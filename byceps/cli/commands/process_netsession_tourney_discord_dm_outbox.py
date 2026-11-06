"""
byceps.cli.commands.process_netsession_tourney_discord_dm_outbox
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import click
from dotenv import load_dotenv

from byceps.application import create_worker_app
from byceps.config.integration import (
    read_configuration_from_file_given_in_env_var,
)
from byceps.services.netsession_tourney.discord_dm_outbox import (
    process_discord_dm_outbox,
)
from byceps.services.netsession_tourney.worker_loop import repeat_every


@click.command()
@click.option('--limit', default=50, type=int, show_default=True)
@click.option(
    '--every',
    default=0,
    type=int,
    help='Repeat every N seconds in this process (0: run once).',
)
def process_netsession_tourney_discord_dm_outbox(limit: int, every: int) -> None:
    load_dotenv()

    config = read_configuration_from_file_given_in_env_var()
    app = create_worker_app(config)

    def run() -> None:
        processed = process_discord_dm_outbox(limit=limit)
        if processed or not every:
            click.echo(f'processed {processed} Discord-DM outbox item(s)')

    with app.app_context():
        repeat_every(every, run, name='discord_dm_outbox')
