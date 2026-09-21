"""Logging setup shared by the API and the ingestion CLI."""
import logging
import sys

from app.config import LOG_LEVEL

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
_configured = False


def setup_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(level or LOG_LEVEL)
    root.handlers = [handler]

    # sentence-transformers and httpx are noisy at INFO.
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _configured = True
