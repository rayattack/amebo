"""Structured logging with request-id propagation.

`configure_logging()` installs a single root handler that stamps every record with
the current request id. Output is human-readable text by default, or JSON when
`AMEBO_LOG_FORMAT=json` (for log aggregators). Level comes from `AMEBO_LOG_LEVEL`.

The request id flows through the async call chain via a `ContextVar`, set by the
observability middleware at the start of each request, so any log line emitted while
handling that request — including the `logger.error(...)` calls in controllers —
carries it without threading the id through every call.
"""
import logging
from contextvars import ContextVar
from os import environ

from orjson import dumps


# '-' when no request is in flight (startup, daemon, CLI).
request_id_var: ContextVar = ContextVar('amebo_request_id', default='-')


def set_request_id(value):
    request_id_var.set(value or '-')


def get_request_id():
    try:
        return request_id_var.get()
    except LookupError:
        return '-'


class RequestIdFilter(logging.Filter):
    """Stamp every record with the current request id."""

    def filter(self, record):
        record.request_id = get_request_id()
        return True


# Access-log records carry these extras; surface them in JSON output.
_EXTRA_KEYS = ('method', 'path', 'status', 'duration_ms', 'client_ip')


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'ts': self.formatTime(record),
            'level': record.levelname,
            'logger': record.name,
            'request_id': getattr(record, 'request_id', '-'),
            'message': record.getMessage(),
        }
        for key in _EXTRA_KEYS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return dumps(payload).decode()


_TEXT_FORMAT = '%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s'
_HANDLER_TAG = '_amebo_log_handler'


def configure_logging():
    """Install (or re-install) Amebo's root log handler. Idempotent: replaces a prior
    Amebo handler without disturbing handlers owned by other code (e.g. pytest)."""
    level = getattr(logging, environ.get('AMEBO_LOG_LEVEL', 'INFO').upper(), logging.INFO)

    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, _HANDLER_TAG, False):
            root.removeHandler(h)

    handler = logging.StreamHandler()
    setattr(handler, _HANDLER_TAG, True)
    handler.addFilter(RequestIdFilter())
    if environ.get('AMEBO_LOG_FORMAT', '').strip().lower() == 'json':
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    root.addHandler(handler)
    root.setLevel(level)
    return handler
