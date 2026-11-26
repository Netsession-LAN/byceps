"""
byceps.services.netsession_tourney.blueprints.site.timetable_agenda_days
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Agenda days and their time slots of the party timetable.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from flask_babel import format_datetime, gettext


def _build_agenda_days(
    party_days: list[date],
    selected_day: date | None,
    agenda_items_by_day: dict[date, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    agenda_days: list[dict[str, Any]] = []
    days_for_agenda = [selected_day] if selected_day is not None else party_days
    today = datetime.utcnow().date()
    for day in days_for_agenda:
        items = _sort_agenda_items(agenda_items_by_day.get(day, []))
        if selected_day is None and not items:
            continue

        agenda_days.append(_build_agenda_day(day, items, today))
    return agenda_days


def _sort_agenda_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            item['starts_at'],
            item['tournament'].title.lower(),
            item['stage_name'].lower(),
            item['round_no'],
        ),
    )


def _build_agenda_day(
    day: date, items: list[dict[str, Any]], today: date
) -> dict[str, Any]:
    slots = _build_agenda_slots(items)

    return {
        'date': day,
        'label': format_datetime(datetime.combine(day, time.min), 'EEEE d.M'),
        'is_today': day == today,
        'items': items,
        'item_count': len(items),
        'slots': slots,
        'slot_count': len(slots),
        'tournament_count': len({item['tournament'].id for item in items}),
        'parallel_slot_count': sum(1 for slot in slots if slot['is_parallel']),
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
                    f'{format_datetime(current_start, "HH:mm")} - '
                    f'{format_datetime(current_end, "HH:mm")}'
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
