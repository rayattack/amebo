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
    params = ['id', 'action', 'application', 'schemata', 'timeline']
    _id, _action, _application, _schemata, _timeline = [req.queries.get(p) for p in params]

    steps = Steps()
    sqls = f'''
        SELECT
            rowid, action, application, schemata, timestamped
        FROM
            actions
            {steps.EQUALS('rowid', _id)}
            {steps.LIKE('action', _action)}
            {steps.LIKE('application', _application)}
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
        'application': application,
        'schemata': loads(schemata),
        'timestamped': timestamped
    } for id, action, application, schemata, timestamped in rows]


@jsonify
@expects(Action)
def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    action: Action = ctx.action

    table = 'actions'
    fields = ('action', 'application', 'schemata', 'timestamped',)
    values = (action.action, action.application, dumps(action.schemata), action.timestamped)

    try:
        cursor: Cursor = db.cursor()
        _application = cursor.execute(f'''
            select application, passphrase from applications where application = ?
        ''', (action.application,)).fetchone()
        if not _application:
            raise ValueError(f'Application {action.application} not found')
        application, passphrase = _application
        if(passphrase != action.passphrase):
            return res.out(HTTPStatus.UNAUTHORIZED, {'error': f'Incorrect {application} passphrase detected'})

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
