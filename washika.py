from asyncio import gather, get_running_loop

from routerling import Router
from routerling.constants import STARTUP, SHUTDOWN, WILDCARD, DEFAULT
from routerling.utils import preprocessor


def _notify(width=80, event=STARTUP): #pragma: nocover
    drawline = lambda: print('=' * width)
    drawline()
    print(f'NOTE: The `LAST` {event} func above failed and prevented others from running')
    drawline()


class Washika(Router):
    def __init__(self, configurator=None):
        super().__init__(configurator)

        self.__daemons = []

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            while True:
                message = await receive()
                if message['type'] == 'lifespan.startup':
                    try: await self._register()
                    except: _notify()
                    await send({'type': 'lifespan.startup.complete'})
                    await self._rundaemons()
                elif message['type'] == 'lifespan.shutdown':
                    try: await self._unregister()
                    except: _notify(event=SHUTDOWN)
                    await send({'type': 'lifespan.shutdown.complete'})

        metadata = preprocessor(scope)
        subdomain = metadata[0]
        wildcard_engine = self.subdomains.get(WILDCARD)
        engine = self.subdomains.get(subdomain)
        if not engine:
            engine = wildcard_engine if wildcard_engine else self.subdomains.get(DEFAULT)

        response = await engine.handle(scope, receive, send, metadata, self)
        await send({'type': 'http.response.start', 'headers': response.headers, 'status': response.status})
        await send({'type': 'http.response.body', 'body': response.body, **response.metadata})

        # add background tasks
        if response.deferred:
            await gather(*[func() for func in response._deferred])

    async def _rundaemons(self):
        loop = get_running_loop()
        for daemon in self.__daemons:
            print('starting daemons:...')
            loop.create_task(daemon())

    @property
    def daemons(self):
        return self.__daemons

    @daemons.setter
    def daemons(self, daemon):
        self.__daemons.append(daemon)
