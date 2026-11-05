"""
byceps.cli.commands.run_netsession_tourney_discord_bot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from __future__ import annotations

import asyncio

import click
import discord
from dotenv import load_dotenv

from byceps.application import create_worker_app
from byceps.config.integration import (
    read_configuration_from_file_given_in_env_var,
)
from byceps.services.netsession_tourney.discord_dm_service import (
    get_configured_discord_bot_credentials,
)
from byceps.util.result import Err, Ok
from byceps.util.sentry import configure_sentry_from_env


class NetsessionDiscordClient(discord.Client):
    async def on_ready(self) -> None:
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name='Netsession'),
        )
        click.echo(f'Connected to Discord as {self.user}.')


@click.command()
def run_netsession_tourney_discord_bot() -> None:
    """Start the Netsession Discord gateway bot."""
    load_dotenv()

    configure_sentry_from_env('worker')

    config = read_configuration_from_file_given_in_env_var()
    app = create_worker_app(config)

    with app.app_context():
        match get_configured_discord_bot_credentials():
            case Ok(None):
                click.echo(
                    'No configured Discord bot credentials found. '
                    'Nothing to connect.'
                )
                return
            case Ok((_, bot_token)):
                token = bot_token
            case Err(message):
                raise click.ClickException(message)

    intents = discord.Intents.none()
    intents.guilds = True

    client = NetsessionDiscordClient(intents=intents)
    asyncio.run(client.start(token))
