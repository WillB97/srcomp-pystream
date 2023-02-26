import asyncio
import json
import logging
import weakref
from contextlib import suppress

from aiohttp.web import WebSocketResponse
from aiohttp_sse import EventSourceResponse

LOGGER = logging.getLogger(__name__)


async def worker(app):
    try:
        while True:
            # Fetch the message to send to all eventstreams and websockets
            msg = await app['event_queue'].get()
            LOGGER.debug(msg)
            try:

                # Collect up the actions to be awaited and the calling response so that
                # streams are closed when they die
                actions = []
                actors = [None]

                # Generate eventstream actions
                for stream in app["streams"]:
                    if isinstance(msg['data'], str):
                        data = msg['data']
                    else:
                        data = json.dumps(msg['data'])
                    actions.append(stream.send(data, event=msg['event']))
                    actors.append(stream)

                # Generate websocket actions
                for socket in app['sockets']:
                    actions.append(socket.send_json(msg))
                    actors.append(socket)

                # Run all sending in parallel.
                # return_exceptions is used to collect up the raised execptions so they can
                # be processed.
                res = await asyncio.gather(*actions, return_exceptions=True)
                # res contains an mixture of return values and errors in the same order as the
                # awaitables that were passed
                for result, conn in zip(res, actors):
                    if isinstance(result, Exception):
                        if isinstance(conn, EventSourceResponse):
                            conn.stop_streaming()
                        elif isinstance(conn, WebSocketResponse):
                            await conn.close()
                        else:
                            raise result
            except Exception as e:
                LOGGER.exception(f"Worker thread encountered: {e}")
                await asyncio.sleep(0.5)
            finally:
                app['event_queue'].task_done()
    except Exception as e:
        LOGGER.exception(f"Worker failed with {e}")


async def on_startup(app):
    # Use weakref so that stream connections are automatically removed if the
    # response closes
    app["streams"] = weakref.WeakSet()
    app["sockets"] = weakref.WeakSet()

    # Create a background task and store a reference so that it can be closed later
    app["worker"] = asyncio.create_task(worker(app))


async def clean_up(app):
    """Cleanly close the background thread."""
    app["worker"].cancel()
    with suppress(asyncio.CancelledError):
        await app["worker"]


async def on_shutdown(app):
    """Stop all active streams and websockets before shutting down."""
    waiters = []
    for stream in app["streams"]:
        stream.stop_streaming()
        waiters.append(stream.wait())

    for socket in app['sockets']:
        waiters.append(socket.close())

    await asyncio.gather(*waiters)
    app["streams"].clear()
    app["sockets"].clear()


def setup(app):
    """Configure event handlers."""
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(clean_up)
