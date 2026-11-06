"""
byceps.services.netsession_tourney.swiss_thresholds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Swiss win/loss thresholds and the round count that follows from them.
"""

from __future__ import annotations

from typing import Any

from .models import (
    Stage,
)


SWISS_THRESHOLDS = {2, 3, 4}


def get_round_count_for_swiss_stage(
    stage: Stage, *, participant_count: int
) -> int:
    configured_threshold = get_configured_swiss_threshold(stage.settings)
    if configured_threshold is not None:
        return get_swiss_round_count_for_threshold(configured_threshold)

    max_rounds = max(1, participant_count - 1)
    raw_value = (stage.settings or {}).get('round_count')
    if raw_value is None:
        return max_rounds

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return max_rounds

    if parsed < 1:
        return 1

    return min(parsed, max_rounds)


def get_swiss_threshold_for_round_count(round_count: int) -> int:
    return (round_count // 2) + 1


def get_swiss_round_count_for_threshold(threshold: int) -> int:
    return (threshold * 2) - 1


def get_configured_swiss_threshold(settings: dict[str, Any] | None) -> int | None:
    if not isinstance(settings, dict):
        return None

    raw_value = settings.get('swiss_threshold')
    try:
        threshold = int(raw_value)
    except (TypeError, ValueError):
        return None

    return threshold if threshold in SWISS_THRESHOLDS else None


def get_swiss_threshold_for_stage(
    stage: Stage, *, participant_count: int
) -> int:
    configured_threshold = get_configured_swiss_threshold(stage.settings)
    if configured_threshold is not None:
        return configured_threshold

    round_count = get_round_count_for_swiss_stage(
        stage, participant_count=participant_count
    )
    return get_swiss_threshold_for_round_count(round_count)
