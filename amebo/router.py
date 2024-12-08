from os import environ
from uuid import uuid4

# installed libs
from dotenv import load_dotenv
from heaven import Application
from heaven.constants import STARTUP, SHUTDOWN

# src code
from amebo.aproko import aproko
from amebo.constants.literals import AMEBO_SECRET_KEY
from amebo.utils.helpers import deterministic_uuid


router = Application({
    'engine': environ.get('AMEBO_ENGINE') or 'sqlite',
    'envelope_size': int(environ.get('ENVELOPE_SIZE') or 256),  # how many tasks to fetch at once for processing
    'idles': 5,  # sleep for 5 seconds
    'rest_when': 0,  # reduce frequency of daemons when tasks less than 5
    AMEBO_SECRET_KEY: environ.get('AMEBO_SECRET_KEY') or deterministic_uuid()
})


# setup daemons and app engine helpers
router.daemons = aproko
router.ASSETS('public', relative_to=__file__)
router.TEMPLATES('templates', relative_to=__file__)


# set up hooks
router.ON(STARTUP, 'amebo.middlewares.database.connect')
router.ON(STARTUP, 'amebo.middlewares.database.cache')
router.ON(SHUTDOWN, 'amebo.middlewares.database.disconnect')
router.ON(STARTUP, 'amebo.middlewares.database.initialize')
router.ON(STARTUP, 'amebo.middlewares.security.upsudo')
router.ON(STARTUP, 'amebo.middlewares.security.upsecret')


# hooks
router.BEFORE('/*', 'amebo.middlewares.security.cors')
router.BEFORE('/x/*', 'amebo.decorators.security.authenticate')
router.BEFORE('/x1/*', 'amebo.decorators.security.authorization')


# authenticate first
router.POST('/v8/tokens', 'amebo.controllers.applications.authenticate')


# web ui- views/pages/screens
router.GET('/', 'amebo.controllers.xui.login')
router.GET('/p/:page', 'amebo.controllers.xui.pages')


# api
router.GET('/v1/actions', 'amebo.controllers.actions.tabulate')
router.GET('/v1/events', 'amebo.controllers.events.tabulate')
router.GET('/v1/applications', 'amebo.controllers.applications.tabulate')
router.GET('/v1/subscriptions', 'amebo.controllers.subscriptions.tabulate')
router.GET('/v1/gists', 'amebo.controllers.gists.tabulate')
router.POST('/v1/tokens', 'amebo.controllers.applications.authenticate')
router.POST('/v1/actions', 'amebo.controllers.actions.insert')
router.POST('/v1/events', 'amebo.controllers.events.insert')
router.POST('/v1/applications', 'amebo.controllers.applications.insert')
router.POST('/v1/subscriptions', 'amebo.controllers.subscriptions.insert')
router.POST('/v1/regists/:id', 'amebo.controllers.gists.replay')
router.PUT('/v1/applications/:id', 'amebo.controllers.applications.update')

# maybe add a route to clear cache of compiled schemas ?


# comment me out in production
# router.POST('/h1/identity-created', amebo_sleeper)
