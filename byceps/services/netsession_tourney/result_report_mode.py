"""
byceps.services.netsession_tourney.result_report_mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Who may report a match result in a stage, and the match state afterwards
(stage setting `result_report_mode`).
"""

from __future__ import annotations

from typing import Any

from .models import MatchState, Stage, TournamentMode


RESULT_REPORT_MODE_BOTH_MUST_CONFIRM = 'both_must_confirm'
RESULT_REPORT_MODE_WINNER_CAN_REPORT = 'winner_can_report'
RESULT_REPORT_MODE_LOSER_CAN_REPORT = 'loser_can_report'
RESULT_REPORT_MODE_ADMIN_ONLY = 'admin_only'
RESULT_REPORT_MODES = {
    RESULT_REPORT_MODE_BOTH_MUST_CONFIRM,
    RESULT_REPORT_MODE_WINNER_CAN_REPORT,
    RESULT_REPORT_MODE_LOSER_CAN_REPORT,
    RESULT_REPORT_MODE_ADMIN_ONLY,
}


def is_stage_result_reporting_admin_only(stage: Stage | None) -> bool:
    """Return `True` if only admins/referees may enter results in the stage."""
    if stage is None:
        return False
    return (
        get_stage_result_report_mode(stage.settings)
        == RESULT_REPORT_MODE_ADMIN_ONLY
    )


def get_stage_result_report_mode(stage_settings: dict[str, Any] | None) -> str:
    if not stage_settings:
        return RESULT_REPORT_MODE_BOTH_MUST_CONFIRM

    raw_value = stage_settings.get('result_report_mode')
    if raw_value in RESULT_REPORT_MODES:
        return raw_value

    return RESULT_REPORT_MODE_BOTH_MUST_CONFIRM


def validate_actor_matches_report_mode(
    tournament_mode: TournamentMode,
    stage_result_report_mode: str,
    *,
    actor_is_admin_or_referee: bool,
    actor_slot_no: int | None,
    winner_slot: int | None,
) -> str | None:
    if actor_is_admin_or_referee:
        return None

    if stage_result_report_mode == RESULT_REPORT_MODE_ADMIN_ONLY:
        return 'In dieser Phase tragen nur Admins die Ergebnisse ein.'

    if tournament_mode != TournamentMode.duel:
        return None

    if stage_result_report_mode == RESULT_REPORT_MODE_BOTH_MUST_CONFIRM:
        return None

    if winner_slot is None:
        return 'A winner must be provided.'
    if actor_slot_no is None:
        return 'Only participants of this match can report a result.'

    if stage_result_report_mode == RESULT_REPORT_MODE_WINNER_CAN_REPORT:
        if actor_slot_no != winner_slot:
            return 'Only the winner can report the result for this stage.'
        return None

    if stage_result_report_mode == RESULT_REPORT_MODE_LOSER_CAN_REPORT:
        if actor_slot_no == winner_slot:
            return 'Only the loser can report the result for this stage.'
        return None

    return None


def determine_post_report_state(
    tournament_mode: TournamentMode,
    stage_result_report_mode: str,
    *,
    actor_is_admin_or_referee: bool,
    reports_agree: bool,
    conflicting_duel_reports: bool,
) -> MatchState:
    if actor_is_admin_or_referee:
        return MatchState.completed

    if tournament_mode == TournamentMode.ffa:
        return MatchState.needs_admin_review

    if stage_result_report_mode in {
        RESULT_REPORT_MODE_WINNER_CAN_REPORT,
        RESULT_REPORT_MODE_LOSER_CAN_REPORT,
    }:
        return MatchState.completed

    if conflicting_duel_reports:
        return MatchState.needs_admin_review

    if reports_agree:
        return MatchState.completed

    return MatchState.pending_confirmation
