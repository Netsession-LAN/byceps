"""Send results that were not confirmed in time to admin review.

Run regularly (the compose service does so every minute).
"""

from pathlib import Path
import sys

import click

from byceps.services.netsession_tourney.match_advancement import (
    resolve_pending_confirmations,
)


sys.path.append(str(Path(__file__).resolve().parents[1]))

from _util import call_with_app_context


@click.command()
def execute() -> None:
    resolved = resolve_pending_confirmations()
    if resolved:
        click.echo(f'Sent {resolved} unconfirmed result(s) to admin review.')


if __name__ == '__main__':
    call_with_app_context(execute)
