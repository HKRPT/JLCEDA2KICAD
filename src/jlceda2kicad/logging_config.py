"""Logging setup and credential redaction."""

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PROXY_CREDENTIALS = re.compile(r"(?i)(https?_proxy\s*=\s*)(https?://)([^/@\s:]+)(?::[^@\s]*)?@")
_API_TOKEN = re.compile(r"(?i)(KICAD_API_TOKEN\s*=\s*)[^\s]+")
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)([^/@\s:]+)(?::[^@\s]*)?@")


def redact_text(text: str) -> str:
    redacted = _PROXY_CREDENTIALS.sub(r"\1\2***:***@", text)
    redacted = _URL_CREDENTIALS.sub(r"\1***:***@", redacted)
    return _API_TOKEN.sub(r"\1***", redacted)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def configure_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "jlceda2kicad.log"
    handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("jlceda2kicad")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return path
