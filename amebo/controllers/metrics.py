import logging
from http import HTTPStatus

from heaven import Context, Request, Response

from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize
from amebo.controllers.gists import _timeline_cutoff, GISTS_FROM


logger = logging.getLogger('amebo.metrics')


# SUM(CASE ...) fragments that mirror helpers.status_expr / STATUS_PREDICATES exactly.
_COUNTS = '''
    SUM(CASE WHEN g.completed <> 0 THEN 1 ELSE 0 END) AS delivered,
    SUM(CASE WHEN g.completed = 0 AND (g.dead_at IS NOT NULL OR g.retries >= s.max_retries) THEN 1 ELSE 0 END) AS failed,
    SUM(CASE WHEN g.completed = 0 AND g.dead_at IS NULL AND g.retries > 0 AND g.retries < s.max_retries THEN 1 ELSE 0 END) AS retrying,
    SUM(CASE WHEN g.completed = 0 AND g.dead_at IS NULL AND g.retries = 0 THEN 1 ELSE 0 END) AS pending,
    COUNT(*) AS total
'''


@jsonify
@contextualize
async def deliveries(req: Request, res: Response, ctx: Context):
    """Top-card aggregates for the dashboard over a selectable window."""
    executor = ctx.executor
    x = executor.schema
    window = (req.queries.get('window') or 'all').lower()
    cutoff = _timeline_cutoff(window)

    gist_filter = ''
    event_filter = ''
    gist_args, event_args = [], []
    if cutoff:
        gp = '?' if executor.engine == 'sqlite' else '$1'
        gist_filter = f'WHERE g.timestamped > {gp}'
        event_filter = f'WHERE e.timestamped > {gp}'
        gist_args = [cutoff]
        event_args = [cutoff]

    counts_sql = f'SELECT {_COUNTS} FROM {x}gists g JOIN {x}subscriptions s ON g.subscription = s.subscription {gist_filter};'
    published_sql = f'SELECT COUNT(*) FROM {x}events e {event_filter};'
    try:
        row = await executor.fetch(1).execute(counts_sql, *gist_args)
        prow = await executor.fetch(1).execute(published_sql, *event_args)
    except Exception as exc:
        logger.error('Could not compute deliveries metrics: %s', exc)
        return res.out(HTTPStatus.BAD_REQUEST, {'error': 'Could not compute metrics'})

    delivered, failed, retrying, pending, total = (row or (0, 0, 0, 0, 0))
    delivered, failed, retrying, pending, total = (
        int(delivered or 0), int(failed or 0), int(retrying or 0), int(pending or 0), int(total or 0))
    finalized = delivered + failed
    success_rate = round((delivered / finalized) * 100, 1) if finalized else None

    return res.out(HTTPStatus.OK, {
        'window': window,
        'published': prow[0] if prow else 0,
        'delivered': delivered,
        'retrying': retrying,
        'pending': pending,
        'failed': failed,
        'total': total,
        'success_rate': success_rate,
    })


@jsonify
@contextualize
async def subscriptions(req: Request, res: Response, ctx: Context):
    """Per-subscription health: success vs failed counts and most recent error."""
    executor = ctx.executor
    x = executor.schema

    counts_sql = f'''
        SELECT s.subscription, s.application, s.action, s.handler, s.max_retries,
            {_COUNTS}
        FROM {x}subscriptions s
        LEFT JOIN {x}gists g ON g.subscription = s.subscription
        GROUP BY s.subscription, s.application, s.action, s.handler, s.max_retries
        ORDER BY failed DESC, s.action ASC;
    '''
    # most recent error per subscription (portable: order desc, keep first seen)
    errors_sql = f'''
        SELECT g.subscription, g.last_error, g.last_attempted_at, g.last_status_code
        FROM {x}gists g
        WHERE g.last_error IS NOT NULL
        ORDER BY g.last_attempted_at DESC
        LIMIT 1000;
    '''
    try:
        rows = await executor.fetch(2).execute(counts_sql)
        erows = await executor.fetch(2).execute(errors_sql)
    except Exception as exc:
        logger.error('Could not compute subscriptions metrics: %s', exc)
        return res.out(HTTPStatus.BAD_REQUEST, {'error': 'Could not compute metrics'})

    latest_error = {}
    for sub, err, at, code in (erows or []):
        key = str(sub)
        if key not in latest_error:
            latest_error[key] = {'error': err, 'at': at, 'status_code': code}

    data = []
    for (sub, app, action, handler, max_retries, delivered, failed, retrying, pending, total) in (rows or []):
        info = latest_error.get(str(sub), {})
        data.append({
            'subscription': str(sub),
            'subscriber': app,
            'action': action,
            'handler': handler,
            'max_retries': max_retries,
            'delivered': int(delivered or 0),
            'failed': int(failed or 0),
            'retrying': int(retrying or 0),
            'pending': int(pending or 0),
            'total': int(total or 0),
            'last_error': info.get('error'),
            'last_error_at': info.get('at'),
            'last_status_code': info.get('status_code'),
        })

    return res.out(HTTPStatus.OK, {'data': data})


@jsonify
@contextualize
async def versions(req: Request, res: Response, ctx: Context):
    """Versioning / migration-debt analytics: action-family count, lifecycle
    status breakdown, and the active subscriptions still pinned to deprecated
    or retired actions (the work left to migrate consumers off old versions)."""
    executor = ctx.executor
    x = executor.schema

    status_sql = f'SELECT status, COUNT(*) FROM {x}actions GROUP BY status;'
    families_sql = f'SELECT COUNT(DISTINCT family) FROM {x}actions;'
    dep_subs_sql = (
        f'SELECT COUNT(*) FROM {x}subscriptions s '
        f'JOIN {x}actions a ON s.action = a.action '
        f"WHERE a.status IN ('deprecated', 'retired') AND s.active <> 0;"
    )
    # deprecated/retired actions that still have active subscribers -> migration debt
    at_risk_sql = f'''
        SELECT a.action, a.family, a.status, a.successor,
            (SELECT COUNT(*) FROM {x}subscriptions s WHERE s.action = a.action AND s.active <> 0) AS subscribers
        FROM {x}actions a
        WHERE a.status IN ('deprecated', 'retired')
        ORDER BY subscribers DESC, a.action ASC;
    '''
    try:
        srows = await executor.fetch(2).execute(status_sql)
        frow = await executor.fetch(1).execute(families_sql)
        drow = await executor.fetch(1).execute(dep_subs_sql)
        arows = await executor.fetch(2).execute(at_risk_sql)
    except Exception as exc:
        logger.error('Could not compute versions metrics: %s', exc)
        return res.out(HTTPStatus.BAD_REQUEST, {'error': 'Could not compute metrics'})

    by_status = {'active': 0, 'deprecated': 0, 'retired': 0}
    for status, count in (srows or []):
        by_status[status or 'active'] = int(count or 0)

    at_risk = [{
        'action': action,
        'family': family,
        'status': status,
        'successor': successor,
        'subscribers': int(subscribers or 0),
    } for action, family, status, successor, subscribers in (arows or [])]

    return res.out(HTTPStatus.OK, {
        'total_families': int(frow[0]) if frow and frow[0] is not None else 0,
        'total_actions': sum(by_status.values()),
        'by_status': by_status,
        'subscriptions_on_deprecated': int(drow[0]) if drow and drow[0] is not None else 0,
        'at_risk': at_risk,
    })
