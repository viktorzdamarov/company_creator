"""Operation log: every change sent to Keitaro is recorded in operation_logs."""
import logging

from sqlalchemy.orm import Session

from app.db.models import OperationLog

log = logging.getLogger(__name__)


def log_operation(
    db: Session,
    action: str,
    *,
    status: str = "ok",
    campaign_id: int | None = None,
    details: dict | None = None,
    error: str | None = None,
) -> None:
    db.add(OperationLog(action=action, status=status, campaign_keitaro_id=campaign_id, details=details, error=error))
    db.commit()
    log.info("operation %s status=%s campaign=%s %s", action, status, campaign_id, error or "")
