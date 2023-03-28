import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress

import aiohttp

LOGGER = logging.getLogger(__name__)


class CachedState:
    def __init__(self, base_url, queue=None) -> None:
        self.session = None
        self._timeout = aiohttp.ClientTimeout(total=30)
        self.base_url = base_url.rstrip('/')
        # Event messages are sent to this queue
        self.queue = queue

        self.state_task = None
        self.current_state_task = None
        self.config_task = None

        self.teams = {}
        self.matches = []
        self.last_scored = None
        self.knockouts = []
        self.tiebreaker = None
        self.state_hash = ''
        self.config = {}
        self.current_match = []
        self.current_staging_matches = []
        self.current_shepherding_matches = []
        self.current_delay = 0

    @asynccontextmanager
    async def checked_response(self, path, silent_404=False):
        """Handle errors raised while connecting tho the HTTP API or from malformed data."""
        url = self.base_url + path
        try:
            async with self.session.get(url, timeout=self._timeout) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                    except UnicodeDecodeError:
                        LOGGER.error(f"Response from {url!r} could not be decoded: {await response.read()!r}")
                        data = None
                    except json.JSONDecodeError:
                        LOGGER.error(f"Response from {url!r} is not valid JSON: {await response.text()!r}")
                        data = None
                    except aiohttp.ContentTypeError:
                        LOGGER.error(f"Response from {url!r} is not JSON: {await response.text()!r}")
                        data = None

                    yield data
                else:
                    if not (response.status == 404 and silent_404 is True):
                        LOGGER.error(f"Invalid status code from {url!r}: {response.status}")
                    yield None
        except aiohttp.ClientError as e:
            LOGGER.error(f"Error making request to {url!r}: {e}")
            yield None

    async def update_data(self):
        """
        Refresh the team, last scored, knockout and tiebreaker states.

        Returns a list of event messages for any state information that has changed.
        """
        msgs = []
        LOGGER.info("Reloading data")

        team_updates = await self.update_teams()
        msgs.extend([
            {'event': 'team', 'data': team_msg}
            for team_msg in team_updates
        ])

        await self.update_matches()
        msgs.extend(await self.update_last_scored_match())
        msgs.extend(await self.update_knockouts())
        msgs.extend(await self.update_tiebreaker())

        return msgs

    async def update_teams(self):
        """
        Fetch the teams data from the HTTP API and cache it.

        Returns a list of event messages for any teams that have changed.
        """
        async with self.checked_response('/teams') as data:
            if data is None or (new_teams := data.get('teams')) is None:
                return []

            # calculate and return diff of teams
            team_changes = []
            removed_teams = set(self.teams.keys()) - set(new_teams.keys())
            team_changes.extend([(tla, None) for tla in removed_teams])

            for key, record in new_teams.items():
                if record != self.teams.get(key):
                    team_changes.append((key, record))

            self.teams = new_teams
            return team_changes

    async def update_matches(self):
        """
        Fetch the matches data from the HTTP API and cache it.

        Triggers refetching the current matches if the value has changed.
        """
        async with self.checked_response('/matches') as data:
            if data is None or (new_matches := data.get('matches')) is None:
                return

            if self.matches != new_matches:
                self.matches = new_matches
                await self.update_current_state()

    async def update_last_scored_match(self):
        """
        Fetch the last scored match number from the HTTP API and cache it.

        Returns an event message if the value has changed.
        """
        async with self.checked_response('/matches/last_scored') as data:
            if data is None or (latest_scored := data.get('last_scored')) is None:
                return []

            if self.last_scored != latest_scored:
                self.last_scored = latest_scored
                return [{'event': 'last-scored-match', 'data': latest_scored}]
        return []

    async def update_knockouts(self):
        """
        Fetch the latest knockout round values from the HTTP API and cache it.

        Returns an event message if the value has changed.
        """
        async with self.checked_response('/knockout') as data:
            if data is None or (new_knockouts := data.get('rounds')) is None:
                return []

            if self.knockouts != new_knockouts:
                self.knockouts = new_knockouts
                return [{'event': 'knockouts', 'data': new_knockouts}]
        return []

    async def update_tiebreaker(self):
        """
        Fetch the latest tiebreaker value from the HTTP API and cache it.

        Returns an event message if the value has changed.
        """
        async with self.checked_response('/tiebreaker', silent_404=True) as data:
            if data is None or (new_tiebreaker := data.get('tiebreaker')) is None:
                return []

            if self.tiebreaker != new_tiebreaker:
                self.tiebreaker = new_tiebreaker
                return [{'event': 'tiebreaker', 'data': new_tiebreaker}]

    async def update_state(self):
        """
        Fetch the current state hash from the HTTP API and cache it.

        When the state information has changed:
        1. Triggers the team, last scored, knockout and tiebreaker state to be refreshed.
        2. Sends event messages to `self.queue` for all changes encountered.
        """
        async with self.checked_response('/state') as data:
            if data is None or (new_state := data.get('state')) is None:
                return

            update_msgs = []
            if self.state_hash != new_state:
                self.state_hash = new_state
                update_msgs = await self.update_data()

            if self.queue is not None:
                for msg in update_msgs:
                    await self.queue.put(msg)

    async def update_current_state(self):
        """
        Fetch the current matches data from the HTTP API and cache it.

        Sends event messages to `self.queue` if the match information has changed.
        """
        async with self.checked_response('/current') as data:
            msgs = []
            if data is None:
                return

            if (new_current_match := data.get('matches')) is not None:
                if self.current_match != new_current_match:
                    self.current_match = new_current_match
                    msgs.append({'event': 'match', 'data': new_current_match})

            if (new_current_staging_matches := data.get('staging_matches')) is not None:
                if self.current_staging_matches != new_current_staging_matches:
                    self.current_staging_matches = new_current_staging_matches
                    msgs.append({
                        'event': 'current-staging-matches',
                        'data': new_current_staging_matches
                    })

            if (new_current_shepherding := data.get('shepherding_matches')) is not None:
                if self.current_shepherding_matches != new_current_shepherding:
                    self.current_shepherding_matches = new_current_shepherding
                    msgs.append({
                        'event': 'current-shepherding-matches',
                        'data': new_current_shepherding
                    })

            if (new_current_delay := data.get('delay')) is not None:
                if self.current_delay != new_current_delay:
                    self.current_delay = new_current_delay
                    msgs.append({'event': 'current-delay', 'data': new_current_delay})

            if self.queue is not None:
                for msg in msgs:
                    await self.queue.put(msg)

    async def update_config(self):
        """
        Fetch the latest config data from the HTTP API and cache it.
        """
        async with self.checked_response('/config') as data:
            if data is None or (new_config := data.get('config')) is None:
                return

            self.config = new_config

    def current_data(self):
        """
        Generate a list of events to express the currently cached state.

        This is useful for when a new client connects.
        """
        msgs = []

        msgs.extend([
            {'event': 'team', 'data': team}
            for team in self.teams.values()
        ])
        msgs.append({'event': 'match', 'data': self.current_match})
        msgs.append({
            'event': 'current-staging-matches',
            'data': self.current_staging_matches
        })
        msgs.append({
            'event': 'current-shepherding-matches',
            'data': self.current_shepherding_matches
        })
        if self.last_scored is not None:
            msgs.append({'event': 'last-scored-match', 'data': self.last_scored})
        if self.knockouts is not []:
            msgs.append({'event': 'knockouts', 'data': self.knockouts})
        msgs.append({'event': 'current-delay', 'data': self.current_delay})
        if self.tiebreaker:
            msgs.append({'event': 'tiebreaker', 'data': self.tiebreaker})

        return msgs

    async def _periodic_task(self, coro, interval, args=[]):
        """Helper wrapper to run a coroutine periodically each interval seconds."""
        while True:
            try:
                await asyncio.gather(
                    asyncio.sleep(interval),
                    coro(*args),
                )
            except Exception as e:
                LOGGER.exception(f"Periodic task failed because {e}")

    async def run(self):
        """Begin fetching the state from the HTTP API periodically."""
        self.session = aiohttp.ClientSession()

        # Generate initial state
        await self.update_state()
        await self.update_current_state()
        await self.update_config()

        # Set particular update routines to run as periodic tasks
        self.state_task = asyncio.create_task(
            self._periodic_task(self.update_state, 0.5))
        self.current_state_task = asyncio.create_task(
            self._periodic_task(self.update_current_state, 2))
        self.config_task = asyncio.create_task(
            self._periodic_task(self.update_config, 0.3))

    async def stop(self):
        """Stop the update tasks and close the underlying network session."""
        for task in (self.state_task, self.current_state_task, self.config_task):
            if task:
                task.cancel()

        for task in (self.state_task, self.current_state_task, self.config_task):
            if task:
                with suppress(asyncio.CancelledError):
                    await task

        await self.session.close()
        self.session = None

        await asyncio.sleep(0)


async def on_startup(app):
    """Create the state tracking tasks and store a reference to be used by requests."""
    # The queue to pass events from state to the worker task
    app["event_queue"] = asyncio.Queue()
    event_queue = app["event_queue"]
    base_url = app["comp_api"]
    app["state"] = CachedState(base_url, event_queue)

    await app["state"].run()
    await asyncio.sleep(0)


async def clean_up(app):
    """Cleanly close the background tasks."""
    await app["state"].stop()


def setup(app, api_url):
    """Configure event handlers."""
    app["comp_api"] = api_url

    app.on_startup.append(on_startup)
    app.on_cleanup.append(clean_up)


def main(argv=None):
    parser = argparse.ArgumentParser(description=(
        "An example of fetching state from the HTTP API and printing the event "
        "stream to console."))

    parser.add_argument('url', help="The URL of the SRComp HTTP API.")

    args = parser.parse_args(argv)

    def print_event(msg):
        """Format event messages to match event strean output."""
        print(f"event: {msg['event']}")
        print(f"data: {msg['data']}")
        print()

    async def api_fetch(base_url):
        """An example task to fetch state from the API and print an event stream to console."""
        event_queue = asyncio.Queue()
        state = CachedState(base_url, event_queue)
        await state.run()
        for msg in state.current_data():
            print_event(msg)

        try:
            while not event_queue.empty():
                msg = await event_queue.get()
                event_queue.task_done()

            while not state.session.closed:
                msg = await event_queue.get()
                print_event(msg)
                event_queue.task_done()
        finally:
            await asyncio.sleep(0)
            await state.stop()

    try:
        asyncio.run(api_fetch(args.url))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
