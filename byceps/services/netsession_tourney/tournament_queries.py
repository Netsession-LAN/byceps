"""
byceps.services.netsession_tourney.tournament_queries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Read-only lookups shared by the tournament service modules: tournaments,
stages, participants, site paths, score parsing and FlatOut 2 races.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID

from .coin_service import (  # noqa: F401
    _append_coin_ledger_entry,
    _build_default_coin_settings,
    _charge_coins_for_tournament_registration,
    _get_manual_coin_adjustment_amount_for_user,
    _get_registration_coin_delta_amount_for_user,
    _get_ticket_coin_amount_for_user,
    _refund_coins_for_tournament_registration_if_available,
    _validate_coin_cost,
    adjust_user_coins,
    configure_coin_settings,
    get_coin_settings,
    get_recent_coin_ledger_entries_for_user,
    get_ticket_category_coin_settings_for_party,
    get_user_coin_balance,
    get_user_coin_balances,
    is_tournament_coin_refund_available,
)
from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTeamMember,
    DbNetsessionTourneyTournament,
)
from .flatout2 import get_flatout2_mode_label
from .models import (
    MatchID,
    Participant,
    ParticipantID,
    ParticipantStatus,
    Stage,
    StageStatus,
    TournamentID,
    TournamentStatus,
)
from .service_helpers import (  # noqa: F401
    _append_audit_log,
    _db_browser_push_config_to_model,
    _db_coin_ledger_entry_to_model,
    _db_coin_settings_to_model,
    _db_discord_dm_config_to_model,
    _db_match_chat_message_to_model,
    _db_match_result_to_model,
    _db_match_slot_to_model,
    _db_match_to_model,
    _db_participant_to_model,
    _db_registration_to_model,
    _db_stage_to_model,
    _db_team_member_to_model,
    _db_ticket_category_coin_settings_to_model,
    _db_tournament_category_to_model,
    _db_tournament_prize_to_model,
    _db_tournament_rule_template_to_model,
    _db_tournament_to_model,
    _find_sponsor_logo_target_url,
    _parse_source_outcome,
)
from .tournament_category_service import (  # noqa: F401
    _ensure_default_tournament_category_for_party,
    _find_db_tournament_category,
    _resolve_tournament_category_id_for_party,
    create_tournament_category,
    DEFAULT_TOURNAMENT_CATEGORY_TITLE,
    find_tournament_category,
    get_tournament_categories_for_party,
    move_tournament_category_down,
    move_tournament_category_up,
    update_tournament_category,
)
from .tournament_prize_service import (  # noqa: F401
    _find_db_tournament_prize,
    create_tournament_prize,
    delete_tournament_prize,
    find_tournament_prize,
    get_tournament_prizes_for_tournament,
    update_tournament_prize,
)
from .tournament_rule_template_service import (  # noqa: F401
    _find_db_tournament_rule_template,
    create_tournament_rule_template,
    find_tournament_rule_template,
    find_tournament_rule_template_by_slug_for_party,
    get_tournament_rule_templates_for_party,
    update_tournament_rule_template,
)


ACTIVE_PARTICIPANT_STATUS_VALUES = {
    ParticipantStatus.forming.value,
    ParticipantStatus.ready.value,
    ParticipantStatus.checked_in.value,
    ParticipantStatus.locked.value,
}


def get_stages_for_tournament(
    party_id: PartyID, tournament_id: TournamentID
) -> list[Stage]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return []

    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()
    return [
        _db_stage_to_model_with_effective_status(
            item, tournament_status=db_tournament.status
        )
        for item in db_stages
    ]


def get_participants_for_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    include_dropped: bool = False,
) -> list[Participant]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return []

    stmt = (
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyParticipant.seed.asc().nullslast(),
            DbNetsessionTourneyParticipant.created_at.asc(),
        )
    )
    if not include_dropped:
        stmt = stmt.filter(
            DbNetsessionTourneyParticipant.status
            != ParticipantStatus.dropped.value
        )

    db_participants = db.session.scalars(stmt).all()
    return [_db_participant_to_model(item) for item in db_participants]


def _parse_numeric_score_value(value: Any) -> int:
    if value is None:
        return 0

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _is_walkover_score_json(score_json: dict[str, Any] | None) -> bool:
    if not isinstance(score_json, dict):
        return False

    return bool(score_json.get('walkover'))


def _parse_match_result_slot_scores(
    slots: list[DbNetsessionTourneyMatchSlot],
    score_json: dict[str, Any] | None,
    *,
    winner_slot: int | None,
) -> dict[int, str]:
    if not slots or not isinstance(score_json, dict):
        return {}

    raw_slots = score_json.get('slots')
    if isinstance(raw_slots, dict):
        parsed_scores = {}
        for slot in slots:
            raw_value = raw_slots.get(str(slot.slot_no))
            if raw_value is None:
                raw_value = raw_slots.get(slot.slot_no)
            if raw_value is None:
                continue

            normalized = str(raw_value).strip()
            if not normalized:
                continue

            parsed_scores[slot.slot_no] = normalized

        if parsed_scores:
            return parsed_scores

    raw_display = score_json.get('display')
    if isinstance(raw_display, str):
        display = raw_display.strip().replace(' ', '')
        if display:
            delimiter = next(
                (
                    candidate
                    for candidate in [':', '-', '/']
                    if candidate in display
                ),
                None,
            )
            if delimiter is not None:
                parts = display.split(delimiter)
                if len(parts) == len(slots) and all(
                    part.isdigit() for part in parts
                ):
                    normalized_parts = list(parts)
                    if len(slots) == 2 and winner_slot is not None:
                        left = int(parts[0])
                        right = int(parts[1])
                        if left != right:
                            first_slot_no = slots[0].slot_no
                            second_slot_no = slots[1].slot_no
                            winner_has_lower_score = (
                                winner_slot == first_slot_no
                                and left < right
                            ) or (
                                winner_slot == second_slot_no
                                and right < left
                            )
                            if winner_has_lower_score:
                                normalized_parts = [parts[1], parts[0]]

                    return {
                        slot.slot_no: normalized_parts[index]
                        for index, slot in enumerate(slots)
                    }

    if winner_slot is None or len(slots) != 2:
        return {}

    return {
        slots[0].slot_no: '1' if winner_slot == slots[0].slot_no else '0',
        slots[1].slot_no: '1' if winner_slot == slots[1].slot_no else '0',
    }


def _get_ffa_points_per_kill(settings: dict[str, Any] | None) -> int:
    if not isinstance(settings, dict):
        return 1

    raw_value = settings.get('points_per_kill', 1)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 1

    return max(0, value)


def _get_flatout2_round_races(
    match_settings: dict[str, Any]
) -> list[dict[str, str]]:
    if not isinstance(match_settings, dict):
        return []

    raw_round_races = match_settings.get('flatout2_races')
    if not isinstance(raw_round_races, list):
        return []

    normalized_races = []
    for race in raw_round_races:
        if not isinstance(race, dict):
            continue
        mode = str(race.get('mode') or '').strip() or 'single_race'
        track = str(race.get('track') or '').strip()
        vehicle = str(race.get('vehicle') or '').strip()
        if not track or not vehicle:
            continue
        normalized_races.append(
            {'mode': mode, 'track': track, 'vehicle': vehicle}
        )

    return normalized_races


def _get_match_host_participant_id(
    db_match: DbNetsessionTourneyMatch,
) -> ParticipantID | None:
    raw_value = (db_match.settings_json or {}).get('host_participant_id')
    if not raw_value:
        return None

    try:
        return ParticipantID(UUID(str(raw_value)))
    except (TypeError, ValueError):
        return None


def _get_selected_host_user_ids(
    db_match: DbNetsessionTourneyMatch,
) -> set[UserID]:
    participant_id = _get_match_host_participant_id(db_match)
    if participant_id is None:
        return set()

    db_participant = db.session.get(DbNetsessionTourneyParticipant, participant_id)
    if (
        db_participant is None
        or db_participant.status not in ACTIVE_PARTICIPANT_STATUS_VALUES
    ):
        return set()

    user_ids = {
        db_participant.user_id,
        db_participant.manager_user_id,
    } - {None}
    user_ids.update(
        db.session.scalars(
            select(DbNetsessionTourneyTeamMember.user_id).filter_by(
                participant_id=participant_id
            )
        ).all()
    )
    return user_ids


def _get_match_involved_user_ids(match_id: MatchID) -> set[UserID]:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
    ).all()
    participant_ids = [slot.participant_id for slot in db_slots if slot.participant_id]
    if not participant_ids:
        return set()

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    participant_ids = [participant.id for participant in db_participants]
    user_ids = {
        participant.user_id
        for participant in db_participants
        if participant.user_id is not None
    }
    user_ids.update(
        participant.manager_user_id
        for participant in db_participants
        if participant.manager_user_id is not None
    )
    user_ids.update(
        db.session.scalars(
            select(DbNetsessionTourneyTeamMember.user_id).filter(
                DbNetsessionTourneyTeamMember.participant_id.in_(participant_ids)
            )
        ).all()
    )
    return user_ids


def _get_active_user_ids_for_tournament(
    tournament_id: TournamentID,
) -> set[UserID]:
    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    participant_ids = [participant.id for participant in db_participants]
    user_ids = {
        participant.user_id
        for participant in db_participants
        if participant.user_id is not None
    }
    user_ids.update(
        participant.manager_user_id
        for participant in db_participants
        if participant.manager_user_id is not None
    )
    if participant_ids:
        user_ids.update(
            db.session.scalars(
                select(DbNetsessionTourneyTeamMember.user_id).filter(
                    DbNetsessionTourneyTeamMember.participant_id.in_(
                        participant_ids
                    )
                )
            ).all()
        )
    return user_ids


def _build_flatout2_round_race_lines(payload: dict[str, Any]) -> list[str]:
    raw_races = payload.get('flatout2_round_races')
    if not isinstance(raw_races, list):
        return []

    lines = []
    for index, race in enumerate(raw_races, start=1):
        if not isinstance(race, dict):
            continue
        mode = str(race.get('mode') or '').strip() or 'single_race'
        track = str(race.get('track') or '').strip()
        vehicle = str(race.get('vehicle') or '').strip()
        if not track or not vehicle:
            continue
        lines.append(
            f'{index}. {get_flatout2_mode_label(mode)} / {track} / {vehicle}'
        )
    return lines


def _build_flatout2_first_race_summary(payload: dict[str, Any]) -> str:
    race_lines = _build_flatout2_round_race_lines(payload)
    if not race_lines:
        return ''

    return f'Erstes Rennen: {race_lines[0][3:]}'


def _find_db_tournament_for_party(
    party_id: PartyID, tournament_id: TournamentID
) -> DbNetsessionTourneyTournament | None:
    return db.session.scalar(
        select(DbNetsessionTourneyTournament).filter_by(
            id=tournament_id, party_id=party_id
        )
    )


def _build_site_tournament_overview_path(slug: str) -> str:
    return f'/ns-tourneys/{slug}'


def _build_site_match_path(slug: str, match_id: MatchID | UUID) -> str:
    return f'/ns-tourneys/{slug}/matches/{match_id}'


def _db_stage_to_model_with_effective_status(
    db_stage: DbNetsessionTourneyStage, *, tournament_status: str
) -> Stage:
    stage = _db_stage_to_model(db_stage)
    if (
        tournament_status == TournamentStatus.draft.value
        and stage.status == StageStatus.live
    ):
        return replace(stage, status=StageStatus.draft)

    return stage
