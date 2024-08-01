from http import HTTPStatus
from sqlite3 import Connection, Cursor

from heaven import Context, Request, Response

from amebo.constants.literals import DB, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import expects
from amebo.models.subscribers import Subscriber
from amebo.utils.helpers import get_pagination, get_timeline
from amebo.utils.structs import Steps


@jsonify
def tabulate(req: Request, res, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['id', 'producer', 'matchrule', 'event', 'endpoint', 'description', 'timeline']
    [
        _id, _producer, _matchrule,
        _event, _endpoint, _description, _timeline] = [req.params.get(p) for p in params]
    
    m = 'producer'
    steps = Steps()
    sqls = f'''
        SELECT
            subscriber, event, producer, endpoint, description, timestamped
        FROM subscribers
            {steps.EQUALS(_id, 'subscriber')}
            {steps.LIKE(_producer, m)}
            {steps.LIKE(_event, 'event')}
            {steps.LIKE(_endpoint, 'endpoint')}
            {steps.LIKE(_description, 'description')}
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
        'subscriber': subscriber,
        'event': event,
        'producer': producer,
        'endpoint': endpoint,
        'description': description,
        'timestamped': timestamped
    } for subscriber, event, producer, endpoint, description, timestamped in rows]


@jsonify
@expects(Subscriber)
def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    subscriber: Actions = ctx.subscriber

    table = 'subscribers'
    fields = ('event', 'producer', 'endpoint', 'description', 'timestamped',)
    values = (subscriber.action, subscriber.producer, subscriber.endpoint, subscriber.description, subscriber.timestamped)

    try:
        cursor: Cursor = db.cursor()
        subscriberid = cursor.execute(f'''
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
    subscriber.subscriber = subscriberid[0]
    res.body = subscriber.dict()
