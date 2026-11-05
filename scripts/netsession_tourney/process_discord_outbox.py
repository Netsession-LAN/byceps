"""Process Discord outbox events for Netsession tourneys.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from pathlib import Path
import sys

import click

from byceps.services.netsession_tourney.discord_service import (
    process_discord_outbox,
)


sys.path.append(str(Path(__file__).resolve().parents[1]))

from _util import call_with_app_context


@click.command()
@click.option('--limit', default=50, type=int, show_default=True)
def execute(limit: int) -> None:
    processed = process_discord_outbox(limit=limit)
    click.echo(f'Processed {processed} Discord outbox item(s).')


if __name__ == '__main__':
    call_with_app_context(execute)
