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

from flask_babel import format_datetime

from byceps.services.netsession_tourney.tournament_service import (
    get_tournaments_for_party,
)

from .timetable_agenda_days import _build_agenda_days
from .timetable_tournament_agenda import _collect_tournament_agenda


def build_party_timetable(
    party, *, selected_day_iso: str | None = None
) -> dict[str, Any]:
    party_days = _build_party_days(party)
    selected_day = _resolve_timetable_selected_day(
        party, party_days, selected_day_iso
    )

    view_mode, selected_day, axis_start, axis_end = _resolve_timetable_axis(
        party, selected_day
    )

    tournaments = _get_sorted_party_tournaments(party)

    agenda_items_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    unscheduled_tournaments: list[dict[str, Any]] = []
    for tournament in tournaments:
        _collect_tournament_agenda(
            party,
            tournament,
            axis_start,
            axis_end,
            agenda_items_by_day,
            unscheduled_tournaments,
        )

    available_days = _build_available_days(party_days)

    agenda_days = _build_agenda_days(
        party_days, selected_day, agenda_items_by_day
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
            item['unscheduled_match_count'] for item in unscheduled_tournaments
        ),
        'item_count': sum(len(day['items']) for day in agenda_days),
        'tournament_count': len(tournaments),
    }


def _resolve_timetable_axis(
    party, selected_day: date | None
) -> tuple[str, date | None, datetime, datetime]:
    view_mode, selected_day, axis_start, axis_end = _resolve_timetable_window(
        party, selected_day
    )
    if axis_end <= axis_start:
        axis_end = axis_start + timedelta(hours=1)
    return view_mode, selected_day, axis_start, axis_end


def _resolve_timetable_window(
    party, selected_day: date | None
) -> tuple[str, date | None, datetime, datetime]:
    if selected_day is None:
        return 'global', None, party.starts_at, party.ends_at

    day_start = datetime.combine(selected_day, time.min)
    next_day_start = day_start + timedelta(days=1)
    axis_start = max(party.starts_at, day_start)
    axis_end = min(party.ends_at, next_day_start)
    if axis_end <= axis_start:
        return 'global', None, party.starts_at, party.ends_at

    return 'day', selected_day, axis_start, axis_end


def _get_sorted_party_tournaments(party) -> list:
    return sorted(
        get_tournaments_for_party(party.id, visible_on_site=True),
        key=lambda tournament: (
            tournament.starts_at or datetime.max,
            tournament.title.lower(),
        ),
    )


def _build_available_days(party_days: list[date]) -> list[dict[str, Any]]:
    return [
        {
            'date': day,
            'iso': day.isoformat(),
            'label': format_datetime(
                datetime.combine(day, time.min), 'EEE d.M'
            ),
        }
        for day in party_days
    ]


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
    step_hours = _get_axis_tick_step_hours(duration_hours, day_view=day_view)

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

    return _complete_axis_ticks(ticks, axis_start, axis_end)


def _get_axis_tick_step_hours(duration_hours: float, *, day_view: bool) -> int:
    if day_view:
        return 2
    if duration_hours <= 30:
        return 2
    if duration_hours <= 72:
        return 4
    if duration_hours <= 120:
        return 6
    return 12


def _complete_axis_ticks(
    ticks: list[datetime], axis_start: datetime, axis_end: datetime
) -> list[datetime]:
    if not ticks:
        return [axis_start, axis_end]
    if ticks[-1] < axis_end:
        ticks.append(axis_end)
    return ticks
