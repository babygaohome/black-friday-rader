"""Structured JSON logs (design doc section 43): one object per line with service, event and context fields."""
import json
import logging
import sys
from datetime import datetime, timezone

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "fields"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "service": self._service,
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        out.update(getattr(record, "fields", {}))
        if record.exc_info and "error" not in out:
            out["error"] = repr(record.exc_info[1])
        return json.dumps(out, default=str)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """Fields with a None value are left out so lines stay compact."""
    logger.log(level, event, extra={"fields": {k: v for k, v in fields.items() if v is not None}})


def configure_logging(service: str, level: str = "INFO", stream=None) -> None:
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
