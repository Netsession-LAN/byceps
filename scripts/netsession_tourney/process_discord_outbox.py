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
from byceps.services.netsession_tourney.worker_loop import repeat_every


sys.path.append(str(Path(__file__).resolve().parents[1]))

from _util import call_with_app_context


@click.command()
@click.option('--limit', default=50, type=int, show_default=True)
@click.option(
    '--every',
    default=0,
    type=int,
    help='Repeat every N seconds in this process (0: run once).',
)
def execute(limit: int, every: int) -> None:
    def run() -> None:
        processed = process_discord_outbox(limit=limit)
        if processed or not every:
            click.echo(f'Processed {processed} Discord outbox item(s).')

    repeat_every(every, run, name='discord_outbox')


if __name__ == '__main__':
    call_with_app_context(execute)
