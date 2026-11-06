"""
byceps.services.netsession_tourney.blueprints.site.timetable_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from flask_babel import format_datetime, gettext

from ...match_queries import get_matches_for_tournament
from ...tournament_queries import get_stages_for_tournament
from ...tournament_service import get_tournaments_for_party


def build_party_timetable(
    party, *, selected_day_iso: str | None = None
) -> dict[str, Any]:
    party_days = _build_party_days(party)
    selected_day = _resolve_timetable_selected_day(
        party, party_days, selected_day_iso
    )

    if selected_day is None:
        view_mode = 'global'
        axis_start = party.starts_at
        axis_end = party.ends_at
    else:
        view_mode = 'day'
        day_start = datetime.combine(selected_day, time.min)
        next_day_start = day_start + timedelta(days=1)
        axis_start = max(party.starts_at, day_start)
        axis_end = min(party.ends_at, next_day_start)
        if axis_end <= axis_start:
            view_mode = 'global'
            selected_day = None
            axis_start = party.starts_at
            axis_end = party.ends_at

    if axis_end <= axis_start:
        axis_end = axis_start + timedelta(hours=1)

    tournaments = sorted(
        get_tournaments_for_party(party.id, visible_on_site=True),
        key=lambda tournament: (
            tournament.starts_at or datetime.max,
            tournament.title.lower(),
        ),
    )

    agenda_items_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    unscheduled_tournaments: list[dict[str, Any]] = []
    for tournament in tournaments:
        stages = get_stages_for_tournament(party.id, tournament.id)
        stages_by_id = {stage.id: stage for stage in stages}
        matches = get_matches_for_tournament(party.id, tournament.id)

        matches_by_stage_and_round: dict[tuple, list] = defaultdict(list)
        unscheduled_match_count = 0
        for match in matches:
            if match.scheduled_at is None:
                unscheduled_match_count += 1
                continue
            matches_by_stage_and_round[(match.stage_id, match.round_no)].append(match)

        sorted_stage_round_keys = sorted(
            matches_by_stage_and_round.keys(),
            key=lambda item: (
                stages_by_id[item[0]].order_no if item[0] in stages_by_id else 9999,
                item[1],
            ),
        )
        for stage_id, round_no in sorted_stage_round_keys:
            stage = stages_by_id.get(stage_id)
            if stage is None:
                continue

            round_matches = matches_by_stage_and_round[(stage_id, round_no)]
            round_start = min(match.scheduled_at for match in round_matches)
            if round_start is None:
                continue

            round_duration_minutes = _estimate_round_duration_minutes(
                stage, len(round_matches)
            )
            round_end = round_start + timedelta(minutes=round_duration_minutes)

            clipped_segment = _clip_segment_to_axis(
                round_start, round_end, axis_start, axis_end
            )
            if clipped_segment is None:
                continue
            item_day = round_start.date()
            agenda_items_by_day[item_day].append(
                {
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
                        f"{format_datetime(round_start, 'HH:mm')} - "
                        f"{format_datetime(round_end, 'HH:mm')}"
                    ),
                    'duration_minutes': round_duration_minutes,
                    'duration_label': gettext(
                        '%(minutes)s Min.',
                        minutes=round_duration_minutes,
                    ),
                }
            )

        if unscheduled_match_count > 0:
            unscheduled_tournaments.append(
                {
                    'tournament': tournament,
                    'unscheduled_match_count': unscheduled_match_count,
                    'scheduled_round_count': len(matches_by_stage_and_round),
                }
            )

    available_days = [
        {
            'date': day,
            'iso': day.isoformat(),
            'label': format_datetime(datetime.combine(day, time.min), 'EEE d.M'),
        }
        for day in party_days
    ]

    agenda_days: list[dict[str, Any]] = []
    days_for_agenda = (
        [selected_day] if selected_day is not None else party_days
    )
    today = datetime.utcnow().date()
    for day in days_for_agenda:
        items = sorted(
            agenda_items_by_day.get(day, []),
            key=lambda item: (
                item['starts_at'],
                item['tournament'].title.lower(),
                item['stage_name'].lower(),
                item['round_no'],
            ),
        )
        if selected_day is None and not items:
            continue

        slots = _build_agenda_slots(items)

        agenda_days.append(
            {
                'date': day,
                'label': format_datetime(
                    datetime.combine(day, time.min), 'EEEE d.M'
                ),
                'is_today': day == today,
                'items': items,
                'item_count': len(items),
                'slots': slots,
                'slot_count': len(slots),
                'tournament_count': len(
                    {item['tournament'].id for item in items}
                ),
                'parallel_slot_count': sum(
                    1 for slot in slots if slot['is_parallel']
                ),
            }
        )

    return {
        'view_mode': view_mode,
        'selected_day': selected_day,
        'available_days': available_days,
        'available_day_count': len(available_days),
        'agenda_days': agenda_days,
        'unscheduled_tournaments': sorted(
            unscheduled_tournaments,
            key=lambda item: item['tournament'].title.lower(),
        ),
        'unscheduled_match_total': sum(
            item['unscheduled_match_count']
            for item in unscheduled_tournaments
        ),
        'item_count': sum(len(day['items']) for day in agenda_days),
        'tournament_count': len(tournaments),
    }


def _build_agenda_slots(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []

    slots: list[dict[str, Any]] = []
    current_items: list[dict[str, Any]] = []
    current_start: datetime | None = None
    current_end: datetime | None = None

    def flush_slot() -> None:
        nonlocal current_items, current_start, current_end
        if not current_items or current_start is None or current_end is None:
            return

        slots.append(
            {
                'starts_at': current_start,
                'ends_at': current_end,
                'start_label': format_datetime(current_start, 'HH:mm'),
                'end_label': format_datetime(current_end, 'HH:mm'),
                'time_label': (
                    f"{format_datetime(current_start, 'HH:mm')} - "
                    f"{format_datetime(current_end, 'HH:mm')}"
                ),
                'duration_minutes': int(
                    (current_end - current_start).total_seconds() // 60
                ),
                'duration_label': gettext(
                    '%(minutes)s Min.',
                    minutes=int(
                        (current_end - current_start).total_seconds() // 60
                    ),
                ),
                'items': current_items,
                'item_count': len(current_items),
                'tournament_count': len(
                    {item['tournament'].id for item in current_items}
                ),
                'is_parallel': len(current_items) > 1,
            }
        )
        current_items = []
        current_start = None
        current_end = None

    for item in items:
        item_start = item['starts_at']
        item_end = item['ends_at']
        if current_end is None or current_start is None:
            current_items = [item]
            current_start = item_start
            current_end = item_end
            continue

        if item_start < current_end:
            current_items.append(item)
            if item_end > current_end:
                current_end = item_end
            continue

        flush_slot()
        current_items = [item]
        current_start = item_start
        current_end = item_end

    flush_slot()

    return slots


def _build_party_days(party) -> list[date]:
    day = party.starts_at.date()
    end_day = party.ends_at.date()
    days: list[date] = []
    while day <= end_day:
        days.append(day)
        day += timedelta(days=1)
    return days


def _resolve_timetable_selected_day(
    party, party_days: list[date], selected_day_iso: str | None
) -> date | None:
    if selected_day_iso:
        try:
            selected_day = date.fromisoformat(selected_day_iso)
        except ValueError:
            selected_day = None
        if selected_day in party_days:
            return selected_day

    today = datetime.utcnow().date()
    if party.starts_at.date() <= today <= party.ends_at.date():
        return today

    return None


def _build_timetable_axis_ticks(
    axis_start: datetime, axis_end: datetime, *, day_view: bool
) -> list[datetime]:
    duration_hours = max(1.0, (axis_end - axis_start).total_seconds() / 3600.0)
    if day_view:
        step_hours = 2
    elif duration_hours <= 30:
        step_hours = 2
    elif duration_hours <= 72:
        step_hours = 4
    elif duration_hours <= 120:
        step_hours = 6
    else:
        step_hours = 12

    first_tick = axis_start.replace(minute=0, second=0, microsecond=0)
    first_tick_midnight = datetime.combine(first_tick.date(), time.min)
    hours_from_midnight = int(
        (first_tick - first_tick_midnight).total_seconds() // 3600
    )
    aligned_hours = (hours_from_midnight // step_hours) * step_hours
    tick = first_tick_midnight + timedelta(hours=aligned_hours)
    while tick < axis_start:
        tick += timedelta(hours=step_hours)

    ticks: list[datetime] = []
    while tick <= axis_end:
        ticks.append(tick)
        tick += timedelta(hours=step_hours)

    if not ticks:
        ticks = [axis_start, axis_end]
    elif ticks[-1] < axis_end:
        ticks.append(axis_end)

    return ticks


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
    except (TypeError, ValueError):
        return 30

    return max(1, value)


def _get_stage_max_matches_per_round(stage) -> int:
    raw_value = stage.settings.get('max_matches_per_round')
    if raw_value is None:
        return 9999

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 9999

    return max(1, value)


def _estimate_round_duration_minutes(stage, round_match_count: int) -> int:
    match_duration_minutes = _get_stage_match_duration_minutes(stage)
    max_matches_per_round = _get_stage_max_matches_per_round(stage)
    waves = max(
        1,
        (round_match_count + max_matches_per_round - 1) // max_matches_per_round,
    )
    return waves * match_duration_minutes
