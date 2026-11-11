from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Column, DateTime, Integer, String

from ..database import Base


class BackupJob(Base):
    __tablename__ = "backup_jobs"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    requested_by = Column(String(36), nullable=False)
    operation = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="Queued")
    settings = Column(JSON, nullable=False, default=dict)
    report = Column(JSON, nullable=False, default=dict)
    started_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    record_count = Column(Integer, nullable=False, default=0)
    file_size = Column(BigInteger, nullable=False, default=0)
    error = Column(String(500), nullable=True)


class ExportPreset(Base):
    __tablename__ = "export_presets"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    creator_id = Column(String(36), nullable=False)
    name = Column(String(120), nullable=False)
    settings = Column(JSON, nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
