from http import HTTPStatus
from sqlite3 import Connection, Cursor

# installed libs
from heaven import Context, Request, Response
from orjson import dumps, loads

from amebo.constants.literals import DB, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import expects
from amebo.models.actions import Action
from amebo.utils.helpers import get_pagination, get_timeline
from amebo.utils.structs import Steps


@jsonify
def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['id', 'action', 'producer', 'schemata', 'timeline']
    _id, _action, _producer, _schemata, _timeline = [req.queries.get(p) for p in params]

    steps = Steps()
    sqls = f'''
        SELECT
            rowid, action, producer, schemata, timestamped
        FROM
            actions
            {steps.EQUALS('rowid', _id)}
            {steps.LIKE('action', _action)}
            {steps.LIKE('producer', _producer)}
            {steps.LIKE('schemata', _schemata)}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try:
        cursor = db.cursor()
        rows = cursor.execute(sqls, steps.values).fetchall()
    except Exception as exc:
        res.status = HTTPStatus.NO_CONTENT
        res.body = None
        return
    finally:
        cursor.close()

    res.status = HTTPStatus.OK
    res.body = [{
        'id': id,
        'action': action,
        'producer': producer,
        'schemata': loads(schemata),
        'timestamped': timestamped
    } for id, action, producer, schemata, timestamped in rows]


@jsonify
@expects(Action)
def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    action: Action = ctx.action

    table = 'actions'
    fields = ('action', 'producer', 'schemata', 'timestamped',)
    values = (action.action, action.producer, dumps(action.schemata), action.timestamped)

    try:
        cursor: Cursor = db.cursor()
        producer = cursor.execute(f'''
            select name, passphrase from producers where name = ?
        ''', (action.producer,)).fetchone()
        if not producer:
            raise ValueError(f'producer {action.producer} not found')
        name, passphrase = producer
        if(passphrase != action.passphrase):
            return res.out(HTTPStatus.UNAUTHORIZED, {'error': f'Incorrect {name} passphrase detected'})

        cursor.execute(f'''
            INSERT INTO {table}({', '.join(fields)}) VALUES(?, ?, ?, ?)
        ''', values)
        db.commit()
    except Exception as exc:
        res.status = HTTPStatus.UPGRADE_REQUIRED
        res.body = {'error': f'{exc}'}
        return
    finally:
        cursor.close()

    res.status = HTTPStatus.CREATED
    res.body = action.model_dump()
