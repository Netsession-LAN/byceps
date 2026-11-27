"""
:Copyright: 2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from types import SimpleNamespace

from byceps.services.netsession_tourney import result_reporting_store


def test_winner_change_with_vanished_blocking_match_is_refused(monkeypatch):
    """If the blocking follow-up match could not be loaded, reporting a new
    winner used to fail with an AttributeError instead of refusing."""
    monkeypatch.setattr(
        result_reporting_store,
        'db',
        SimpleNamespace(session=SimpleNamespace(get=lambda *_: None)),
    )
    monkeypatch.setattr(
        result_reporting_store, 'prepare_swiss_winner_change', lambda _: None
    )
    monkeypatch.setattr(
        result_reporting_store,
        'find_match_result_delete_blocker',
        lambda _: 'blocking-match',
    )

    error = result_reporting_store._check_winner_change_allowed(
        'match-1',
        SimpleNamespace(winner_slot=1),
        SimpleNamespace(winner_slot=2),
    )

    assert error is not None
    assert 'Folge-Match' in error
