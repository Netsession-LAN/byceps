"""
byceps.services.netsession_tourney.engines.implementations_settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Readers for the stage settings the engine implementations use.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from typing import TypeVar


T = TypeVar('T')


def _get_swiss_threshold(settings: dict | None) -> int | None:
    if not isinstance(settings, dict):
        return None

    raw_value = settings.get('swiss_threshold')
    try:
        return int(raw_value)
    except TypeError, ValueError:
        return None


def _get_swiss_round_count_from_settings(settings: dict | None) -> int:
    threshold = _get_swiss_threshold(settings)
    if threshold in {2, 3, 4}:
        return (threshold * 2) - 1

    raw_round_count = (settings or {}).get('round_count', 5)
    try:
        round_count = int(raw_round_count)
    except TypeError, ValueError:
        return 5

    return max(1, round_count)


def _chunked(items: list[T], chunk_size: int) -> list[list[T]]:
    return [
        items[index : index + chunk_size]
        for index in range(0, len(items), chunk_size)
    ]


def _get_round_count(raw_value: object, *, participant_count: int) -> int:
    # Round robin with an odd participant count needs one additional round
    # because each round contains one bye.
    max_rounds = (
        participant_count
        if participant_count % 2 == 1
        else max(1, participant_count - 1)
    )
    if raw_value is None:
        return max_rounds

    try:
        parsed = int(raw_value)
    except TypeError, ValueError:
        return max_rounds

    if parsed < 1:
        return 1

    return min(parsed, max_rounds)


def _get_group_size(raw_value: object) -> int:
    if raw_value is None:
        return 4

    try:
        parsed = int(raw_value)
    except TypeError, ValueError:
        return 4

    return max(2, parsed)


def _get_max_players_per_match(settings: dict) -> int:
    raw = settings.get('max_players_per_match', 8)
    try:
        parsed = int(raw)
    except TypeError, ValueError:
        return 8

    return max(2, parsed)
