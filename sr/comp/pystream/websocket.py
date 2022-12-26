import logging
from pathlib import Path

from aiohttp import WSMsgType, web
from aiohttp.web import Response, WebSocketResponse

LOGGER = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.get('/ws')
async def websocket_handler(request):
    """
    WebSocket endpoint, returns an EventStream-like page if visited directly.

    Creates the WebSocket, registers it to the worker and waits until the
    stream dies. Prints any errors and recieved messages to console.
    """
    ws = WebSocketResponse()
    ws_ready = ws.can_prepare(request)
    if not ws_ready.ok:
        # Return a page to view the websocket messages on if this is an HTTP request
        return Response(
            text=(Path(__file__).parent / 'files/websocket_demo.html').read_text(),
            content_type="text/html")

    # Setup the websocket and
    await ws.prepare(request)

    # send current state
    try:
        initial_data = request.app["state"].current_data()
    except KeyError:
        pass
    else:
        for msg in initial_data:
            await ws.send_json(msg)

    # Make the websocket known to the worker task
    request.app["sockets"].add(ws)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                LOGGER.info(f"Received websocket message: {msg.data}")
            elif msg.type == WSMsgType.ERROR:
                LOGGER.warning('ws connection closed with exception %s' %
                      ws.exception())
    except ConnectionResetError:
        # Catch errors from trying to receive from a dead websocket
        pass
    finally:
        request.app["sockets"].discard(ws)

    LOGGER.info('websocket connection closed')
    return ws


def setup(app):
    app.router.add_routes(routes)
