import asyncio
import json
import logging

from aiohttp import web
from aiohttp_sse import EventSourceResponse

LOGGER = logging.getLogger(__name__)
routes = web.RouteTableDef()


class SREventSourceResponse(EventSourceResponse):
    async def _ping(self):
        """
        Periodically send ping to the browser.

        Closes the connection if transmission fails.
        Custom ping format to match previous implementation.
        """
        while True:
            await asyncio.sleep(self._ping_interval)
            try:
                await self.send(f"{self._ping_interval * 1000}", event='ping')
            except ConnectionResetError:
                self.stop_streaming()
            except RuntimeError:
                # sending to a closed socket can throw a runtime error
                return


@routes.get('/')
async def stream_handler(request):
    """
    EventStream endpoint.

    Creates the EventStream, registers it to the worker and waits until the
    stream dies.
    """
    LOGGER.info("New connection to stream")
    stream = SREventSourceResponse()
    await stream.prepare(request)
    try:
        stream.ping_interval = request.app['state'].config['ping_period']
    except KeyError:
        pass

    # send current state
    try:
        initial_data = request.app["state"].current_data()
    except KeyError:
        pass
    else:
        try:
            for msg in initial_data:
                await stream.send(
                    json.dumps(msg['data'], separators=(',', ':')), event=msg['event'])
        except ConnectionResetError:
            # Connection closed before we finished sending
            return stream

    request.app["streams"].add(stream)
    try:
        # Wait until the ping task closes, when the connection has closed
        await stream.wait()
    finally:
        request.app["streams"].discard(stream)
    return stream


def setup(app):
    app.router.add_routes(routes)
