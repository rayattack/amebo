from os import environ
from uuid import uuid4

# installed libs
from dotenv import load_dotenv
from heaven import Application
from heaven.constants import STARTUP, SHUTDOWN

# src code
from amebo import amebo
from constants.literals import SECRET_KEY


router = Application({
    'env_loaded': load_dotenv(),
    'db': environ.get('WASHIKA_STORE') or 'sqlite',
    'envelope_size': int(environ.get('ENVELOPE_SIZE') or 256),  # how many tasks to fetch at once for processing
    'idles': 5,  # sleep for 5 seconds
    'rest_when': 0,  # reduce frequency of daemons when tasks less than 5
    SECRET_KEY: environ.get('secret_key') or str(uuid4())
})


# setup daemons and app engine helpers
router.daemons = amebo
router.ASSETS('public')
router.TEMPLATES('templates')


# set up hooks
router.ON(STARTUP, 'middlewares.database.connect')
router.ON(STARTUP, 'middlewares.database.cache')
router.ON(SHUTDOWN, 'middlewares.database.disconnect')
router.ON(STARTUP, 'middlewares.database.initialize')
router.ON(STARTUP, 'middlewares.security.upsudo')


# hooks
router.BEFORE('/*', 'middlewares.security.cors')


# web ui- views/pages/screens
router.GET('/', 'controllers.app.login')
router.GET('/p/:page', 'controllers.app.pages')


# api
router.GET('/v1/actions', 'controllers.actions.tabulate')
router.GET('/v1/events', 'controllers.events.tabulate')
router.GET('/v1/microservices', 'controllers.microservices.tabulate')
router.GET('/v1/subscribers', 'controllers.subscribers.tabulate')
router.GET('/v1/gists', 'controllers.gists.tabulate')
router.POST('/v1/tokens', 'controllers.microservices.authenticate')
router.POST('/v1/actions', 'controllers.actions.insert')
router.POST('/v1/events', 'controllers.events.insert')
router.POST('/v1/microservices', 'controllers.microservices.insert')
router.POST('/v1/subscribers', 'controllers.subscribers.insert')
router.POST('/v1/gists/:id', 'controllers.gists.replay')
router.PUT('/v1/microservices/:id', 'controllers.microservices.update')

# maybe add a route to clear cache of compiled schemas ?


# comment me out in production
# router.POST('/h1/identity-created', amebo_sleeper)
