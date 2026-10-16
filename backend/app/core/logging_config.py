"""Structured logging with secret redaction. Never log passwords, tokens, or PII bodies."""
import logging
import re

_REDACT_PATTERNS = (
    re.compile(r"(?i)(password['\"]?\s*[:=]\s*['\"]?)([^'\",\s}]+)"),
    re.compile(r"(?i)(token['\"]?\s*[:=]\s*['\"]?)([^'\",\s}]+)"),
    re.compile(r"(?i)(secret['\"]?\s*[:=]\s*['\"]?)([^'\",\s}]+)"),
)

REDACTED = "***REDACTED***"


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pat in _REDACT_PATTERNS:
            msg = pat.sub(r"\1" + REDACTED, msg)
        record.msg = msg
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


logger = logging.getLogger("scnc")
