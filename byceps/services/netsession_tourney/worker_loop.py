"""
byceps.services.netsession_tourney.worker_loop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Background workers (outboxes, timers) run as one long-lived process that
repeats its task, instead of a shell loop that started a new process with
a whole app every few seconds.
"""

from __future__ import annotations

from collections.abc import Callable
import time

import structlog

from byceps.database import db


log = structlog.get_logger()


def repeat_every(seconds: int, task: Callable[[], object], *, name: str) -> None:
    """Run `task` in the current app context every `seconds`.

    With `seconds` <= 0 run it once (errors propagate). In the loop, a
    failing run is logged and the next one follows as usual.
    """
    while True:
        try:
            task()
        except Exception:
            db.session.rollback()
            if seconds <= 0:
                raise
            log.exception('netsession_tourney.worker_run_failed', worker=name)
        finally:
            db.session.remove()

        if seconds <= 0:
            return
        time.sleep(seconds)
