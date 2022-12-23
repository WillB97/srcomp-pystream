import argparse
import asyncio

import aiohttp


class CachedState:
    def __init__(self, base_url, queue=None) -> None:
        self.session = None
        self.base_url = base_url.rstrip('/')
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

    async def get_json(self, response):
        try:
            return await response.json()
        except aiohttp.ContentTypeError:
            return None

    async def update_data(self):
        msgs = []
        print("Reloading data")

        team_updates = await self.update_teams()
        msgs.extend([
            {'event': 'team', 'data': team_msg}
            for team_msg in team_updates.values()
        ])

        await self.update_matches()
        msgs.extend(await self.update_last_scored_match())
        msgs.extend(await self.update_knockouts())
        msgs.extend(await self.update_tiebreaker())

        return msgs

    async def update_teams(self):
        async with self.session.get(self.base_url + '/teams') as response:
            data = await self.get_json(response)
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
        async with self.session.get(self.base_url + '/matches') as response:
            data = await self.get_json(response)
            if data is None or (new_matches := data.get('matches')) is None:
                return

            if self.matches != new_matches:
                self.matches = new_matches
                await self.update_current_state()

    async def update_last_scored_match(self):
        async with self.session.get(self.base_url + '/matches/last_scored') as response:
            data = await self.get_json(response)
            if data is None or (latest_scored := data.get('last_scored')) is None:
                return []

            if self.last_scored != latest_scored:
                self.last_scored = latest_scored
                return [{'event': 'last-scored-match', 'data': latest_scored}]

    async def update_knockouts(self):
        async with self.session.get(self.base_url + '/knockout') as response:
            data = await self.get_json(response)
            if data is None or (new_knockouts := data.get('rounds')) is None:
                return []

            if self.knockouts != new_knockouts:
                self.knockouts = new_knockouts
                return [{'event': 'knockouts', 'data': new_knockouts}]

    async def update_tiebreaker(self):
        async with self.session.get(self.base_url + '/tiebreaker') as response:
            if response.status_code != 200:
                return []
            data = await self.get_json(response)
            if data is None or (new_tiebreaker := data.get('tiebreaker')) is None:
                return []

            if self.tiebreaker != new_tiebreaker:
                self.tiebreaker = new_tiebreaker
                return [{'event': 'tiebreaker', 'data': new_tiebreaker}]

    async def update_state(self):
        async with self.session.get(self.base_url + '/state') as response:
            data = await self.get_json(response)
            if data is None or (new_state := data.get('state')) is None:
                return

            update_msgs = []
            if self.state_hash != new_state:
                self.state_hash = new_state
                update_msgs = await self.update_data()

            if self.queue:
                for msg in update_msgs:
                    await self.queue.put(msg)

    async def update_current_state(self):
        pass
        async with self.session.get(self.base_url + '/current') as response:
            msgs =[]
            data = await self.get_json(response)
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

            if (new_current_shepherding_matches := data.get('shepherding_matches')) is not None:
                if self.current_shepherding_matches != new_current_shepherding_matches:
                    self.current_shepherding_matches = new_current_shepherding_matches
                    msgs.append({
                        'event': 'current-shepherding-matches',
                        'data': new_current_shepherding_matches
                    })

            if (new_current_delay := data.get('delay')) is not None:
                if self.current_delay != new_current_delay:
                    self.current_delay = new_current_delay
                    msgs.append({'event': 'current-delay', 'data': new_current_delay})

            return msgs

    async def update_config(self):
        async with self.session.get(self.base_url + '/config') as response:
            data = await self.get_json(response)
            if data is None or (new_config := data.get('config')) is None:
                return

            self.config = new_config

    def current_data(self):
        msgs = []

        msgs.extend([
            {'event': 'team', 'data': team}
            for team in self.teams.values()
        ])
        msgs.append({'event': 'match', 'data': self.current_match})
        msgs.append({'event': 'current-staging-matches', 'data': self.current_staging_matches})
        msgs.append({'event': 'current-shepherding-matches', 'data': self.current_shepherding_matches})
        if self.last_scored is not None:
            msgs.append({'event': 'last-scored-match', 'data': self.last_scored})
        if self.knockouts is not []:
            msgs.append({'event': 'knockouts', 'data': self.knockouts})
        msgs.append({'event': 'current-delay', 'data': self.current_delay})
        if self.tiebreaker:
            msgs.append({'event': 'tiebreaker', 'data': self.tiebreaker})

        return msgs

    async def _periodic_task(self, coro, interval):
        while True:
            await asyncio.gather(
                asyncio.sleep(interval),
                coro,
            )

    async def run(self):
        self.session = aiohttp.ClientSession()
        self.state_task = asyncio.create_task(self._periodic_task(self.update_state(), 0.5))
        self.current_state_task = asyncio.create_task(
            self._periodic_task(self.update_current_state(), 2))
        self.config_task = asyncio.create_task(self._periodic_task(self.update_config(), 0.3))

    async def stop(self):
        for task in (self.state_task, self.current_state_task, self.config_task):
            if task:
                task.cancel()

        await self.session.close()
        self.session = None

        await asyncio.sleep(0.1)


def main(argv=None):
    parser = argparse.ArgumentParser()

    parser.add_argument('url', help="The URL of the SRComp HTTP API.")

    args = parser.parse_args(argv)

    async def api_fetch(base_url):
        state = CachedState(base_url)
        await state.run()
        await asyncio.sleep(1)
        await state.stop()

        for msg in state.current_data():
            print(msg)

    asyncio.run(api_fetch(args.url))


if __name__ == '__main__':
    main()