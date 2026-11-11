"""Small application lifecycle task; no broker or new queue service required."""

import logging
import threading

from sqlalchemy import inspect

from ..database import SessionLocal
from .service import cleanup

log = logging.getLogger(__name__)
_stop = threading.Event()
_thread = None


def _maintain():
    while not _stop.is_set():
        try:
            with SessionLocal() as db:
                if "backup_jobs" in inspect(db.get_bind()).get_table_names():
                    cleanup(db)
        except Exception as exc:  # noqa: BLE001 - maintenance must not stop application startup
            log.warning(
                "backup_cleanup_deferred", extra={"error_type": type(exc).__name__}
            )
        _stop.wait(300)


def start_backup_maintenance():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_maintain, name="backup-cleanup", daemon=True)
    _thread.start()


def stop_backup_maintenance():
    _stop.set()
    if _thread:
        _thread.join(timeout=1)
