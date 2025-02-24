import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import WSMsgType, web
from aiohttp.web import FileResponse, WebSocketResponse

LOGGER = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.get('/ws')
async def websocket_handler(request):
    """
    WebSocket endpoint, returns an EventStream-like page if visited directly.

    Creates the WebSocket, registers it to the worker and waits until the
    stream dies. Prints any errors and received messages to console.
    """
    ws = WebSocketResponse()
    ws_ready = ws.can_prepare(request)
    if not ws_ready.ok:
        # Return a page to view the websocket messages on if this is an HTTP request
        return FileResponse(str(Path(__file__).parent / 'files/websocket_demo.html'))

    LOGGER.info("New connection to websocket")
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
            srv_recv = datetime.now(tz=timezone.utc).timestamp()
            if msg.type == WSMsgType.TEXT:
                if 'timesync' in msg.data:
                    try:
                        data = msg.json()
                        if data.get('type') == 'timesync':
                            srv_sent = datetime.now(tz=timezone.utc).timestamp()
                            data['server_recv'] = srv_recv
                            data['server_sent'] = srv_sent
                            await ws.send_json(data)
                            continue
                    except json.JSONDecodeError:
                        pass
                LOGGER.info(f"Received websocket message: {msg.data}")
            elif msg.type == WSMsgType.ERROR:
                LOGGER.warning(
                    'ws connection closed with exception %s' %
                    ws.exception())
    except ConnectionResetError:
        # Catch errors from trying to receive from a dead websocket
        pass
    finally:
        request.app["sockets"].discard(ws)

    LOGGER.info('websocket connection closed')
    return ws


@routes.get('/ws/timesync.js')
async def timesync_library(request):
    """Serve timesync.js library."""
    return FileResponse(str(Path(__file__).parent / 'files/timesync.js'))


def setup(app):
    routes.static('/static', Path(__file__).parent / 'files')
    app.router.add_routes(routes)
