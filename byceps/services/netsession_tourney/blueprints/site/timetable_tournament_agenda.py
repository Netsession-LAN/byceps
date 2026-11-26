"""
byceps.services.netsession_tourney.blueprints.site.timetable_tournament_agenda
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Agenda items (one per stage round) of a tournament in the party
timetable.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from flask_babel import format_datetime, gettext

from byceps.services.netsession_tourney.match_queries import (
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)


def _collect_tournament_agenda(
    party,
    tournament,
    axis_start: datetime,
    axis_end: datetime,
    agenda_items_by_day: dict[date, list[dict[str, Any]]],
    unscheduled_tournaments: list[dict[str, Any]],
) -> None:
    stages = get_stages_for_tournament(party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    matches = get_matches_for_tournament(party.id, tournament.id)

    matches_by_stage_and_round, unscheduled_match_count = (
        _group_scheduled_matches(matches)
    )

    for stage_id, round_no in _sort_stage_round_keys(
        matches_by_stage_and_round, stages_by_id
    ):
        item = _build_round_agenda_item(
            tournament,
            stages_by_id.get(stage_id),
            round_no,
            matches_by_stage_and_round[(stage_id, round_no)],
            axis_start,
            axis_end,
        )
        if item is not None:
            agenda_items_by_day[item['starts_at'].date()].append(item)

    if unscheduled_match_count > 0:
        unscheduled_tournaments.append(
            {
                'tournament': tournament,
                'unscheduled_match_count': unscheduled_match_count,
                'scheduled_round_count': len(matches_by_stage_and_round),
            }
        )


def _group_scheduled_matches(matches) -> tuple[dict[tuple, list], int]:
    matches_by_stage_and_round: dict[tuple, list] = defaultdict(list)
    unscheduled_match_count = 0
    for match in matches:
        if match.scheduled_at is None:
            unscheduled_match_count += 1
            continue
        matches_by_stage_and_round[(match.stage_id, match.round_no)].append(
            match
        )
    return matches_by_stage_and_round, unscheduled_match_count


def _sort_stage_round_keys(matches_by_stage_and_round, stages_by_id) -> list:
    return sorted(
        matches_by_stage_and_round.keys(),
        key=lambda item: (
            stages_by_id[item[0]].order_no if item[0] in stages_by_id else 9999,
            item[1],
        ),
    )


def _build_round_agenda_item(
    tournament,
    stage,
    round_no,
    round_matches,
    axis_start: datetime,
    axis_end: datetime,
) -> dict[str, Any] | None:
    if stage is None:
        return None

    round_start = min(match.scheduled_at for match in round_matches)
    if round_start is None:
        return None

    round_duration_minutes = _estimate_round_duration_minutes(
        stage, len(round_matches)
    )
    round_end = round_start + timedelta(minutes=round_duration_minutes)

    clipped_segment = _clip_segment_to_axis(
        round_start, round_end, axis_start, axis_end
    )
    if clipped_segment is None:
        return None

    return {
        'tournament': tournament,
        'stage_id': stage.id,
        'stage_name': stage.name,
        'round_no': round_no,
        'match_count': len(round_matches),
        'starts_at': round_start,
        'ends_at': round_end,
        'start_label': format_datetime(round_start, 'HH:mm'),
        'end_label': format_datetime(round_end, 'HH:mm'),
        'time_label': (
            f'{format_datetime(round_start, "HH:mm")} - '
            f'{format_datetime(round_end, "HH:mm")}'
        ),
        'duration_minutes': round_duration_minutes,
        'duration_label': gettext(
            '%(minutes)s Min.',
            minutes=round_duration_minutes,
        ),
    }


def _clip_segment_to_axis(
    starts_at: datetime,
    ends_at: datetime,
    axis_start: datetime,
    axis_end: datetime,
) -> tuple[datetime, datetime] | None:
    clipped_start = max(starts_at, axis_start)
    clipped_end = min(ends_at, axis_end)
    if clipped_end <= clipped_start:
        return None
    return clipped_start, clipped_end


def _get_stage_match_duration_minutes(stage) -> int:
    raw_value = stage.settings.get('match_duration_minutes', 30)
    try:
        value = int(raw_value)
    except TypeError, ValueError:
        return 30

    return max(1, value)


def _get_stage_max_matches_per_round(stage) -> int:
    raw_value = stage.settings.get('max_matches_per_round')
    if raw_value is None:
        return 9999

    try:
        value = int(raw_value)
    except TypeError, ValueError:
        return 9999

    return max(1, value)


def _estimate_round_duration_minutes(stage, round_match_count: int) -> int:
    match_duration_minutes = _get_stage_match_duration_minutes(stage)
    max_matches_per_round = _get_stage_max_matches_per_round(stage)
    waves = max(
        1,
        (round_match_count + max_matches_per_round - 1)
        // max_matches_per_round,
    )
    return waves * match_duration_minutes
