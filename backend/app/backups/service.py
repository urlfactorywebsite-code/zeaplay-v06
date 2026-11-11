from __future__ import annotations

import csv
import enum
import hashlib
import io
import json
import logging
import os
import secrets
import sqlite3
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    Uuid,
    and_,
    func,
    inspect,
    literal,
    select,
    text,
    true,
)
from sqlalchemy.types import TypeDecorator

from .. import models
from ..version import APP_VERSION
from ..auth import hash_password
from ..database import Base, SessionLocal
from .models import BackupJob
from .registry import (
    EXCLUDED,
    FIELDS,
    LEGACY_TASK_AUDIT_FIELDS,
    OMITTED_FIELDS,
    PHASE1_SUBTASK_FIELDS,
    PHASE2_REWARD_FIELDS,
    dataset_id,
    dependencies,
    references,
    tables,
)
from .scope import ACTOR_OWNED
from .scope import columns as scoped_columns
from .scope import predicate as workspace_scope

log = logging.getLogger(__name__)
VERSION = 1
TTL = timedelta(hours=24)
TIMEOUT = 1800
MAX_UPLOAD = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_CELL = 8 * 1024 * 1024
MAX_RECORDS = 250_000
ROOT = Path(
    os.environ.get(
        "ZEA_BACKUP_DIR", str(Path(tempfile.gettempdir()) / "zea-play-private-backups")
    )
)
csv.field_size_limit(MAX_CELL)


def fail(message, code=422):
    raise HTTPException(code, message)


def path_for(job_id, suffix):
    # Never accept a filename or path from an upload or manifest.
    uuid.UUID(str(job_id))
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    return ROOT / f"{job_id}{suffix}"


def json_value(value):
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (datetime, date, uuid.UUID)):
        return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
    return value


def encode(value):
    return json.dumps(
        value,
        default=json_value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def fingerprint(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def assert_isolated(db, tenant_id):
    """Global business tables have no tenant key: refuse ambiguous shared databases.

    Check every loaded tenant-bearing table, including credential configuration,
    without reading secret columns. No global export/reset is safe in a shared DB.
    """
    present = set(
        inspect(db.get_bind() if hasattr(db, "get_bind") else db).get_table_names()
    )
    for table in Base.metadata.tables.values():
        if (
            table.name not in present
            or "tenant_id" not in table.c
            or table.name in {"backup_jobs", "export_presets"}
        ):
            continue
        column = table.c.tenant_id
        value = (
            uuid.UUID(str(tenant_id))
            if isinstance(column.type, Uuid)
            else str(tenant_id)
        )
        if db.execute(
            select(column).where(column.is_not(None), column != value).limit(1)
        ).first():
            fail(
                "Permission denied: global business tables require an isolated workspace database.",
                403,
            )


def legacy_templates(db, table):
    """Support the shared pre-tenant template table without migrating on reads."""
    return table.name == "email_templates" and "tenant_id" not in {
        column["name"]
        for column in inspect(
            db.get_bind() if hasattr(db, "get_bind") else db
        ).get_columns(table.name)
    }


def record_scope(db, table, tenant_id):
    return (
        true()
        if legacy_templates(db, table)
        else workspace_scope(table.name, str(tenant_id))
    )


def record_columns(db, table, tenant_id, exporting=False):
    if legacy_templates(db, table):
        return [
            literal(str(tenant_id)).label(field)
            if field == "tenant_id"
            else table.c[field]
            for field in FIELDS[table.name].split()
        ]
    return (
        scoped_columns(table, tenant_id)
        if exporting
        else [table.c[field] for field in FIELDS[table.name].split()]
    )


def catalog(db, tenant_id):
    inspector = inspect(db.get_bind() if hasattr(db, "get_bind") else db)
    present = set(inspector.get_table_names())
    column_map = inspector.get_multi_columns(filter_names=sorted(present & set(FIELDS)))
    known = tables()
    unknown = sorted(present - set(FIELDS) - EXCLUDED - {"alembic_version"})
    result = []
    for key, table in known.items():
        if table.name not in present:
            continue
        columns = {c["name"] for c in column_map[(None, table.name)]}
        unreviewed = (
            columns
            - set(FIELDS[table.name].split())
            - OMITTED_FIELDS.get(table.name, set())
        )
        unknown.extend(f"{table.name}.{column}" for column in sorted(unreviewed))
        compatible_fields = set(FIELDS[table.name].split())
        if table.name == "email_templates" and "tenant_id" not in columns:
            compatible_fields.remove("tenant_id")
        if not compatible_fields <= columns:
            fail(f"Unsupported schema: dataset {key} needs a database migration.", 409)
        result.append(
            {
                "id": key,
                "name": key.replace("-", " ").title(),
                "count": db.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(record_scope(db, table, tenant_id))
                ),
                "description": "Business records"
                if key != "users"
                else "Profiles only; credentials excluded",
                "dependencies": dependencies(table),
            }
        )
    return {
        "datasets": result,
        "unregistered_tables": unknown,
        "limitations": [
            "Storage files are referenced, not embedded; back up media/object storage separately.",
            "Credentials, push subscriptions, webhook integrations and opaque audit payloads are excluded.",
            "Rich release-note HTML/CSS/JS and opaque event payloads are excluded; those datasets contain metadata only.",
            "Missing users need explicit Owner-approved inactive-account provisioning, followed by password reset and activation in Users.",
            "Records are scoped to this workspace through tenant keys and required ownership relationships; optional references to other workspaces are cleared in exports.",
            "Shared reference/settings datasets (including departments, rewards and feature flags) apply across this installation. Actorless audit records and records with required cross-workspace relationships are excluded.",
            "Older email-template tables without tenant keys are shared installation settings; their layout is supported without changing the database schema.",
        ],
    }


def resolve_selection(db, tenant, settings):
    info = catalog(db, tenant)
    available = {d["id"] for d in info["datasets"]}
    selected = available if settings["scope"] == "all" else set(settings["datasets"])
    if settings["scope"] == "all" and info["unregistered_tables"]:
        fail(
            "Entire workspace export blocked: unregistered business tables need review.",
            409,
        )
    if not selected or not selected <= available:
        fail("Select supported datasets.")
    if settings["include_related"]:
        while True:
            expanded = selected | {
                dep
                for key in selected
                for dep in dependencies(tables()[key])
                if dep in available
            }
            if expanded == selected:
                break
            selected = expanded
    missing = sorted(
        {
            dep
            for key in selected
            for dep in dependencies(tables()[key])
            if dep not in selected
        }
    )
    if missing and not settings.get("acknowledge_dependencies"):
        fail("Missing required dependencies: " + ", ".join(missing))
    return sorted(selected), info, missing


def new_job(db, owner, operation, settings):
    job = BackupJob(
        id=str(uuid.uuid4()),
        tenant_id=str(owner.tenant_id),
        requested_by=owner.id,
        operation=operation,
        status="Queued",
        settings=settings,
        report={},
        expires_at=datetime.now(UTC).replace(tzinfo=None) + TTL,
    )
    db.add(job)
    db.commit()
    return job


def cleanup(db):
    now = datetime.now(UTC).replace(tzinfo=None)
    # A bounded batch on each manager request; archives are never served past expiry.
    expired = db.scalars(
        select(BackupJob).where(BackupJob.expires_at < now).limit(100)
    ).all()
    for job in expired:
        if job.status in ("Queued", "Processing"):
            job.status, job.error, job.completed_at = (
                "Cancelled",
                "Backup or import preview expired.",
                now,
            )
        for suffix in (".zip", ".part", ".stage", ".upload"):
            try:
                path_for(job.id, suffix).unlink(missing_ok=True)
            except OSError:
                log.warning("backup_cleanup_file_busy", extra={"job_id": job.id})
    stale = db.scalars(
        select(BackupJob).where(
            BackupJob.status.in_(["Queued", "Processing"]),
            BackupJob.operation == "Export",
            BackupJob.started_at < now - timedelta(seconds=TIMEOUT),
        )
    ).all()
    for job in stale:
        job.status, job.error, job.completed_at = (
            "Failed",
            "Job timed out or worker stopped; run a new job.",
            now,
        )
    db.commit()


def check_cancel(job_id, started):
    if time.monotonic() - started > TIMEOUT:
        fail("Export timed out; choose fewer datasets.", 408)
    with SessionLocal() as control:
        status = control.scalar(select(BackupJob.status).where(BackupJob.id == job_id))
    if status not in ("Queued", "Processing"):
        fail("Export cancelled or no longer active.", 409)


def export_archive(
    db, job, check=lambda: None, progress=lambda count, completed, total: None
):
    selected, info, missing = resolve_selection(db, job.tenant_id, job.settings)
    manifest = {
        "backup_schema_version": VERSION,
        "application_version": APP_VERSION,
        "exported_at": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
        "workspace_id": job.tenant_id,
        "format": job.settings["format"],
        "scope": job.settings["scope"],
        "selected_datasets": selected,
        "files": {},
        "completion_status": "completed",
        "limitations": info["limitations"],
        "missing_dependencies": missing,
        "csv_encoding": "json-cells-v1",
    }
    part = path_for(job.id, ".part")
    total, bytes_written = 0, 0
    try:
        with zipfile.ZipFile(
            part,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for key in selected:
                check()
                table = tables()[key]
                fields = FIELDS[table.name].split()
                name = f"data/{key}.{job.settings['format']}"
                digest, count = hashlib.sha256(), 0
                with archive.open(name, "w", force_zip64=True) as output:

                    def write(chunk, digest=digest):
                        nonlocal bytes_written
                        data = chunk.encode("utf-8")
                        bytes_written += len(data)
                        if bytes_written > 8 * 1024**3:
                            fail(
                                "Export exceeds 8 GiB safety limit; select fewer datasets."
                            )
                        digest.update(data)
                        output.write(
                            data
                        )  # disk-backed ZIP compression applies backpressure

                    if job.settings["format"] == "csv":
                        buffer = io.StringIO(newline="")
                        writer = csv.writer(buffer, lineterminator="\r\n")
                        writer.writerow(fields)
                        write(buffer.getvalue())
                    else:
                        write("[")
                    query = (
                        select(
                            *record_columns(db, table, job.tenant_id, exporting=True)
                        )
                        .where(record_scope(db, table, job.tenant_id))
                        .order_by(*table.primary_key.columns)
                    )
                    # One server-side cursor, at most 500 rows per fetch, same snapshot for every file.
                    result = db.execute(query.execution_options(yield_per=500))
                    for row in result.mappings():
                        record = {field: json_value(row[field]) for field in fields}
                        serialized = encode(record)
                        if len(serialized.encode("utf-8")) > MAX_CELL:
                            fail(f"Record in {key} exceeds the supported row size.")
                        if job.settings["format"] == "csv":
                            buffer.seek(0)
                            buffer.truncate(0)
                            # JSON-encoded cells are reversible and begin with a quote for strings,
                            # preventing spreadsheet formulas without changing user data.
                            writer.writerow([encode(record[field]) for field in fields])
                            write(buffer.getvalue())
                        else:
                            write(("," if count else "") + serialized)
                        count += 1
                        if count % 500 == 0:
                            check()
                    result.close()
                    if job.settings["format"] == "json":
                        write("]")
                total += count
                manifest["files"][key] = {
                    "path": name,
                    "record_count": count,
                    "sha256": digest.hexdigest(),
                    "fields": fields,
                    "dependencies": dependencies(table),
                }
                progress(total, len(manifest["files"]), len(selected))
            check()
            archive.writestr("manifest.json", encode(manifest))
        return manifest, total, part
    except Exception:
        part.unlink(missing_ok=True)
        raise


def run_export(job_id):
    started = time.monotonic()
    with SessionLocal() as control:
        job = control.get(BackupJob, job_id)
        if not job or job.status != "Queued":
            return
        changed = (
            control.query(BackupJob)
            .filter(BackupJob.id == job_id, BackupJob.status == "Queued")
            .update({"status": "Processing"})
        )
        control.commit()
        if not changed:
            return
        try:
            bind = control.get_bind()
            with bind.connect().execution_options(  # noqa: SIM117 - explicit transaction lifetime
                isolation_level="REPEATABLE READ"
                if bind.dialect.name == "postgresql"
                else "SERIALIZABLE"
            ) as connection:
                with connection.begin():
                    if bind.dialect.name == "sqlite":
                        connection.exec_driver_sql("BEGIN")
                    else:
                        connection.execute(text("SET LOCAL statement_timeout = '120s'"))

                    def progress(count, completed, total):
                        # SQLite readers block writes without WAL. Status tracking still
                        # works there; PostgreSQL additionally records dataset progress.
                        if bind.dialect.name == "postgresql":
                            control.query(BackupJob).filter(
                                BackupJob.id == job_id, BackupJob.status == "Processing"
                            ).update(
                                {
                                    "record_count": count,
                                    "report": {
                                        "progress": {
                                            "completed_files": completed,
                                            "total_files": total,
                                        }
                                    },
                                }
                            )
                            control.commit()

                    manifest, count, part = export_archive(
                        connection, job, lambda: check_cancel(job_id, started), progress
                    )
            # Persist success only after the central directory and manifest have been written.
            control.refresh(job)
            if job.status != "Processing":
                part.unlink(missing_ok=True)
                return
            target = path_for(job_id, ".zip")
            part.replace(target)
            job.status, job.record_count, job.file_size = (
                "Completed",
                count,
                target.stat().st_size,
            )
            job.report = {"manifest": manifest}
            log.info(
                "backup_export_completed",
                extra={"job_id": job_id, "records": count, "bytes": job.file_size},
            )
        except Exception as exc:  # noqa: BLE001 - background failure boundary
            control.refresh(job)
            if job.status != "Cancelled":
                job.status = "Failed"
                job.error = (
                    exc.detail
                    if isinstance(exc, HTTPException)
                    else "Export failed; no complete archive was published."
                )
            path_for(job_id, ".part").unlink(missing_ok=True)
            log.warning(
                "backup_export_failed",
                extra={"job_id": job_id, "error_type": type(exc).__name__},
            )
        job.completed_at = datetime.now(UTC).replace(tzinfo=None)
        control.commit()


@contextmanager
def stage_connection(job_id):
    stage = sqlite3.connect(path_for(job_id, ".stage"))
    stage.execute(
        "CREATE TABLE IF NOT EXISTS records (dataset TEXT, pk TEXT, payload TEXT, baseline TEXT, PRIMARY KEY(dataset, pk))"
    )
    stage.execute("CREATE TABLE IF NOT EXISTS datasets (name TEXT PRIMARY KEY)")
    try:
        with stage:
            yield stage
    finally:
        stage.close()


def convert(column, value):
    if value is None:
        if not column.nullable:
            fail(f"Field {column.name} cannot be null.")
        return None
    typ = column.type
    utc_workflow_time = isinstance(typ, models.UTCDateTime)
    if isinstance(typ, TypeDecorator):
        typ = typ.impl
    try:
        if isinstance(typ, Enum):
            return (
                typ.enum_class(value)
                if typ.enum_class
                else value
                if value in typ.enums
                else fail(f"Invalid enum {column.name}.")
            )
        if isinstance(typ, Uuid):
            return uuid.UUID(str(value))
        if isinstance(typ, Boolean):
            if value not in (True, False, "true", "false", "True", "False", "1", "0"):
                fail(f"Invalid boolean {column.name}.")
            return value in (True, "true", "True", "1")
        if isinstance(typ, Integer):
            if isinstance(value, bool) or str(int(value)) != str(value):
                fail(f"Invalid integer {column.name}.")
            return int(value)
        if isinstance(typ, Float):
            number = float(value)
            if not __import__("math").isfinite(number):
                fail(f"Invalid number {column.name}.")
            return number
        if isinstance(typ, DateTime):
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if utc_workflow_time:
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    fail(f"Field {column.name} requires a timezone.")
                parsed = parsed.astimezone(UTC)
            return parsed
        if isinstance(typ, Date):
            return date.fromisoformat(str(value))
        if isinstance(typ, JSON):
            return value if not isinstance(value, str) else json.loads(value)
        if not isinstance(value, str) or (
            getattr(typ, "length", None) and len(value) > typ.length
        ):
            fail(f"Invalid text {column.name}.")
        return value
    except (ValueError, TypeError, OverflowError):
        fail(f"Invalid field type: {column.name}.")


def primary_key(table, record):
    return encode([json_value(record[c.name]) for c in table.primary_key.columns])


def condition(table, record):
    return and_(*(c == record[c.name] for c in table.primary_key.columns))


LEGACY_KEYS = {
    "userRewards": "user-rewards",
    "user_rewards": "user-rewards",
    "userAchievements": "user-achievements",
    "user_achievements": "user-achievements",
    "kanbanColumns": "kanban-columns",
    "kanban_columns": "kanban-columns",
}


def normalize_legacy(record):
    import re

    return {
        re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): value
        for key, value in record.items()
    }


def stage_dataset(stage, key, rows, legacy=False, warnings=None, archive_fields=None):
    if key not in tables():
        fail(f"Unsupported dataset: {key}.")
    table = tables()[key]
    fields = set(archive_fields or FIELDS[table.name].split())
    stage.execute("INSERT OR IGNORE INTO datasets(name) VALUES(?)", (key,))
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            fail(f"Invalid record in {key}.")
        if legacy:
            row = normalize_legacy(row)
            if "hashed_password" in row:
                warnings.add(
                    "Legacy password hashes were discarded; existing credentials are never changed."
                )
            if key == "tasks":
                for child in row.get("subtasks", []) or []:
                    stage_dataset(
                        stage,
                        "subtasks",
                        [{**normalize_legacy(child), "task_id": row["id"]}],
                        True,
                        warnings,
                    )
                for child in row.get("comments", []) or []:
                    stage_dataset(
                        stage,
                        "comments",
                        [{**normalize_legacy(child), "task_id": row["id"]}],
                        True,
                        warnings,
                    )
                for dependency in row.get("dependencies", []) or []:
                    stage_dataset(
                        stage,
                        "task-dependencies",
                        [{"task_id": row["id"], "depends_on_task_id": dependency}],
                        True,
                        warnings,
                    )
            extra = set(row) - fields
            if extra:
                warnings.add("Legacy fields outside the safe schema were discarded.")
            row = {k: v for k, v in row.items() if k in fields}
        elif set(row) != fields:
            fail(f"Invalid dataset headers: {key}.")
        if not all(
            c.name in row and row[c.name] not in (None, "")
            for c in table.primary_key.columns
        ):
            fail(f"Missing record identifier: {key}.")
        converted = {name: convert(table.c[name], value) for name, value in row.items()}
        try:
            stage.execute(
                "INSERT INTO records(dataset,pk,payload) VALUES(?,?,?)",
                (key, primary_key(table, converted), encode(converted)),
            )
        except sqlite3.IntegrityError:
            fail(f"Duplicate identifier: {key}.")
        count += 1
    return count


def read_upload(job, file_path, filename, dataset=None):
    warnings = set()
    with stage_connection(job.id) as stage:
        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(file_path) as archive:
                    entries = archive.infolist()
                    names = [entry.filename for entry in entries]
                    allowed = {"manifest.json"} | {
                        f"data/{key}.{fmt}"
                        for key in tables()
                        for fmt in ("csv", "json")
                    }
                    if (
                        len(names) != len(set(names))
                        or len(names) > 200
                        or not set(names) <= allowed
                    ):
                        fail("Unsupported archive structure or duplicate ZIP entries.")
                    if any(
                        e.file_size > MAX_UPLOAD
                        or e.flag_bits & 1
                        or (e.external_attr >> 16) & 0o170000 == 0o120000
                        for e in entries
                    ):
                        fail("Unsafe ZIP entry or file size.")
                    if sum(e.file_size for e in entries) > MAX_EXPANDED:
                        fail("ZIP expansion exceeds the safety limit.")
                    if (
                        "manifest.json" not in names
                        or archive.getinfo("manifest.json").file_size > 1024**2
                    ):
                        fail("Missing required manifest or oversized manifest.")
                    manifest = json.loads(archive.read("manifest.json"))
                    if manifest.get("backup_schema_version") != VERSION:
                        fail("Unsupported backup version.")
                    if manifest.get("workspace_id") != job.tenant_id:
                        fail(
                            "Permission denied: backup belongs to another workspace.",
                            403,
                        )
                    if manifest.get("completion_status") != "completed" or manifest.get(
                        "format"
                    ) not in ("csv", "json"):
                        fail("Backup is incomplete or has an unsupported format.")
                    keys = manifest.get("selected_datasets")
                    files = manifest.get("files")
                    if (
                        not isinstance(keys, list)
                        or not keys
                        or len(keys) != len(set(keys))
                        or not set(keys) <= set(tables())
                        or not isinstance(files, dict)
                        or set(files) != set(keys)
                    ):
                        fail("Invalid manifest datasets.")
                    expected = {"manifest.json"} | {
                        f"data/{key}.{manifest['format']}" for key in keys
                    }
                    if set(names) != expected:
                        fail("Missing required dataset or unexpected ZIP file.")
                    for key in keys:
                        name = f"data/{key}.{manifest['format']}"
                        if files[key].get("path") != name:
                            fail("Invalid manifest file path.")
                        # Bounded read; no extraction, code evaluation, or uploaded path use.
                        with archive.open(name) as member:
                            raw = member.read(MAX_UPLOAD + 1)
                        if len(raw) > MAX_UPLOAD:
                            fail("Dataset exceeds import size limit.")
                        if hashlib.sha256(raw).hexdigest() != files[key].get("sha256"):
                            fail(f"Invalid ZIP checksum: {key}.")
                        expected_fields = FIELDS[tables()[key].name].split()
                        archive_fields = files[key].get("fields")
                        old_fields = LEGACY_TASK_AUDIT_FIELDS.get(tables()[key].name)
                        previous_fields = PHASE2_REWARD_FIELDS.get(tables()[key].name)
                        phase1_fields = (archive_fields == PHASE1_SUBTASK_FIELDS and tables()[key].name == "subtasks") or (previous_fields is not None and archive_fields == previous_fields)
                        if not phase1_fields and archive_fields != expected_fields and (
                            old_fields is None or archive_fields != old_fields.split()
                        ):
                            fail(f"Invalid dataset headers: {key}.")
                        if manifest["format"] == "csv":
                            reader = csv.DictReader(
                                io.StringIO(raw.decode("utf-8-sig"), newline=""),
                                strict=True,
                            )
                            if reader.fieldnames != archive_fields:
                                fail(f"Invalid CSV headers: {key}.")
                            rows = (
                                {k: json.loads(v) for k, v in row.items()}
                                for row in reader
                            )
                        else:
                            rows = json.loads(raw)
                        count = stage_dataset(stage, key, rows, archive_fields=archive_fields)
                        if count != files[key].get("record_count"):
                            fail(f"Incorrect record count: {key}.")
            except HTTPException:
                raise
            except (
                zipfile.BadZipFile,
                RuntimeError,
                KeyError,
                ValueError,
                TypeError,
                AttributeError,
                UnicodeError,
                csv.Error,
            ):
                fail("Broken ZIP archive or invalid dataset structure.")
        elif filename.lower().endswith(".csv"):
            if not dataset:
                fail("Choose the dataset for a legacy CSV file.")
            with open(file_path, encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if not reader.fieldnames or len(set(reader.fieldnames)) != len(
                    reader.fieldnames
                ):
                    fail("Invalid CSV headers.")
                normalized = set(normalize_legacy(dict.fromkeys(reader.fieldnames)))
                if (
                    dataset not in tables()
                    or not {c.name for c in tables()[dataset].primary_key.columns}
                    <= normalized
                ):
                    fail("Invalid CSV headers: missing record identifier.")

                def legacy_rows():
                    for row in reader:
                        if None in row or None in row.values():
                            fail("Invalid CSV structure.")
                        result = {}
                        for key, value in row.items():
                            if value == "":
                                value = None
                            elif value[0] in '[{"' or value in (
                                "true",
                                "false",
                                "null",
                            ):
                                try:
                                    value = json.loads(value)
                                except ValueError:
                                    pass
                            result[key] = value
                        yield result

                stage_dataset(stage, dataset, legacy_rows(), True, warnings)
        elif filename.lower().endswith(".json"):
            with open(file_path, encoding="utf-8-sig") as stream:
                bundle = json.load(stream)
            if isinstance(bundle, list) and dataset:
                stage_dataset(stage, dataset, bundle, True, warnings)
            elif isinstance(bundle, dict):
                for key, rows in bundle.items():
                    target = LEGACY_KEYS.get(key, key.replace("_", "-"))
                    if target in tables():
                        stage_dataset(stage, target, rows, True, warnings)
            else:
                fail("Invalid legacy JSON backup.")
        else:
            fail("Unsupported backup format. Select ZIP, CSV or JSON.")
        if stage.execute("SELECT count(*) FROM records").fetchone()[0] > MAX_RECORDS:
            fail("Import exceeds the record limit; select smaller backups.")
        if not stage.execute("SELECT 1 FROM records LIMIT 1").fetchone():
            fail("No supported records detected.")
    return sorted(warnings)


def staged_records(stage, selected):
    for key in selected:
        if key == "xp-ledger":
            stage.execute("CREATE INDEX IF NOT EXISTS ix_staged_ledger_id ON records(dataset,json_extract(payload,'$.id'))")
            stage.execute("CREATE INDEX IF NOT EXISTS ix_staged_ledger_parent ON records(dataset,json_extract(payload,'$.reversal_of_id'))")
            # Reversals are immutable and cannot be inserted with a temporary
            # NULL reference then patched. Restore each original before its
            # reversal, including reversal chains, without loading them in RAM.
            cursor = stage.execute("""
                WITH RECURSIVE ordered(pk,depth) AS (
                  SELECT r.pk,0 FROM records r WHERE r.dataset=? AND
                    (json_extract(r.payload,'$.reversal_of_id') IS NULL OR NOT EXISTS (
                      SELECT 1 FROM records p WHERE p.dataset=r.dataset
                      AND json_extract(p.payload,'$.id')=json_extract(r.payload,'$.reversal_of_id')))
                  UNION ALL
                  SELECT c.pk,o.depth+1 FROM ordered o
                    JOIN records p ON p.dataset=? AND p.pk=o.pk
                    JOIN records c ON c.dataset=p.dataset
                    AND json_extract(c.payload,'$.reversal_of_id')=json_extract(p.payload,'$.id')
                )
                SELECT r.pk,r.payload,r.baseline FROM ordered o
                  JOIN records r ON r.dataset=? AND r.pk=o.pk ORDER BY o.depth,r.pk
                """, (key,key,key))
        else:
            cursor = stage.execute(
                "SELECT pk,payload,baseline FROM records WHERE dataset=? ORDER BY pk", (key,))
        seen = 0
        for pk, payload, baseline in cursor:
            seen += 1
            table = tables()[key]
            record = {
                name: convert(table.c[name], value)
                for name, value in json.loads(payload).items()
            }
            yield key, table, pk, record, baseline
        if key == "xp-ledger" and seen != stage.execute("SELECT COUNT(*) FROM records WHERE dataset=?", (key,)).fetchone()[0]:
            fail("Cyclic point reversal references cannot be restored.")


def current_record(db, table, record, tenant_id=None, check_scope=True):
    row = (
        db.execute(
            select(
                *record_columns(db, table, tenant_id or record.get("tenant_id"))
            ).where(condition(table, record))
        )
        .mappings()
        .first()
    )
    if (
        row
        and tenant_id is not None
        and check_scope
        and not db.execute(
            select(*table.primary_key.columns)
            .where(condition(table, record), record_scope(db, table, tenant_id))
            .limit(1)
        ).first()
    ):
        fail(
            f"Permission denied: record outside this workspace in {dataset_id(table.name)}.",
            403,
        )
    return {k: json_value(v) for k, v in row.items()} if row else None


def preview(db, job, selected, mode, save_baselines=True, provision_users=False):
    started = time.monotonic()
    errors, counts, impact = (
        [],
        {},
        {"insert": 0, "update": 0, "skip": 0, "provision": 0},
    )
    with stage_connection(job.id) as stage:
        stage.execute(
            "CREATE TEMP TABLE unique_values (dataset TEXT, constraint_key TEXT, value TEXT, pk TEXT, PRIMARY KEY(dataset,constraint_key,value))"
        )
        available = dict(
            stage.execute(
                "SELECT name,(SELECT count(*) FROM records WHERE dataset=name) FROM datasets"
            )
        )
        if not selected:
            selected = sorted(available)
        if not set(selected) <= set(available):
            fail("Unsupported restore scope.")
        counts = {key: 0 for key in selected}
        for key, table, pk, record, _ in staged_records(stage, selected):
            if time.monotonic() - started > TIMEOUT:
                fail("Validation timed out; select a smaller restore scope.", 408)
            counts[key] = counts.get(key, 0) + 1
            existing = current_record(
                db, table, record, job.tenant_id, check_scope=False
            )
            if (
                existing
                and not db.execute(
                    select(*table.primary_key.columns)
                    .where(
                        condition(table, record),
                        record_scope(db, table, job.tenant_id),
                    )
                    .limit(1)
                ).first()
            ):
                errors.append(
                    f"Permission denied: record outside this workspace in {key}."
                )
                continue
            if save_baselines:
                stage.execute(
                    "UPDATE records SET baseline=? WHERE dataset=? AND pk=?",
                    (fingerprint(existing), key, pk),
                )
            if "tenant_id" in record and str(record["tenant_id"]) != job.tenant_id:
                errors.append(f"Permission denied: foreign tenant in {key}.")
            if table.name in ACTOR_OWNED and record.get("actor_id") is None:
                errors.append(f"Missing workspace ownership: {key}.actor_id.")
            if table.name == "users" and not existing:
                if not provision_users:
                    errors.append(
                        "Missing users must be provisioned through authorized account management; enable inactive-account provisioning and preview again."
                    )
                else:
                    impact["provision"] += 1
                    try:
                        TypeAdapter(EmailStr).validate_python(record.get("email"))
                    except ValidationError:
                        errors.append("Invalid account email in users dataset.")
            if existing and mode == "insert":
                impact["skip"] += 1
                continue
            if not existing:
                for column in table.columns:
                    if column.name == "tenant_id" or (
                        table.name == "users"
                        and provision_users
                        and column.name == "hashed_password"
                    ):
                        continue
                    if (
                        column.name not in record
                        and not column.nullable
                        and column.default is None
                        and column.server_default is None
                        and not column.computed
                    ):
                        errors.append(f"Missing required field {key}.{column.name}.")
            for field, target, target_field in references(table):
                value = record.get(field)
                if value is None:
                    continue
                value = convert(target.c[target_field], json_value(value))
                found = db.execute(
                    select(target.c[target_field])
                    .where(
                        target.c[target_field] == value,
                        workspace_scope(target.name, job.tenant_id),
                    )
                    .limit(1)
                ).first()
                if (
                    not found
                    and target.name in FIELDS
                    and dataset_id(target.name) in selected
                ):
                    # FK targets in this schema reference a single primary-key column.
                    found = stage.execute(
                        "SELECT 1 FROM records WHERE dataset=? AND pk=?",
                        (dataset_id(target.name), encode([json_value(value)])),
                    ).fetchone()
                if not found:
                    errors.append(f"Broken relationship reference: {key}.{field}.")
            # Unique constraints are checked before execution as well as by the DB transaction.
            unique_columns = [
                tuple(c.name for c in constraint.columns)
                for constraint in table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            ]
            unique_columns += [
                (column.name,) for column in table.columns if column.unique
            ]
            if legacy_templates(db, table):
                unique_columns = [
                    tuple(name for name in names if name != "tenant_id")
                    for names in unique_columns
                ]
            for names in set(unique_columns):
                if not all(record.get(name) is not None for name in names):
                    continue
                conflict = (
                    db.execute(
                        select(*table.primary_key.columns).where(
                            *(table.c[name] == record[name] for name in names)
                        )
                    )
                    .mappings()
                    .first()
                )
                if conflict and any(
                    conflict[c.name] != record[c.name]
                    for c in table.primary_key.columns
                ):
                    errors.append(f"Restore conflict: duplicate unique value in {key}.")
                try:
                    stage.execute(
                        "INSERT INTO unique_values VALUES(?,?,?,?)",
                        (
                            key,
                            encode(names),
                            encode([record[name] for name in names]),
                            pk,
                        ),
                    )
                except sqlite3.IntegrityError:
                    errors.append(
                        f"Restore conflict: duplicate unique value in uploaded {key}."
                    )
            impact["update" if existing else "insert"] += 1
            if len(errors) > 100:
                break
        stage.commit()
    errors = sorted(set(errors))[:100]
    upload_warnings = list(
        job.report.get("upload_warnings", job.report.get("warnings", []))
    )
    warnings = list(upload_warnings)
    if provision_users:
        warnings.append(
            "Owner-approved provisioning creates inactive ordinary-user accounts with fresh random credentials. Use Users to reset their passwords, review roles and activate them. Imported credentials, roles and active status are never applied."
        )
    return {
        "datasets": counts,
        "impact": impact,
        "errors": errors,
        "valid": not errors,
        "selected": selected,
        "mode": mode,
        "provision_users": provision_users,
        "warnings": sorted(set(warnings)),
        "upload_warnings": upload_warnings,
    }


def restore(db, job):
    """Called in a SERIALIZABLE transaction after explicit confirmation; never delete."""
    started = time.monotonic()

    def check_deadline():
        if time.monotonic() - started > TIMEOUT:
            fail(
                "Restore timed out; the transaction was rolled back. Select a smaller scope.",
                408,
            )

    report = job.report
    selected, mode = report["selected"], report["mode"]
    with stage_connection(job.id) as stage:
        records = lambda: staged_records(stage, selected)
        for key, table, pk, record, baseline in records():
            check_deadline()
            if (
                fingerprint(current_record(db, table, record, job.tenant_id))
                != baseline
            ):
                fail(
                    "Restore conflict: data changed since preview. Validate again.", 409
                )
        # Dependency order is resolved by successful inserts. Cycles use a second pass
        # for nullable references; existing rows are updated after all inserts.
        pending = []
        for key in selected:
            table = tables()[key]
            for other in dependencies(table):
                if other in selected:
                    if table.name == "users" and other == "avatar-assets":
                        # The known nullable users/avatar_assets cycle is
                        # repaired by nullable_refs after all inserts. Keep
                        # immutable task history behind its actual parents.
                        continue
                    pending.append((key, other))
        ordered, remaining = [], set(selected)
        while remaining:
            ready = sorted(
                k
                for k in remaining
                if not any(a == k and b in remaining for a, b in pending)
            )
            if not ready:
                ready = [min(remaining)]
            ordered.extend(ready)
            remaining.difference_update(ready)
        nullable_refs = []
        count = 0
        for key, table, pk, record, _ in staged_records(stage, ordered):
            check_deadline()
            exists = current_record(db, table, record, job.tenant_id)
            if exists:
                continue
            if table.name == "users" and not report.get("provision_users"):
                fail("Provision missing users before restore.")
            values = dict(record)
            if table.name == "subtasks" and "created_at" not in values:
                # Older archives did not know creation time. Do not invoke the
                # new writer default and invent a historical timestamp.
                values["created_at"] = None
            if "tenant_id" in table.c:
                values["tenant_id"] = convert(table.c.tenant_id, job.tenant_id)
            if legacy_templates(db, table):
                values.pop("tenant_id", None)
            if table.name == "users":
                # Explicit Owner-approved recovery step. No imported credential or
                # authorization state is accepted, and the account cannot log in.
                values.update(
                    tenant_id=uuid.UUID(job.tenant_id),
                    role=models.RoleEnum.USER,
                    status=models.UserStatusEnum.DEACTIVATED,
                    hashed_password=hash_password(secrets.token_urlsafe(48)),
                    email=str(TypeAdapter(EmailStr).validate_python(record["email"])),
                    employer_id=db.scalar(
                        select(table.c.employer_id).where(
                            table.c.id == job.requested_by
                        )
                    ),
                )
            for fk in table.foreign_keys:
                value = values.get(fk.parent.name)
                if (
                    value is not None
                    and not db.execute(
                        select(fk.column).where(fk.column == value).limit(1)
                    ).first()
                    and fk.parent.nullable
                ):
                    if table.name in {"task_work_intervals", "task_work_corrections", "task_activity_contexts"} or table.name == "audit_events" and values.get("audit_schema_version") == 2 or table.name == "xp_ledger" and values.get("record_version") == 2:
                        fail(f"Cannot clear immutable relationship: {table.name}.{fk.parent.name}.", 409)
                    nullable_refs.append((key, pk, fk.parent.name, json_value(value)))
                    values[fk.parent.name] = None
            db.execute(table.insert().values(**values))
            count += 1
        for key, table, pk, record, baseline in staged_records(stage, ordered):
            check_deadline()
            # Do not touch existing user authentication/authorization fields.
            if mode == "update" and baseline != fingerprint(None):
                protected = {c.name for c in table.primary_key.columns} | {"tenant_id"}
                if table.name == "users":
                    protected |= {"role", "status", "email", "employer_id"}
                values = {k: v for k, v in record.items() if k not in protected}
                # Immutable history may be replayed unchanged, never rewritten.
                immutable = (
                    table.name in {"task_work_intervals", "task_work_corrections", "task_activity_contexts"}
                    or table.name == "audit_events" and record.get("audit_schema_version") == 2
                    or table.name == "xp_ledger" and record.get("record_version") == 2
                )
                if immutable:
                    existing = current_record(db, table, record, job.tenant_id)
                    if any(existing.get(k) != json_value(v) for k, v in values.items()):
                        fail("Immutable task history cannot be updated during restore.", 409)
                    continue
                if values:
                    db.execute(
                        table.update()
                        .where(
                            condition(table, record),
                            record_scope(db, table, job.tenant_id),
                        )
                        .values(**values)
                    )
                    count += 1
        for key, pk, name, value in nullable_refs:
            table = tables()[key]
            payload = stage.execute(
                "SELECT payload FROM records WHERE dataset=? AND pk=?", (key, pk)
            ).fetchone()[0]
            record = {k: convert(table.c[k], v) for k, v in json.loads(payload).items()}
            db.execute(
                table.update()
                .where(condition(table, record))
                .values(**{name: convert(table.c[name], value)})
            )
    return count
