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
def tabulate(req, res, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['id', 'action', 'microservice', 'schemata', 'timeline']
    _id, _action, _microservice, _schemata, _timeline = [req.params.get(p) for p in params]

    steps = Steps()
    sqls = f'''
        SELECT
            rowid, action, microservice, schemata, timestamped
        FROM
            actions
            {steps.EQUALS(_id, 'rowid')}
            {steps.LIKE(_action, 'action')}
            {steps.LIKE(_microservice, 'microservice')}
            {steps.LIKE(_schemata, 'schemata')}
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
        'microservice': microservice,
        'schemata': loads(schemata),
        'timestamped': timestamped
    } for id, action, microservice, schemata, timestamped in rows]


@jsonify
@expects(Action)
def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    action: Action = ctx.action

    table = 'actions'
    fields = ('action', 'microservice', 'schemata', 'timestamped',)
    values = (action.action, action.microservice, dumps(action.schemata), action.timestamped)

    try:
        cursor: Cursor = db.cursor()
        microservice = cursor.execute(f'''
            select * from microservices where rowid = ?
        ''', (action.microservice,)).fetchone()
        if not microservice:
            raise ValueError(f'microservice with id {action.microservice} not found')

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
    res.body = action.dict()
