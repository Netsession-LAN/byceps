"""
byceps.services.netsession_tourney.domain_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from datetime import datetime

from byceps.util.result import Err, Ok, Result

from .engines.registry import get_stage_type_spec
from .models import (
    MatchState,
    Participant,
    ParticipantStatus,
    Stage,
    Tournament,
    TournamentMode,
    TournamentStatus,
)


def validate_registration_open(
    tournament: Tournament, now: datetime
) -> Result[None, str]:
    if tournament.status != TournamentStatus.draft:
        return Err('Registration is only possible while tournament is in draft.')

    if not tournament.registration_open:
        return Err('Registration is closed.')

    if (
        tournament.registration_deadline is not None
        and now > tournament.registration_deadline
    ):
        return Err('Registration deadline has passed.')

    return Ok(None)


def validate_publishable(
    tournament: Tournament,
    stages: list[Stage],
    participants: list[Participant],
) -> Result[None, str]:
    if tournament.status != TournamentStatus.draft:
        return Err('Only draft tournaments can be published.')

    if not stages:
        return Err('At least one stage is required.')

    if len(select_bracket_ready_participants(participants)) < 2:
        return Err('At least two ready participants are required.')

    for stage in stages:
        spec = get_stage_type_spec(stage.type)
        if not spec.publishable:
            return Err(
                f'Stage type "{stage.type.value}" is disabled or beta only.'
            )

    return Ok(None)


def select_bracket_ready_participants(
    participants: list[Participant],
) -> list[Participant]:
    eligible_statuses = {
        ParticipantStatus.ready,
        ParticipantStatus.checked_in,
        ParticipantStatus.locked,
    }
    return [p for p in participants if p.status in eligible_statuses]


def select_ready_participants(
    participants: list[Participant],
) -> list[Participant]:
    return [p for p in participants if p.status == ParticipantStatus.ready]


def can_actor_report_match_result(
    tournament_mode: TournamentMode,
    actor_is_admin_or_referee: bool,
    is_match_participant_manager: bool,
) -> bool:
    if tournament_mode == TournamentMode.ffa:
        return actor_is_admin_or_referee

    return actor_is_admin_or_referee or is_match_participant_manager


def determine_post_report_state(
    tournament_mode: TournamentMode,
    actor_is_admin_or_referee: bool,
    reports_agree: bool,
) -> MatchState:
    if actor_is_admin_or_referee:
        return MatchState.completed

    if tournament_mode == TournamentMode.ffa:
        return MatchState.needs_admin_review

    if reports_agree:
        return MatchState.completed

    return MatchState.pending_confirmation
