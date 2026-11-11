# ruff: noqa: B008
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_owner
from . import service as svc
from .http import BackupRoute
from .models import BackupJob, ExportPreset

router = APIRouter(
    prefix="/admin/data/manager", tags=["backup-manager"], route_class=BackupRoute
)


def manager_db(
    owner: models.User = Depends(get_current_owner), db: Session = Depends(get_db)
):
    del owner
    if not {"backup_jobs", "export_presets"} <= set(
        svc.inspect(db.get_bind()).get_table_names()
    ):
        svc.fail("Backup Manager database migration is required before use.", 503)
    return db


class ExportSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["all", "custom"] = "all"
    datasets: list[str] = Field(default_factory=list, max_length=150)
    format: Literal["csv", "json"] = "csv"
    packaging: Literal["zip"] = "zip"
    include_related: bool = True
    acknowledge_dependencies: bool = False


class PresetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    settings: ExportSettings


class PreviewPayload(BaseModel):
    selected: list[str] = Field(default_factory=list, max_length=150)
    mode: Literal["insert", "update"] = "insert"
    provision_users: bool = False


class ConfirmPayload(BaseModel):
    confirmation: Literal["RESTORE"]
    preview_token: str


def job_for(db, owner, job_id):
    job = db.scalar(
        select(BackupJob)
        .where(BackupJob.id == job_id, BackupJob.tenant_id == str(owner.tenant_id))
        .with_for_update()
    )
    if not job:
        svc.fail("Job not found.", 404)
    if job.expires_at < datetime.now(UTC).replace(tzinfo=None):
        svc.fail("Backup expired; generate or upload it again.", 410)
    return job


def public_job(job):
    return {
        "id": job.id,
        "operation": job.operation,
        "scope": job.settings.get("scope", "custom"),
        "requested_by": job.requested_by,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "status": job.status,
        "record_count": job.record_count,
        "file_size": job.file_size,
        "error": job.error,
        "report": {k: v for k, v in job.report.items() if k != "download_ticket"},
        "download_available": job.operation == "Export"
        and job.status == "Completed"
        and job.expires_at > datetime.now(UTC).replace(tzinfo=None)
        and svc.path_for(job.id, ".zip").is_file(),
        "expires_at": job.expires_at,
    }


@router.get("/catalog")
def get_catalog(
    owner: models.User = Depends(get_current_owner), db: Session = Depends(manager_db)
):
    svc.cleanup(db)
    return svc.catalog(db, owner.tenant_id)


@router.get("/jobs")
def history(
    owner: models.User = Depends(get_current_owner), db: Session = Depends(manager_db)
):
    svc.cleanup(db)
    return [
        public_job(job)
        for job in db.scalars(
            select(BackupJob)
            .where(BackupJob.tenant_id == str(owner.tenant_id))
            .order_by(BackupJob.started_at.desc())
            .limit(100)
        )
    ]


@router.post("/exports", status_code=202)
def create_export(
    payload: ExportSettings,
    background: BackgroundTasks,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    svc.cleanup(db)
    if db.get_bind().dialect.name == "postgresql":
        lock_key = int(
            hashlib.sha256(str(owner.tenant_id).encode()).hexdigest()[:15], 16
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    svc.resolve_selection(db, owner.tenant_id, payload.model_dump())
    active = db.scalar(
        select(BackupJob.id)
        .where(
            BackupJob.tenant_id == str(owner.tenant_id),
            BackupJob.operation == "Export",
            BackupJob.status.in_(["Queued", "Processing"]),
        )
        .limit(1)
    )
    if active:
        svc.fail("An export is already running for this workspace.", 409)
    job = svc.new_job(db, owner, "Export", payload.model_dump())
    background.add_task(svc.run_export, job.id)
    return public_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel(
    job_id: str,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    job = job_for(db, owner, job_id)
    if job.status not in ("Queued", "Processing"):
        svc.fail("Only queued or processing jobs can be cancelled.", 409)
    job.status, job.completed_at = "Cancelled", datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    if job.operation == "Import":
        svc.path_for(job.id, ".stage").unlink(missing_ok=True)
    return public_job(job)


@router.post("/jobs/{job_id}/download-ticket")
def download_ticket(
    job_id: str,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    job = job_for(db, owner, job_id)
    if job.operation != "Export" or job.status != "Completed":
        svc.fail("No completed archive is available.", 409)
    ticket = secrets.token_urlsafe(32)
    job.report = {
        **job.report,
        "download_ticket": {
            "hash": hashlib.sha256(ticket.encode()).hexdigest(),
            "expires": (
                datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=60)
            ).isoformat(),
        },
    }
    db.commit()
    return {"ticket": ticket}


@router.get("/jobs/{job_id}/download")
def download(
    job_id: str,
    ticket: str = Query(min_length=40, max_length=100),
    db: Session = Depends(get_db),
):
    if "backup_jobs" not in svc.inspect(db.get_bind()).get_table_names():
        svc.fail("Archive unavailable.", 410)
    # A one-use, job-scoped capability permits a native browser download without
    # buffering the archive in JS or putting the user's access token in a URL.
    job = db.scalar(select(BackupJob).where(BackupJob.id == job_id).with_for_update())
    stored = job.report.get("download_ticket", {}) if job else {}
    if (
        not stored
        or not secrets.compare_digest(
            stored["hash"], hashlib.sha256(ticket.encode()).hexdigest()
        )
        or stored["expires"] < datetime.now(UTC).replace(tzinfo=None).isoformat()
    ):
        svc.fail("Download link expired or already used.", 403)
    if (
        job.expires_at < datetime.now(UTC).replace(tzinfo=None)
        or job.status != "Completed"
        or job.operation != "Export"
    ):
        svc.fail("Archive unavailable.", 410)
    actor = db.get(models.User, job.requested_by)
    if (
        not actor
        or str(actor.tenant_id) != job.tenant_id
        or actor.role != models.RoleEnum.OWNER
        or actor.status != models.UserStatusEnum.ACTIVE
    ):
        svc.fail("Permission denied: the requesting owner's access changed.", 403)
    target = svc.path_for(job.id, ".zip")
    if not target.is_file():
        svc.fail("Archive expired or unavailable.", 410)
    job.report = {k: v for k, v in job.report.items() if k != "download_ticket"}
    db.commit()
    return FileResponse(
        target,
        media_type="application/zip",
        filename=f"zea-play-backup-{job.started_at:%Y-%m-%d}-{job.id[:8]}.zip",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.post("/imports/validate")
def validate_upload(
    file: UploadFile = File(),
    dataset: str | None = Form(None),
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    svc.cleanup(db)
    job = svc.new_job(db, owner, "Import", {"scope": "custom"})
    job.status = "Processing"
    db.commit()
    target = svc.path_for(job.id, ".upload")
    try:
        size = 0
        with open(target, "wb") as output:
            while chunk := file.file.read(65536):
                size += len(chunk)
                if size > svc.MAX_UPLOAD:
                    svc.fail("Backup exceeds the 32 MiB upload limit.", 413)
                output.write(chunk)
        warnings = svc.read_upload(job, target, file.filename or "", dataset)
        job.report = {"warnings": warnings}
        job.report = svc.preview(db, job, [], "insert")
        job.report = {**job.report, "preview_token": secrets.token_urlsafe(24)}
        job.record_count = sum(job.report["datasets"].values())
        job.file_size = size
        # Validation is a preview, not a completed import. Keep it queued for confirmation.
        job.status = "Queued"
        db.commit()
        return public_job(job)
    except Exception as exc:
        job.status, job.completed_at = "Failed", datetime.now(UTC).replace(tzinfo=None)
        job.error = (
            exc.detail
            if isinstance(exc, HTTPException)
            else "Invalid backup structure or field types."
        )
        db.commit()
        svc.path_for(job.id, ".stage").unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        svc.fail(job.error)
    finally:
        target.unlink(missing_ok=True)
        file.file.close()


@router.post("/imports/{job_id}/preview")
def preview_import(
    job_id: str,
    payload: PreviewPayload,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    job = job_for(db, owner, job_id)
    if job.operation != "Import" or job.status != "Queued":
        svc.fail("Upload the backup again to start a new restore.", 409)
    job.report = {
        **svc.preview(
            db,
            job,
            payload.selected,
            payload.mode,
            provision_users=payload.provision_users,
        ),
        "preview_token": secrets.token_urlsafe(24),
    }
    db.commit()
    return public_job(job)


@router.post("/imports/{job_id}/confirm")
def confirm_import(
    job_id: str,
    payload: ConfirmPayload,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    # End auth/read transaction; restore gets its own serializable, atomic transaction.
    tenant_id, owner_id = str(owner.tenant_id), owner.id
    db.rollback()
    bind = db.get_bind()
    try:
        with bind.connect().execution_options(  # noqa: SIM117 - explicit transaction lifetime
            isolation_level="SERIALIZABLE"
        ) as connection:
            with connection.begin():
                if bind.dialect.name == "sqlite":
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    connection.execute(text("SET LOCAL statement_timeout = '120s'"))
                    # Prevent tenant drift and concurrent writes to legacy global tables.
                    present = set(svc.inspect(connection).get_table_names())
                    names = sorted(
                        t.name
                        for t in svc.Base.metadata.tables.values()
                        if t.name in present
                        and t.name not in ("backup_jobs", "export_presets")
                    )
                    for name in names:
                        connection.exec_driver_sql(
                            f'LOCK TABLE "{name}" IN SHARE ROW EXCLUSIVE MODE'
                        )
                with Session(bind=connection) as restore_session:
                    proxy = type("OwnerScope", (), {"tenant_id": tenant_id})()
                    job = job_for(restore_session, proxy, job_id)
                    if (
                        job.operation != "Import"
                        or job.status != "Queued"
                        or not job.report.get("valid")
                        or not secrets.compare_digest(
                            job.report.get("preview_token", ""), payload.preview_token
                        )
                    ):
                        svc.fail(
                            "Restore requires a valid, current preview and explicit confirmation.",
                            409,
                        )
                    job.status = "Processing"
                    fresh = svc.preview(
                        restore_session,
                        job,
                        job.report["selected"],
                        job.report["mode"],
                        save_baselines=False,
                        provision_users=job.report.get("provision_users", False),
                    )
                    if not fresh["valid"]:
                        svc.fail("Restore conflicts changed; validate again.", 409)
                    # Keep original preview baselines: preview above validates constraints,
                    # but must not replace the original optimistic concurrency fingerprints.
                    job.record_count = svc.restore(restore_session, job)
                    job.status, job.completed_at = (
                        "Completed",
                        datetime.now(UTC).replace(tzinfo=None),
                    )
                    restore_session.add(
                        models.AuditEvent(
                            id=str(uuid.uuid4()),
                            actor_id=owner_id,
                            event_type="BACKUP_RESTORE",
                            entity_type="backup_job",
                            entity_id=job_id,
                            payload={
                                "job_id": job_id,
                                "record_count": job.record_count,
                                "provisioned_users": job.report.get("impact", {}).get(
                                    "provision", 0
                                ),
                            },
                        )
                    )
                    restore_session.flush()
                    result = public_job(job)
        svc.path_for(job_id, ".stage").unlink(missing_ok=True)
        return result
    except HTTPException as exc:
        failed = db.scalar(
            select(BackupJob).where(
                BackupJob.id == job_id,
                BackupJob.tenant_id == tenant_id,
                BackupJob.operation == "Import",
                BackupJob.status == "Queued",
            )
        )
        if failed:
            failed.error = str(exc.detail)[:500]
            failed.status, failed.completed_at = (
                "Failed",
                datetime.now(UTC).replace(tzinfo=None),
            )
            db.commit()
        raise
    except SQLAlchemyError:
        # All writes rolled back. Do not leak SQL, values, or constraints.
        failed = db.scalar(
            select(BackupJob).where(
                BackupJob.id == job_id,
                BackupJob.tenant_id == tenant_id,
                BackupJob.operation == "Import",
                BackupJob.status == "Queued",
            )
        )
        if failed:
            failed.status, failed.error, failed.completed_at = (
                "Failed",
                "Restore conflict: transaction rolled back; no records were changed.",
                datetime.now(UTC).replace(tzinfo=None),
            )
            db.commit()
        svc.fail(
            "Restore conflict: no records were changed. Validate the backup again.", 409
        )


@router.get("/presets")
def list_presets(
    owner: models.User = Depends(get_current_owner), db: Session = Depends(manager_db)
):
    return db.scalars(
        select(ExportPreset)
        .where(
            ExportPreset.tenant_id == str(owner.tenant_id),
            ExportPreset.creator_id == owner.id,
        )
        .order_by(ExportPreset.updated_at.desc())
    ).all()


@router.post("/presets")
def save_preset(
    payload: PresetPayload,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    svc.resolve_selection(db, owner.tenant_id, payload.settings.model_dump())
    name = payload.name.strip()
    if not name:
        svc.fail("Configuration name is required.")
    preset = ExportPreset(
        id=str(uuid.uuid4()),
        tenant_id=str(owner.tenant_id),
        creator_id=owner.id,
        name=name,
        settings=payload.settings.model_dump(),
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


def preset_for(db, owner, preset_id):
    preset = db.scalar(
        select(ExportPreset).where(
            ExportPreset.id == preset_id,
            ExportPreset.tenant_id == str(owner.tenant_id),
            ExportPreset.creator_id == owner.id,
        )
    )
    if not preset:
        svc.fail("Configuration not found.", 404)
    return preset


@router.put("/presets/{preset_id}")
def edit_preset(
    preset_id: str,
    payload: PresetPayload,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    preset = preset_for(db, owner, preset_id)
    svc.resolve_selection(db, owner.tenant_id, payload.settings.model_dump())
    if not payload.name.strip():
        svc.fail("Configuration name is required.")
    preset.name, preset.settings, preset.updated_at = (
        payload.name.strip(),
        payload.settings.model_dump(),
        datetime.now(UTC).replace(tzinfo=None),
    )
    db.commit()
    return {"id": preset.id, "name": preset.name, "settings": preset.settings}


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(
    preset_id: str,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    db.delete(preset_for(db, owner, preset_id))
    db.commit()


@router.post("/presets/{preset_id}/run", status_code=202)
def run_preset(
    preset_id: str,
    background: BackgroundTasks,
    owner: models.User = Depends(get_current_owner),
    db: Session = Depends(manager_db),
):
    preset = preset_for(db, owner, preset_id)
    return create_export(ExportSettings(**preset.settings), background, owner, db)
