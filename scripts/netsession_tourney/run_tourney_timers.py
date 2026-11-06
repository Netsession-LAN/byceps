"""Time-driven tasks of the tournament system, run every minute by the
compose service `byceps-tourney-timers`:

- results that were not confirmed in time go to admin review,
- participants get a reminder once a check-in window opens.
"""

from pathlib import Path
import sys

import click

from byceps.services.netsession_tourney.checkin_reminders import (
    send_due_checkin_reminders,
)
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

    reminded = send_due_checkin_reminders()
    if reminded:
        click.echo(f'Sent check-in reminders for {reminded} tournament(s).')


if __name__ == '__main__':
    call_with_app_context(execute)
