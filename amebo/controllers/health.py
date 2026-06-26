"""Liveness and readiness probes for load balancers / orchestrators.

- GET /health  (alias /healthz): liveness — the process is up; touches no dependencies.
- GET /readyz: readiness — the database is reachable; returns 503 when it is not, so a
  load balancer stops routing traffic to an instance that can't serve it.

Both are unauthenticated by design (probes don't carry credentials).
"""
import logging
from http import HTTPStatus

from heaven import Context, Request, Response

from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import Executor

logger = logging.getLogger('amebo.health')


@jsonify
async def health(req: Request, res: Response, ctx: Context):
    """Liveness: always 200 while the process can serve requests."""
    res.status = HTTPStatus.OK
    res.body = {'status': 'ok', 'version': req.app.peek('version')}


@jsonify
async def readyz(req: Request, res: Response, ctx: Context):
    """Readiness: 200 only when the database answers a trivial query, else 503."""
    try:
        executor = Executor(req.app)
        if executor.db is None:
            raise RuntimeError('database connection not established')
        row = await executor.fetch(1).execute('SELECT 1')
        if not row:
            raise RuntimeError('database did not respond')
    except Exception as exc:
        logger.warning('Readiness check failed: %s', exc)
        return res.out(HTTPStatus.SERVICE_UNAVAILABLE, {'status': 'unavailable', 'database': 'down'})

    res.status = HTTPStatus.OK
    res.body = {'status': 'ready', 'version': req.app.peek('version')}
