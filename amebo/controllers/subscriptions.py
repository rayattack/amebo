from http import HTTPStatus
from sqlite3 import Connection, Cursor

from heaven import Context, Request, Response

from amebo.constants.literals import DB, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import expects
from amebo.models.subscriptions import Subscriptions
from amebo.utils.helpers import get_pagination, get_timeline
from amebo.utils.structs import Steps


@jsonify
def tabulate(req: Request, res, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    qstrings = ['id', 'application', 'matchrule', 'action', 'endpoint', 'description', 'timeline']
    [
        _id, _application, _matchrule,
        _action, _handler, _description, _timeline] = [req.queries.get(q) for q in qstrings]

    steps = Steps()
    sqls = f'''
        SELECT
            subscription, action, application, handler, description, timestamped
        FROM subscriptions
            {steps.EQUALS('subscription', _id)}
            {steps.LIKE('application', _application)}
            {steps.LIKE('action', _action)}
            {steps.LIKE('handler', _handler)}
            {steps.LIKE('description', _description)}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try:
        cursor = db.cursor()
        rows = cursor.execute(sqls, steps.values).fetchall()
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = None
        return
    finally:
        cursor.close()

    res.status = HTTPStatus.OK
    res.body = [{
        'subscription': subscription,
        'action': action,
        'application': application,
        'handler': handler,
        'description': description,
        'timestamped': timestamped
    } for subscription, action, application, handler, description, timestamped in rows]


@jsonify
@expects(Subscriptions)
def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    subscriptions: Actions = ctx.subscriptions

    table = 'subscriptions'
    fields = ('action', 'application', 'handler', 'description', 'timestamped',)
    values = (
        subscriptions.action,
        subscriptions.application,
        subscriptions.handler,
        subscriptions.description,
        subscriptions.timestamped
    )

    try:
        cursor: Cursor = db.cursor()
        subscriptionid = cursor.execute(f'''
            INSERT INTO {table}({', '.join(fields)}) VALUES(?, ?, ?, ?, ?) RETURNING rowid;
        ''', values).fetchone()
        db.commit()
    except Exception as exc:
        res.status = HTTPStatus.UPGRADE_REQUIRED
        res.body = {'error': f'{exc}'}
        return
    finally:
        cursor.close()

    res.status = HTTPStatus.CREATED
    subscriptions.subscription = subscriptionid[0]
    res.body = subscriptions.dict()
