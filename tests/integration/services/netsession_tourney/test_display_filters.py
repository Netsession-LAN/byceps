"""Admin display filters: one date format, German labels for raw values."""

from datetime import datetime

from byceps.services.netsession_tourney.display_filters import (
    format_ns_datetime,
    raw_enum_label,
    status_class,
)
from byceps.services.netsession_tourney.models import (
    MatchState,
    ParticipantStatus,
    TournamentStatus,
)


def test_form_dates_are_shown_without_seconds(admin_app):
    assert format_ns_datetime('2026-12-05T18:00') == '05.12.2026, 18:00'
    assert format_ns_datetime(None) == '-'
    assert format_ns_datetime('kaputt') == 'kaputt'


def test_stored_dates_are_shown_without_seconds(admin_app):
    with admin_app.test_request_context():
        text = format_ns_datetime(datetime(2026, 12, 5, 17, 0, 30))
    assert text.startswith('05.12.2026, ')
    assert text.count(':') == 1


def test_raw_values_get_german_labels(admin_app):
    with admin_app.test_request_context():
        assert raw_enum_label('duel', 'TournamentMode') == 'Duell'
        assert raw_enum_label('solo', 'RegistrationMode') == 'Einzelspieler'
        assert raw_enum_label('unknown', 'TournamentMode') == 'unknown'
        assert raw_enum_label(None, 'TournamentMode') == '-'


def test_status_badges_use_one_colour_per_meaning():
    assert status_class(MatchState.needs_admin_review) == 'status-canceled'
    assert status_class(MatchState.completed) == 'status-closed'
    assert status_class(ParticipantStatus.ready) == 'status-live'
    assert status_class(TournamentStatus.draft) == 'status-draft'
