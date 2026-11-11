from __future__ import annotations

import base64
import re
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException, status
from PIL import Image, ImageOps
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from . import models
from .config import get_settings

AVATAR_LIBRARY_DIR = Path("assets/avatars")
USER_AVATAR_DIR = AVATAR_LIBRARY_DIR / "custom"
MIME_EXTENSION_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def ensure_avatar_dirs() -> None:
    AVATAR_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    USER_AVATAR_DIR.mkdir(parents=True, exist_ok=True)


def resolve_avatar_asset(
    db: Session, avatar_asset_id: str | None, actor: models.User | None = None
) -> models.AvatarAsset | None:
    if avatar_asset_id is None:
        return None
    asset = db.scalar(
        select(models.AvatarAsset)
        .where(models.AvatarAsset.id == avatar_asset_id)
        .with_for_update()
    )
    if not asset or (actor is not None and not can_access_asset(db, asset, actor)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Avatar asset not found"
        )
    return asset


def is_bundled_avatar(asset: models.AvatarAsset) -> bool:
    return bool(
        asset.tenant_id is None
        and asset.created_by_id is None
        and asset.is_default
        and re.fullmatch(
            r"avatars/library/default-avatar-(?:0[1-9]|10)\.svg", asset.file_path or ""
        )
    )


def safe_external_avatar_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return value
    except ValueError:
        pass
    return None


def avatar_public_url(asset: models.AvatarAsset | None) -> str | None:
    if not asset:
        return None
    if asset.file_path or asset.data_url:
        version = asset.updated_at.isoformat() if asset.updated_at else asset.id
        return f"/avatars/{asset.id}/image?v={version}"
    return safe_external_avatar_url(asset.external_url)


def user_avatar_url(user: models.User) -> str | None:
    resolved = avatar_public_url(user.avatar_asset)
    if resolved:
        return resolved
    if user.profile_image_key:
        version = user.updated_at.isoformat() if user.updated_at else user.id
        return f"/users/{user.id}/avatar-image?v={version}"
    return safe_external_avatar_url(user.profile_image_url)


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    match = re.fullmatch(r"data:(?P<mime>[\w+/.-]+);base64,(?P<data>.+)", data_url)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid avatar data URL"
        )

    mime_type = match.group("mime")
    encoded_data = match.group("data")
    if mime_type not in MIME_EXTENSION_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image type. Use PNG, JPEG, or WebP.",
        )

    if len(encoded_data) > ((max_avatar_bytes() + 2) // 3) * 4:
        raise HTTPException(
            status_code=413, detail="Avatar exceeds the configured size limit"
        )
    try:
        binary = base64.b64decode(encoded_data, validate=True)
    except (base64.binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not decode avatar image",
        ) from exc

    return mime_type, binary


def create_avatar_asset_from_data_url(
    db: Session,
    data_url: str,
    *,
    creator_id: str,
    name: str = "Custom upload",
    is_default: bool = False,
) -> models.AvatarAsset:
    creator = db.get(models.User, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Avatar creator not found")
    mime, binary = _decode_data_url(data_url)
    asset = store_avatar_image(db, load_avatar_image(binary, mime_type=mime), creator)
    asset.name = name
    asset.is_default = is_default
    db.add(asset)
    db.flush()
    return asset


def max_avatar_bytes() -> int:
    return get_settings().avatar_max_file_size_mb * 1024 * 1024


def load_avatar_image(data: bytes, *, mime_type: str | None = None) -> Image.Image:
    if not data or len(data) > max_avatar_bytes():
        raise HTTPException(
            status_code=413, detail="Avatar exceeds the configured size limit"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                detected = Image.MIME.get(source.format)
                if detected not in MIME_EXTENSION_MAP or (
                    mime_type and mime_type != detected
                ):
                    raise ValueError("Image type does not match its signature")
                if (
                    min(source.size) < 16
                    or source.width * source.height > get_settings().avatar_max_pixels
                ):
                    raise ValueError(
                        "Image dimensions must be at least 16px and within the pixel limit"
                    )
                source.verify()
            with Image.open(BytesIO(data)) as source:
                source.load()
                # New pixels discard EXIF, comments, ICC and other metadata.
                oriented = ImageOps.exif_transpose(source).convert("RGB")
                clean = Image.new("RGB", oriented.size)
                clean.paste(oriented)
                return clean
    except (
        ValueError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid avatar: use a valid JPEG, PNG or WebP within the dimension limit",
        ) from exc


def apply_avatar_crop(image: Image.Image, crop: dict) -> Image.Image:
    import math

    values = [
        crop.get("x", 0),
        crop.get("y", 0),
        crop.get("width", image.width),
        crop.get("height", image.height),
    ]
    if not all(math.isfinite(value) for value in values) or crop.get("rotate", 0) != 0:
        raise HTTPException(status_code=400, detail="Invalid crop area")
    x, y, width, height = values
    if (
        min(x, y) < 0
        or min(width, height) < 1
        or x + width > image.width + 1
        or y + height > image.height + 1
    ):
        raise HTTPException(status_code=400, detail="Crop must be inside the image")
    left = max(0, round(crop.get("x", 0)))
    top = max(0, round(crop.get("y", 0)))
    width = max(1, round(crop.get("width", image.width)))
    height = max(1, round(crop.get("height", image.height)))
    right = min(image.width, left + width)
    bottom = min(image.height, top + height)
    if right <= left or bottom <= top:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid crop area"
        )
    return image.crop((left, top, right, bottom))


def encode_avatar(image: Image.Image, size: int) -> bytes:
    output = BytesIO()
    ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS).save(
        output, format="WEBP", quality=85
    )
    return output.getvalue()


def can_access_asset(
    db: Session, asset: models.AvatarAsset, actor: models.User
) -> bool:
    if asset.tenant_id is not None:
        if str(asset.tenant_id) != str(actor.tenant_id):
            return False
        return (
            asset.is_default
            or asset.created_by_id == actor.id
            or actor.role in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}
        )
    if is_bundled_avatar(asset):
        return True  # Bundled library artwork only.
    creator = db.get(models.User, asset.created_by_id) if asset.created_by_id else None
    return bool(
        creator
        and creator.tenant_id == actor.tenant_id
        and (
            asset.is_default
            or creator.id == actor.id
            or actor.role in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}
        )
    )


@dataclass(frozen=True)
class AvatarFiles:
    id: str
    file_path: str | None
    thumbnail_path: str | None
    storage_provider: str | None


def avatar_files(asset) -> AvatarFiles:
    return AvatarFiles(
        asset.id, asset.file_path, asset.thumbnail_path, asset.storage_provider
    )


def _provider(asset):
    return getattr(asset, "storage_provider", None)


def remove_avatar_asset_file(asset: models.AvatarAsset) -> None:
    paths = [asset.file_path, getattr(asset, "thumbnail_path", None)]
    if _provider(asset) == "minio":
        from .services.minio_media_service import _get_minio_client, _require_bucket

        client = _get_minio_client()
        for path in filter(None, paths):
            client.delete_object(Bucket=_require_bucket(), Key=path)
    elif _provider(asset) == "local":
        from .storage.local import LocalAdapter

        adapter = LocalAdapter(get_settings().media_root, "/uploads")
        for path in filter(None, paths):
            adapter.delete(path)
    elif asset.file_path:
        root = Path("assets").resolve()
        path = (root / asset.file_path).resolve()
        if path.is_relative_to(root):
            path.unlink(missing_ok=True)


@event.listens_for(Session, "after_commit")
def _cleanup_committed(session):
    session.info.pop("avatar_rollback", None)
    for asset in session.info.pop("avatar_cleanup", []):
        try:
            remove_avatar_asset_file(asset)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Unable to clean unreferenced avatar %s", asset.id
            )


@event.listens_for(Session, "after_rollback")
def _cleanup_rollback(session):
    session.info.pop("avatar_cleanup", None)
    for asset in session.info.pop("avatar_rollback", []):
        try:
            remove_avatar_asset_file(asset)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Unable to clean rolled back avatar %s", asset.id
            )


@event.listens_for(Session, "after_transaction_end")
def _cleanup_closed_transaction(session, transaction):
    if transaction.parent is None and session.info.get("avatar_rollback"):
        # Session.close() rolls back without emitting after_rollback.
        _cleanup_rollback(session)


def maybe_cleanup_custom_avatar(db: Session, asset: models.AvatarAsset | None) -> None:
    if not asset or asset.is_default:
        return
    db.scalar(
        select(models.AvatarAsset)
        .where(models.AvatarAsset.id == asset.id)
        .with_for_update()
    )
    db.flush()
    if db.scalar(
        select(models.User.id).where(models.User.avatar_asset_id == asset.id).limit(1)
    ):
        return
    db.info.setdefault("avatar_cleanup", []).append(avatar_files(asset))
    db.delete(asset)


def assign_user_avatar(
    db: Session, user: models.User, avatar_id: str | None, actor: models.User
) -> None:
    previous = user.avatar_asset
    # Lock the selected asset before assignment so deletion cannot race reuse.
    asset = resolve_avatar_asset(db, avatar_id, actor)
    queue_legacy_avatar_cleanup(db, user)
    user.avatar_asset = asset
    user.profile_image_key = None
    user.profile_image_url = None
    db.flush()
    maybe_cleanup_custom_avatar(db, previous)


def queue_legacy_avatar_cleanup(db: Session, user: models.User) -> None:
    key = user.profile_image_key
    if key and key.startswith(f"avatars/{user.id}/") and ".." not in key:
        asset = models.AvatarAsset(
            id="legacy-" + user.id,
            file_path=key,
            thumbnail_path=key.replace("avatar.webp", "avatar_256.webp")
            if key.endswith("avatar.webp")
            else None,
            storage_provider="minio",
        )
        db.info.setdefault("avatar_cleanup", []).append(avatar_files(asset))


def store_avatar_image(
    db: Session, image: Image.Image, creator: models.User
) -> models.AvatarAsset:
    token = uuid4().hex
    base = f"private-avatars/{creator.tenant_id}/{creator.id}/{token}"
    asset = models.AvatarAsset(
        id=str(uuid4()),
        name="Profile picture",
        tenant_id=creator.tenant_id,
        storage_type=models.AvatarStorageTypeEnum.FILE,
        mime_type="image/webp",
        is_default=False,
        created_by_id=creator.id,
        file_path=base + ".webp",
        thumbnail_path=base + "_128.webp",
    )
    settings = get_settings()
    if (
        not (settings.minio_access_key and settings.minio_secret_key)
        and settings.storage_provider != "local"
    ):
        raise HTTPException(
            status_code=503,
            detail="Private avatar storage requires configured MinIO or local media storage",
        )
    asset.storage_provider = (
        "minio" if settings.minio_access_key and settings.minio_secret_key else "local"
    )
    db.info.setdefault("avatar_rollback", []).append(avatar_files(asset))
    try:
        if asset.storage_provider == "minio":
            from .services.minio_media_service import _get_minio_client, _require_bucket

            client = _get_minio_client()
            for path, size in ((asset.file_path, 512), (asset.thumbnail_path, 128)):
                client.put_object(
                    Bucket=_require_bucket(),
                    Key=path,
                    Body=encode_avatar(image, size),
                    ContentType="image/webp",
                )
        else:
            from .storage.local import LocalAdapter

            adapter = LocalAdapter(settings.media_root, "/uploads")
            for path, size in ((asset.file_path, 512), (asset.thumbnail_path, 128)):
                adapter.save(
                    encode_avatar(image, size), path, content_type="image/webp"
                )
        db.add(asset)
        db.flush()
        return asset
    except Exception:
        db.rollback()
        raise


def set_user_avatar_image(
    db: Session, user: models.User, *, image: Image.Image, actor: models.User
) -> None:
    if user.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    previous_asset = user.avatar_asset
    queue_legacy_avatar_cleanup(db, user)
    try:
        asset = store_avatar_image(db, image, user)
        user.avatar_asset = asset
        user.profile_image_key = None
        user.profile_image_url = None
        user.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.flush()
        maybe_cleanup_custom_avatar(db, previous_asset)
        db.add(
            models.AuditEvent(
                actor_id=actor.id,
                event_type="user.avatar.updated",
                entity_type="user",
                entity_id=user.id,
                payload={"avatar_asset_id": asset.id},
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
    except Exception:
        db.rollback()
        raise


def set_user_avatar_from_data_url(
    db: Session, user: models.User, *, data_url: str, actor: models.User
) -> None:
    mime, binary = _decode_data_url(data_url)
    set_user_avatar_image(
        db, user, image=load_avatar_image(binary, mime_type=mime), actor=actor
    )


def read_avatar_bytes(asset: models.AvatarAsset, *, thumbnail: bool = False) -> bytes:
    path = (
        asset.thumbnail_path if thumbnail and asset.thumbnail_path else asset.file_path
    )
    if not path:
        raise HTTPException(status_code=404, detail="Avatar image not found")
    if _provider(asset) == "minio":
        from contextlib import closing

        from .services.minio_media_service import (
            ClientError,
            _get_minio_client,
            _require_bucket,
        )

        try:
            response = _get_minio_client().get_object(
                Bucket=_require_bucket(), Key=path
            )
        except ClientError as exc:
            missing = exc.response.get("Error", {}).get("Code") in {
                "404",
                "NoSuchKey",
                "NotFound",
            }
            raise HTTPException(
                status_code=404 if missing else 502,
                detail="Avatar image not found"
                if missing
                else "Avatar storage unavailable",
            ) from exc
        with closing(response["Body"]) as body:
            return body.read(max_avatar_bytes() + 1)
    root = Path(
        get_settings().media_root if _provider(asset) == "local" else "assets"
    ).resolve()
    full_path = (root / path).resolve()
    if not full_path.is_relative_to(root) or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Avatar image not found")
    with full_path.open("rb") as stream:
        return stream.read(max_avatar_bytes() + 1)
