#! /usr/bin/env python3
import argparse
import logging
import os

from aiohttp import web

from .state import setup as state_setup
from .stream import setup as stream_setup
from .websocket import setup as websocket_setup
from .worker import setup as worker_setup

LOGGER = logging.getLogger(__name__)


async def on_prepare(request, response):
    """Enable Cross-Origin support."""
    response.headers['Access-Control-Allow-Origin'] = '*'


def setup_logger(debug=False):
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # log from all loggers to stdout
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    if debug:
        root_logger.setLevel(logging.DEBUG)


def setup(app, api_url, debug=False):
    setup_logger(debug)

    worker_setup(app)
    stream_setup(app)
    websocket_setup(app)
    state_setup(app, api_url)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "An EventStream and WebSocket server for events from SRComp by "
            "wrapping the HTTP API."))

    parser.add_argument(
        '--api_url',
        default=os.environ.get('SRCOMP_API_URL', 'http://localhost:5112/comp-api/'),
        help="The url of the SRComp HTTP API")
    parser.add_argument(
        '--bind_address', default=os.environ.get('SRCOMP_STREAM_BIND', '127.0.0.1'),
        help="The network address to bind to, defaults to localhost")
    parser.add_argument(
        '--port', type=int, default=os.environ.get('SRCOMP_STREAM_PORT', 8080),
        help="The port to expose the webserver on, defaults to 8080")
    parser.add_argument('--debug', action='store_true')

    args = parser.parse_args()

    app = web.Application()
    setup(app, args.api_url, args.debug)
    app.on_response_prepare.append(on_prepare)

    web.run_app(app, host=args.bind_address, port=args.port)


if __name__ == '__main__':
    main()
