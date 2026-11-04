"""
byceps.services.netsession_tourney.enum_labels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

German labels for the tournament system's enum values, so pages show
"Entwurf" instead of "draft". Used as template filter `ns_label`.
"""

from enum import Enum

from flask_babel import lazy_gettext

from .models import (
    CheckinState,
    CoinChargeMode,
    CoinLedgerEntryKind,
    CoinRefundPolicy,
    MatchState,
    ParticipantStatus,
    ParticipantType,
    RegistrationMode,
    StageStatus,
    TeamMemberRole,
    TournamentMode,
    TournamentStatus,
)


_LABELS = {
    TournamentStatus.draft: lazy_gettext('Entwurf'),
    TournamentStatus.live: lazy_gettext('Live'),
    TournamentStatus.canceled: lazy_gettext('Abgesagt'),
    TournamentStatus.closed: lazy_gettext('Abgeschlossen'),
    StageStatus.draft: lazy_gettext('Entwurf'),
    StageStatus.live: lazy_gettext('Live'),
    StageStatus.closed: lazy_gettext('Abgeschlossen'),
    TournamentMode.duel: lazy_gettext('Duell'),
    TournamentMode.ffa: lazy_gettext('Jeder gegen jeden (FFA)'),
    RegistrationMode.solo: lazy_gettext('Einzelspieler'),
    RegistrationMode.team_captain_managed: lazy_gettext(
        'Teams (Captain verwaltet)'
    ),
    RegistrationMode.team_preformed_only: lazy_gettext('Nur fertige Teams'),
    RegistrationMode.mixed: lazy_gettext('Gemischt'),
    ParticipantType.user: lazy_gettext('Spieler'),
    ParticipantType.team: lazy_gettext('Team'),
    ParticipantStatus.forming: lazy_gettext('In Aufstellung'),
    ParticipantStatus.ready: lazy_gettext('Bereit'),
    ParticipantStatus.checked_in: lazy_gettext('Eingecheckt'),
    ParticipantStatus.locked: lazy_gettext('Gesperrt'),
    ParticipantStatus.dropped: lazy_gettext('Abgemeldet'),
    ParticipantStatus.eliminated: lazy_gettext('Ausgeschieden'),
    CheckinState.pending: lazy_gettext('Offen'),
    CheckinState.checked_in: lazy_gettext('Eingecheckt'),
    CheckinState.missed: lazy_gettext('Verpasst'),
    TeamMemberRole.captain: lazy_gettext('Captain'),
    TeamMemberRole.player: lazy_gettext('Spieler'),
    TeamMemberRole.substitute: lazy_gettext('Ersatz'),
    MatchState.pending: lazy_gettext('Wartet auf Gegner'),
    MatchState.ready: lazy_gettext('Spielbereit'),
    MatchState.in_progress: lazy_gettext('Läuft'),
    MatchState.pending_confirmation: lazy_gettext('Wartet auf Bestätigung'),
    MatchState.needs_admin_review: lazy_gettext('Admin-Prüfung'),
    MatchState.completed: lazy_gettext('Abgeschlossen'),
    MatchState.disputed: lazy_gettext('Strittig'),
    CoinLedgerEntryKind.tournament_registration_charge: lazy_gettext(
        'Turnieranmeldung'
    ),
    CoinLedgerEntryKind.tournament_registration_refund: lazy_gettext(
        'Rückgabe Turnieranmeldung'
    ),
    CoinLedgerEntryKind.admin_adjustment: lazy_gettext('Korrektur (Admin)'),
    CoinChargeMode.captain_only: lazy_gettext('Nur Captain zahlt'),
    CoinChargeMode.all_members: lazy_gettext('Jedes Mitglied zahlt'),
    CoinRefundPolicy.until_tournament_end: lazy_gettext(
        'Rückgabe bis Turnierende'
    ),
    CoinRefundPolicy.until_end_of_round_1: lazy_gettext(
        'Rückgabe bis einschließlich Runde 1'
    ),
}


def enum_label(value: Enum | None) -> str:
    """Return the German label, or the raw value for unknown ones."""
    if value is None:
        return ''

    label = _LABELS.get(value)
    if label is None:
        return str(getattr(value, 'value', value))

    return str(label)
