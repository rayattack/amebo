"""Per-request observability: request-id assignment and access logging.

Registered as `/*` BEFORE and AFTER hooks, so they wrap every matched request and
share its Context. The BEFORE hook assigns a request id (honouring an inbound
`X-Request-ID` so it can be correlated across services), echoes it on the response,
and starts a timer; the AFTER hook emits one access-log line with method, path,
status and duration.
"""
import logging
from time import monotonic
from uuid import uuid4

from amebo.utils.logs import set_request_id

logger = logging.getLogger('amebo.access')

REQUEST_ID_HEADER = 'x-request-id'

# Health/scrape probes are high-frequency and low-signal — log them at DEBUG so the
# access log stays readable in production.
_QUIET_PATHS = {'/health', '/healthz', '/readyz', '/metrics'}


async def request_context(req, res, ctx):
    """BEFORE hook: assign/propagate the request id and start the timer."""
    rid = req.headers.get(REQUEST_ID_HEADER) or uuid4().hex
    set_request_id(rid)
    ctx.keep('request_id', rid)
    ctx.keep('request_start', monotonic())
    res.headers = 'X-Request-ID', rid


async def access_log(req, res, ctx):
    """AFTER hook: emit one structured access line per request."""
    start = ctx.request_start
    duration_ms = round((monotonic() - start) * 1000, 2) if start else None
    status = getattr(res, 'status', None)
    path = getattr(req, 'url', '-')
    method = getattr(req, 'method', '-')
    log = logger.debug if path in _QUIET_PATHS else logger.info
    log(
        '%s %s -> %s %sms', method, path, status, duration_ms,
        extra={'method': method, 'path': path, 'status': status,
               'duration_ms': duration_ms, 'client_ip': getattr(req, 'ip', None)},
    )
