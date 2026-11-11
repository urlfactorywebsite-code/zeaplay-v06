from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..avatar_http import AvatarUploadRoute
from ..avatar_utils import (
    _decode_data_url,
    avatar_files,
    avatar_public_url,
    can_access_asset,
    create_avatar_asset_from_data_url,
    encode_avatar,
    is_bundled_avatar,
    load_avatar_image,
    read_avatar_bytes,
)
from ..database import get_db
from ..dependencies import get_current_active_user, get_current_owner

router = APIRouter(prefix="/avatars", tags=["avatars"], route_class=AvatarUploadRoute)


# Reuse dependency markers; FastAPI still resolves them per request.
_db_dependency = Depends(get_db)
_active_dependency = Depends(get_current_active_user)
_owner_dependency = Depends(get_current_owner)


def _decorate_asset(asset: models.AvatarAsset) -> models.AvatarAsset:
    asset.url = avatar_public_url(asset)
    return asset


@router.get("/policy")
def avatar_upload_policy(current_user: models.User = _active_dependency):
    from ..avatar_utils import max_avatar_bytes
    from ..config import get_settings

    return {
        "maxBytes": max_avatar_bytes(),
        "maxPixels": get_settings().avatar_max_pixels,
        "contentTypes": ["image/jpeg", "image/png", "image/webp"],
    }


@router.get("", response_model=list[schemas.AvatarAssetRead])
def list_avatars(
    current_user: models.User = _active_dependency,
    db: Session = _db_dependency,
) -> list[schemas.AvatarAssetRead]:
    stmt = select(models.AvatarAsset).where(
        or_(
            models.AvatarAsset.tenant_id == current_user.tenant_id,
            (
                models.AvatarAsset.tenant_id.is_(None)
                & models.AvatarAsset.is_default.is_(True)
                & models.AvatarAsset.created_by_id.is_(None)
            ),
            models.AvatarAsset.created_by_id == current_user.id,
        )
    )
    if current_user.role not in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        stmt = stmt.where(
            or_(
                models.AvatarAsset.is_default.is_(True),
                models.AvatarAsset.created_by_id == current_user.id,
            )
        )

    assets = db.execute(stmt).scalars().all()
    return [
        _decorate_asset(asset)
        for asset in assets
        if can_access_asset(db, asset, current_user)
    ]


@router.post(
    "", response_model=schemas.AvatarAssetRead, status_code=status.HTTP_201_CREATED
)
def create_avatar_asset(
    payload: schemas.AvatarAssetCreate,
    current_user: models.User = _owner_dependency,
    db: Session = _db_dependency,
) -> schemas.AvatarAssetRead:
    if payload.storage_type == models.AvatarStorageTypeEnum.DATA_URL:
        if not payload.data_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="data_url is required"
            )
        asset = create_avatar_asset_from_data_url(
            db,
            payload.data_url,
            creator_id=current_user.id,
            name=payload.name,
            is_default=True,
        )
    elif payload.storage_type == models.AvatarStorageTypeEnum.EXTERNAL_URL:
        if not payload.external_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="external_url is required",
            )
        asset = models.AvatarAsset(
            name=payload.name,
            storage_type=models.AvatarStorageTypeEnum.EXTERNAL_URL,
            external_url=payload.external_url,
            is_default=True,
            created_by_id=current_user.id,
        )
        db.add(asset)
        db.flush()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File uploads must be provided as base64 data URLs.",
        )

    asset.tenant_id = current_user.tenant_id
    db.commit()
    db.refresh(asset)
    return _decorate_asset(asset)


@router.patch("/{avatar_id}", response_model=schemas.AvatarAssetRead)
def update_avatar_asset(
    avatar_id: str,
    payload: schemas.AvatarAssetUpdate,
    current_user: models.User = _owner_dependency,
    db: Session = _db_dependency,
) -> schemas.AvatarAssetRead:
    asset = db.scalar(
        select(models.AvatarAsset)
        .where(models.AvatarAsset.id == avatar_id)
        .with_for_update()
    )
    if not asset or not can_access_asset(db, asset, current_user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Avatar asset not found"
        )

    if asset.tenant_id is None:
        raise HTTPException(
            status_code=403, detail="Bundled avatars cannot be modified"
        )
    if payload.name is not None:
        asset.name = payload.name
    if payload.data_url:
        replacement = create_avatar_asset_from_data_url(
            db, payload.data_url, creator_id=current_user.id
        )
        if asset.file_path:
            db.info.setdefault("avatar_cleanup", []).append(avatar_files(asset))
        for field in (
            "file_path",
            "thumbnail_path",
            "storage_provider",
            "storage_type",
            "mime_type",
        ):
            setattr(asset, field, getattr(replacement, field))
        asset.data_url = None
        asset.external_url = None
        db.delete(replacement)
    elif payload.external_url is not None:
        if asset.file_path:
            db.info.setdefault("avatar_cleanup", []).append(avatar_files(asset))
        asset.storage_provider = None
        asset.thumbnail_path = None
        asset.storage_type = models.AvatarStorageTypeEnum.EXTERNAL_URL
        asset.external_url = payload.external_url
        asset.file_path = None
        asset.mime_type = None
        asset.data_url = None

    db.commit()
    db.refresh(asset)
    return _decorate_asset(asset)


@router.delete("/{avatar_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_avatar_asset(
    avatar_id: str,
    current_user: models.User = _owner_dependency,
    db: Session = _db_dependency,
) -> None:
    asset = db.scalar(
        select(models.AvatarAsset)
        .where(models.AvatarAsset.id == avatar_id)
        .with_for_update()
    )
    if not asset or not can_access_asset(db, asset, current_user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Avatar asset not found"
        )
    if asset.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Default avatars cannot be removed",
        )

    if db.scalar(
        select(models.User.id).where(models.User.avatar_asset_id == asset.id).limit(1)
    ):
        raise HTTPException(status_code=409, detail="This avatar is still in use")
    if asset.file_path:
        db.info.setdefault("avatar_cleanup", []).append(avatar_files(asset))

    db.delete(asset)
    db.commit()


@router.get("/{avatar_id}/image")
def avatar_image(
    avatar_id: str,
    thumbnail: bool = False,
    db: Session = _db_dependency,
    current_user: models.User = _active_dependency,
):
    asset = db.get(models.AvatarAsset, avatar_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Avatar not found")
    creator = db.get(models.User, asset.created_by_id) if asset.created_by_id else None
    tenant = asset.tenant_id or (creator.tenant_id if creator else None)
    if tenant != current_user.tenant_id and not is_bundled_avatar(asset):
        raise HTTPException(status_code=404, detail="Avatar not found")
    if asset.data_url and not asset.file_path:
        mime, binary = _decode_data_url(asset.data_url)
        binary = encode_avatar(
            load_avatar_image(binary, mime_type=mime), 128 if thumbnail else 512
        )
    else:
        binary = read_avatar_bytes(asset, thumbnail=thumbnail)
        if not is_bundled_avatar(asset) and asset.storage_provider not in {
            "local",
            "minio",
        }:
            binary = encode_avatar(load_avatar_image(binary), 128 if thumbnail else 512)
    return Response(
        binary,
        media_type="image/svg+xml" if is_bundled_avatar(asset) else "image/webp",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
