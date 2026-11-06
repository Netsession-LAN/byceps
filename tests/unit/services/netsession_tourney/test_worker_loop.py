"""Workers run as one long-lived process instead of a new process with a
whole app every 15 seconds; a failing run must not end the loop."""

from unittest.mock import patch

import pytest

from byceps.services.netsession_tourney import worker_loop


class _Stop(Exception):
    pass


def test_runs_once_without_interval():
    calls = []
    with patch.object(worker_loop, 'db'):
        worker_loop.repeat_every(0, lambda: calls.append(1), name='test')
    assert calls == [1]


def test_once_mode_raises_errors():
    def fail():
        raise RuntimeError('boom')

    with patch.object(worker_loop, 'db'), pytest.raises(RuntimeError):
        worker_loop.repeat_every(0, fail, name='test')


def test_loop_survives_a_failing_run():
    runs = []

    def task():
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError('first run fails')

    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise _Stop()

    with (
        patch.object(worker_loop, 'db'),
        patch.object(worker_loop.time, 'sleep', fake_sleep),
        pytest.raises(_Stop),
    ):
        worker_loop.repeat_every(15, task, name='test')

    assert len(runs) == 3
    assert sleeps == [15, 15, 15]
