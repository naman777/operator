import json
import logging
from datetime import datetime, timezone


class RequestFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                **{
                    name: getattr(record, name)
                    for name in ("request_id", "method", "status", "latency_ms")
                    if hasattr(record, name)
                },
            }
        )


def configure_logging():
    logger = logging.getLogger("operator.api")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(RequestFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
