"""Media Library API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from .. import models, schemas, rate_limit
from ..database import get_db
from ..dependencies import get_current_active_user
from ..services import media_service, minio_media_service

router = APIRouter(prefix="/media", tags=["media"])


def _parse_category(value: Optional[str]) -> Optional[models.MediaCategoryEnum]:
    if not value:
        return None
    try:
        return models.MediaCategoryEnum(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid media category")


@router.post("/presign", response_model=schemas.MediaPresignResponse)
def presign_media_upload(
    payload: schemas.MediaPresignRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> schemas.MediaPresignResponse:
    rate_limit.enforce_presign_rate_limit(current_user.id)
    media_file, upload_url, expires_in = minio_media_service.presign_media_upload(
        db,
        user=current_user,
        purpose=payload.purpose,
        tab=payload.tab,
        file_name=payload.file_name,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
    )
    return schemas.MediaPresignResponse(
        upload_url=upload_url,
        bucket=media_file.bucket,
        object_key=media_file.object_key,
        file_id=media_file.id,
        expires_in=expires_in,
    )


@router.post("/confirm", response_model=schemas.MediaConfirmResponse)
def confirm_media_upload(
    payload: schemas.MediaConfirmRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> schemas.MediaConfirmResponse:
    crop_metadata = payload.crop.model_dump() if payload.crop else None
    media_file = minio_media_service.confirm_media_upload(
        db,
        user=current_user,
        file_id=payload.file_id,
        crop_metadata=crop_metadata,
    )
    return schemas.MediaConfirmResponse(file_id=media_file.id, status=media_file.status.value)


@router.post("/avatar/finalize", response_model=schemas.AvatarFinalizeResponse)
def finalize_avatar_upload(
    payload: schemas.AvatarFinalizeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> schemas.AvatarFinalizeResponse:
    media_file, avatar_key, profile_url = minio_media_service.finalize_avatar_upload(
        db,
        user=current_user,
        file_id=payload.file_id,
        crop_metadata=payload.crop.model_dump(),
    )
    return schemas.AvatarFinalizeResponse(
        file_id=media_file.id,
        profile_image_key=avatar_key,
        profile_image_url=profile_url,
    )


@router.get("/list", response_model=schemas.MediaFileListResponse)
def list_media_files(
    tab: str = Query(...),
    search: Optional[str] = Query(default=None, max_length=255),
    from_date: Optional[datetime] = Query(default=None),
    to_date: Optional[datetime] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=96),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> schemas.MediaFileListResponse:
    items, total = minio_media_service.list_media_files(
        db,
        user=current_user,
        tab=tab,
        search=search,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )
    response_items = [
        schemas.MediaFileListItem(
            id=item.id,
            original_filename=item.original_filename,
            content_type=item.content_type,
            size_bytes=item.size_bytes,
            created_at=item.created_at,
            read_url=minio_media_service.generate_presigned_get(item.bucket, item.object_key),
        )
        for item in items
    ]
    return schemas.MediaFileListResponse(
        items=response_items,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/upload",
    response_model=schemas.MediaItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_media(
    file: UploadFile = File(...),
    category: Optional[str] = Form(default=None),
    original_id: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    category_enum = _parse_category(category)
    item = await media_service.create_media_item(
        db,
        owner=current_user,
        upload=file,
        category=category_enum,
        original_id=original_id,
    )
    return item


@router.get("", response_model=schemas.MediaListResponse)
def list_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=96),
    q: Optional[str] = Query(default=None, max_length=255),
    category: Optional[models.MediaCategoryEnum] = Query(default=None),
    sort: schemas.MediaSortOption = Query(default=schemas.MediaSortOption.CREATED_DESC),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    owner_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    items, total = media_service.list_media_items(
        db,
        user=current_user,
        page=page,
        page_size=page_size,
        q=q,
        category=category,
        sort=sort.value,
        date_from=date_from,
        date_to=date_to,
        owner_id=owner_id,
    )
    return schemas.MediaListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/{media_id}", response_model=schemas.MediaItemRead)
def get_media(
    media_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    return media_service.get_media_item(db, media_id=media_id, user=current_user)


@router.patch("/{media_id}", response_model=schemas.MediaItemRead)
def rename_media(
    media_id: str,
    payload: schemas.MediaUpdateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    if not payload.filename:
        return media_service.get_media_item(db, media_id=media_id, user=current_user)
    return media_service.rename_media_item(
        db,
        media_id=media_id,
        user=current_user,
        filename=payload.filename,
    )


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(
    media_id: str,
    hard: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    media_file = db.get(models.MediaFile, media_id)
    if media_file:
        if media_file.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
        if current_user.role != models.RoleEnum.OWNER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner privileges required")
        minio_media_service.delete_media_file(db, media_file=media_file)
        return
    media_service.delete_media_item(db, media_id=media_id, user=current_user, hard=hard)


@router.post("/{media_id}/replace", response_model=schemas.MediaItemRead)
async def replace_media(
    media_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    return await media_service.replace_media_item(
        db,
        media_id=media_id,
        user=current_user,
        upload=file,
    )


@router.post("/external/connect", response_model=schemas.MediaProviderStatusResponse)
def connect_provider(
    payload: schemas.MediaProviderConnectRequest,
):
    adapter = media_service.get_adapter(payload.provider)
    health = adapter.health()
    if not adapter.is_configured:
        status_label = "missing_env"
    else:
        status_label = "connected" if health.ok else "error"
    return schemas.MediaProviderStatusResponse(
        provider=payload.provider,
        status=status_label,
        details=health.details,
    )


@router.post("/bulk-delete", response_model=schemas.MediaBulkDeleteResponse)
def bulk_delete_media(
    payload: schemas.MediaBulkDeleteRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    deleted = media_service.bulk_delete_media(
        db,
        user=current_user,
        media_ids=payload.ids,
        hard=payload.hard,
    )
    return schemas.MediaBulkDeleteResponse(deleted=deleted)
