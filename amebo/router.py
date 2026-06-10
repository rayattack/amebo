import logging
from os import environ
from uuid import uuid4

# installed libs
from heaven import Application
from heaven.constants import STARTUP, SHUTDOWN

# src code
from amebo import __version__
from amebo.aproko import aproko

logging.basicConfig(
    level=getattr(logging, environ.get('AMEBO_LOG_LEVEL', 'INFO').upper(), logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)


router = Application({
    'envelope_size': int(environ.get('AMEBO_ENVELOPE') or 256),  # how many tasks to fetch at once for processing
    'idles': 5,  # sleep for 5 seconds
    'rest_when': 0,  # reduce frequency of daemons when tasks less than 5
})


# setup daemons and app engine helpers
router.daemons = aproko
router.ASSETS('public', relative_to=__file__)
router.TEMPLATES('templates', relative_to=__file__)


# set up hooks
router.ON(STARTUP, 'amebo.middlewares.database.connect')
router.ON(STARTUP, lambda app: app.keep('version', __version__))
router.ON(STARTUP, 'amebo.middlewares.database.cache')
router.ON(STARTUP, 'amebo.middlewares.database.initialize')
router.ON(STARTUP, 'amebo.middlewares.database.setup_listener')
router.ON(STARTUP, 'amebo.middlewares.security.upsudo')
router.ON(STARTUP, 'amebo.middlewares.security.upsecret')
router.ON(SHUTDOWN, 'amebo.middlewares.database.teardown_listener')
router.ON(SHUTDOWN, 'amebo.middlewares.database.disconnect')


# hooks
router.BEFORE('/*', 'amebo.middlewares.security.cors')


# authenticate first
router.POST('/v8/tokens', 'amebo.controllers.applications.authenticate')


# web ui- views/pages/screens
router.GET('/', 'amebo.controllers.xui.login')
router.GET('/p/:page', 'amebo.controllers.xui.pages')
router.GET('/w/:page', 'amebo.controllers.xui.windows')


# api
router.GET('/v1/actions', 'amebo.controllers.actions.tabulate')
router.GET('/v1/events', 'amebo.controllers.events.tabulate')
router.GET('/v1/applications', 'amebo.controllers.applications.tabulate')
router.GET('/v1/subscriptions', 'amebo.controllers.subscriptions.tabulate')
router.GET('/v1/gists', 'amebo.controllers.gists.tabulate')
router.POST('/v1/gists/:id', 'amebo.controllers.gists.acknowledge')
router.POST('/v1/tokens', 'amebo.controllers.applications.authenticate')
router.POST('/v1/actions', 'amebo.controllers.actions.insert')
router.DELETE('/v1/actions/:id', 'amebo.controllers.actions.remove')
router.POST('/v1/events', 'amebo.controllers.events.insert')
router.POST('/v1/applications', 'amebo.controllers.applications.insert')
router.POST('/v1/subscriptions', 'amebo.controllers.subscriptions.insert')
router.POST('/v1/regists/:id', 'amebo.controllers.gists.replay')
router.GET('/v1/regists', 'amebo.controllers.gists.time_travel')  # bulk replay dry-run (count)
router.POST('/v1/regists', 'amebo.controllers.gists.bulk_replay')  # bulk replay (fire)
router.POST('/v1/requeues', 'amebo.controllers.gists.requeue')  # hand failed gists back to daemon
router.POST('/v1/backfills', 'amebo.controllers.gists.backfill')  # re-register subscription vs history
router.GET('/v1/metrics/deliveries', 'amebo.controllers.metrics.deliveries')
router.GET('/v1/metrics/subscriptions', 'amebo.controllers.metrics.subscriptions')
router.PUT('/v1/applications/:id', 'amebo.controllers.applications.update')
router.PUT('/v1/applications/:id/secret', 'amebo.controllers.applications.set_secret')
router.POST('/v1/applications/:id/apikey', 'amebo.controllers.applications.regenerate_apikey')
router.PATCH('/v1/applications/:id', 'amebo.controllers.applications.toggle_active')
router.GET('/v1/redactions', 'amebo.controllers.redactions.tabulate')
router.POST('/v1/redactions', 'amebo.controllers.redactions.insert')
router.DELETE('/v1/redactions/:id', 'amebo.controllers.redactions.remove')

# maybe add a route to clear cache of compiled schemas ?


# comment me out in production
# router.POST('/h1/identity-created', amebo_sleeper)
