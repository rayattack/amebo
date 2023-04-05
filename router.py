from asyncio import get_running_loop, sleep

# installed libs
from washika import Washika as Router
from routerling.constants import STARTUP, SHUTDOWN

# src code
from amebo import amebo
from controllers import (
    list_actions,
    list_events,
    list_gists,
    list_microservices,
    list_subscribers,

    register_action,
    register_event,
    register_microservice,
    register_subscriber,
    resend_gist,

    update_microservice,
)
from hooks import downsqlite, initdb, upsqlite
from views import (
    render_screen,
)
from utils import serve_public_assets


router = Router({
    'db': 'amebo.db',
    'envelope_size': 256,  # how many tasks to fetch at once for processing
    'idles': 5,  # sleep for 5 seconds
    'rest_when': 0  # reduce frequency of daemons when tasks less than 5
})


async def reschedule_forever():
    loop = get_running_loop()
    await amebo(router)
    loop.create_task(reschedule_forever())


async def amebo_sleeper(req, res, ctx):
    res.status = 202
    await sleep(1.5)


router.ON(STARTUP, upsqlite)
router.ON(STARTUP, initdb)
router.ON(SHUTDOWN, downsqlite)


router.GET('/v1/actions', list_actions)
router.GET('/v1/events', list_events)
router.GET('/v1/microservices', list_microservices)
router.GET('/v1/subscribers', list_subscribers)
router.GET('/v1/gists', list_gists)


router.POST('/v1/actions', register_action)
router.POST('/v1/events', register_event)
router.POST('/v1/microservices', register_microservice)
router.POST('/v1/subscribers', register_subscriber)
router.POST('/v1/regists/:id', resend_gist)


router.PUT('/v1/microservices/:id', update_microservice)


# views/pages/screens
router.GET('/public/*', serve_public_assets)
router.GET('/actions', render_screen)
router.GET('/events', render_screen)
router.GET('/microservices', render_screen)
router.GET('/subscribers', render_screen)
router.GET('/gists', render_screen)


# comment me out in production
# router.POST('/h1/identity-created', amebo_sleeper)


router.daemons = reschedule_forever
