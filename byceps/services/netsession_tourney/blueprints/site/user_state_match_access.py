"""
byceps.services.netsession_tourney.blueprints.site.user_state_match_access
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Whether the current user may report a match result or is involved
in a match.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.models import (
    MatchState,
    TournamentMode,
    TournamentStatus,
)


def _is_match_open_for_reports(tournament, match) -> bool:
    if tournament.status != TournamentStatus.live:
        return False

    return match.state in {
        MatchState.ready,
        MatchState.in_progress,
        MatchState.pending_confirmation,
    }


def _is_match_managed_by_user(slots, participants_by_id, user_id) -> bool:
    return any(
        participant is not None and participant.manager_user_id == user_id
        for slot in slots
        for participant in [participants_by_id.get(slot.participant_id)]
    )


def can_user_report_match_result(
    user_id,
    tournament,
    match,
    slots,
    participants_by_id,
    *,
    is_admin_or_referee: bool,
    admin_only: bool = False,
) -> bool:
    if not _is_match_open_for_reports(tournament, match):
        return False

    if is_admin_or_referee:
        return True

    if admin_only:
        return False

    if tournament.mode == TournamentMode.ffa:
        return False

    return _is_match_managed_by_user(slots, participants_by_id, user_id)


def format_open_match_participant_name(slot, *, participants_by_id) -> str:
    if slot.participant_id is None:
        return gettext('offen')

    participant = participants_by_id.get(slot.participant_id)
    if participant is None:
        return gettext('offen')

    return participant.name


def _is_participant_involving_user(
    participant, user_id, members_by_participant_id
) -> bool:
    if participant.user_id == user_id or participant.manager_user_id == user_id:
        return True

    return any(
        member.user_id == user_id
        for member in members_by_participant_id.get(participant.id, [])
    )


def is_match_involving_user(
    user_id,
    slots,
    *,
    participants_by_id,
    members_by_participant_id,
) -> bool:
    for slot in slots:
        if slot.participant_id is None:
            continue

        participant = participants_by_id.get(slot.participant_id)
        if participant is None:
            continue

        if _is_participant_involving_user(
            participant, user_id, members_by_participant_id
        ):
            return True

    return False
