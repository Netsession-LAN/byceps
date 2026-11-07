"""
byceps.services.netsession_tourney.display_filters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Template filters for the admin pages: one date format without seconds
(`ns_datetime`) and German labels for raw enum values, e.g. from the
wizard state (`ns_raw_label`), and one badge colour per status meaning
(`ns_status_class`).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from flask_babel import format_datetime

from . import models
from .enum_labels import enum_label


DATETIME_PATTERN = 'dd.MM.yyyy, HH:mm'

# badge colours: draft = waiting/prepare, live = active, canceled = needs
# attention, closed = done
_STATUS_CLASSES = {
    'pending': 'status-draft',
    'forming': 'status-draft',
    'pending_confirmation': 'status-draft',
    'ready': 'status-live',
    'in_progress': 'status-live',
    'checked_in': 'status-live',
    'locked': 'status-live',
    'needs_admin_review': 'status-canceled',
    'disputed': 'status-canceled',
    'missed': 'status-canceled',
    'completed': 'status-closed',
    'dropped': 'status-closed',
    'eliminated': 'status-closed',
}


def format_ns_datetime(value: datetime | str | None) -> str:
    """Format a stored (UTC) datetime in the user's time zone, or a local
    `YYYY-MM-DDTHH:MM` string as entered in a form, as "05.12.2026, 18:00"."""
    if not value:
        return '-'
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        return parsed.strftime('%d.%m.%Y, %H:%M')
    return format_datetime(value, DATETIME_PATTERN)


def raw_enum_label(value: str | None, enum_name: str) -> str:
    """German label of a raw enum value, e.g. `'duel'` of `TournamentMode`."""
    if not value:
        return '-'
    enum_class = getattr(models, enum_name, None)
    if not (isinstance(enum_class, type) and issubclass(enum_class, Enum)):
        return str(value)
    try:
        member = enum_class(value)
    except ValueError:
        return str(value)
    return enum_label(member)


def status_class(value: Enum | str | None) -> str:
    """CSS class of a status badge; tournament and stage statuses keep
    their own class (`status-draft`, `status-live`, ...)."""
    raw = getattr(value, 'value', value) or ''
    return _STATUS_CLASSES.get(raw, f'status-{raw}')
