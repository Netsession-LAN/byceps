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


@click.command()
@click.option('--limit', default=50, type=int, show_default=True)
def process_netsession_tourney_discord_dm_outbox(limit: int) -> None:
    load_dotenv()

    config = read_configuration_from_file_given_in_env_var()
    app = create_worker_app(config)

    with app.app_context():
        processed = process_discord_dm_outbox(limit=limit)

    click.echo(f'processed {processed} Discord-DM outbox item(s)')
