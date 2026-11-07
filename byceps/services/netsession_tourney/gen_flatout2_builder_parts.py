"""
byceps.services.netsession_tourney.gen_flatout2_builder_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2 builder helpers: container and round stage settings of the
stage builder, and match specs of a manually prepared FlatOut 2 stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from byceps.database import db
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .engines.base import MatchSpec, SlotSpec
from .models import (
    ParticipantID,
    StageID,
    StageType,
    TournamentID,
)
from .result_report_mode import (
    RESULT_REPORT_MODE_ADMIN_ONLY,
)


@dataclass(frozen=True, kw_only=True)
class Flatout2InitialRoundSource:
    """Where the participants of the first round stage come from."""

    source_mode: str
    source_stage_ids: list[StageID] | None
    qualifier_top_n: int | None
    qualifier_top_n_per_match: int | None


def create_flatout2_builder_container_stage(
    *,
    tournament_id: TournamentID,
    order_no_start: int,
    container_name: str,
    role: str,
    stage_type: StageType,
    common_settings: dict[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], DbNetsessionTourneyStage]:
    container_settings = dict(common_settings)
    container_settings.update(
        {
            'builder_role': role,
            'builder_is_container': True,
            'builder_materialized_stage_ids': [],
        }
    )
    container_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        order_no_start,
        stage_type,
        container_name,
        now,
        settings_json=container_settings,
    )
    db.session.add(container_stage)
    return container_settings, container_stage


def build_flatout2_builder_round_stage_settings(
    common_settings: dict[str, Any],
    *,
    role: str,
    container_stage_id: StageID,
    round_no: int,
    display_title: str,
    total_round_count: int,
    round_summary: dict[str, int],
    previous_stage_id: StageID | None,
    initial_source: Flatout2InitialRoundSource,
) -> dict[str, Any]:
    round_settings = dict(common_settings)
    round_settings.update(
        {
            'builder_role': f'{role}_round',
            'builder_parent_stage_id': str(container_stage_id),
            'builder_materialized_round_stage': True,
            'builder_display_round_no': round_no,
            'builder_display_title': display_title,
            'builder_round_is_final': round_no == total_round_count,
            'builder_expected_match_count': round_summary.get('match_count'),
            'builder_expected_max_heat_size': round_summary.get(
                'max_heat_size'
            ),
            'result_report_mode': RESULT_REPORT_MODE_ADMIN_ONLY,
        }
    )

    if previous_stage_id is None:
        initial_source_mode = initial_source.source_mode
        round_settings['participant_source_mode'] = initial_source_mode
        if initial_source_mode in {
            'stage_qualifiers',
            'stage_match_qualifiers',
        }:
            round_settings['qualifier_source_stage_ids'] = [
                str(stage_id)
                for stage_id in (initial_source.source_stage_ids or [])
            ]
        if initial_source.qualifier_top_n is not None:
            round_settings['qualifier_top_n'] = initial_source.qualifier_top_n
        if initial_source.qualifier_top_n_per_match is not None:
            round_settings['qualifier_top_n_per_match'] = (
                initial_source.qualifier_top_n_per_match
            )
    else:
        round_settings['participant_source_mode'] = 'stage_match_qualifiers'
        round_settings['qualifier_source_stage_ids'] = [str(previous_stage_id)]
        round_settings['qualifier_top_n_per_match'] = 3

    return round_settings


def read_manual_flatout2_max_players_per_match(
    settings: dict[str, Any],
) -> Result[int, str]:
    try:
        max_players_per_match = int(settings.get('max_players_per_match') or 8)
    except (TypeError, ValueError):
        return Err(
            'Die maximale Teilnehmerzahl pro FlatOut-2-Match ist ungültig.'
        )

    if max_players_per_match < 2 or max_players_per_match > 8:
        return Err(
            'FlatOut 2 unterstützt pro Match nur eine Teilnehmerzahl zwischen 2 und 8.'
        )

    return Ok(max_players_per_match)


def append_manual_flatout2_round_match_specs(
    raw_round: dict[str, Any],
    *,
    raw_match_blueprints: dict[str, Any],
    max_players_per_match: int,
    match_specs: list[MatchSpec],
    seen_match_nos: set[int],
) -> str | None:
    """Append the match specs of one round; return an error message, if any."""
    try:
        round_no = int(raw_round.get('round_no') or 0)
        match_count = int(raw_round.get('match_count') or 0)
    except (TypeError, ValueError):
        return 'Die FlatOut-2-Rundenkonfiguration ist ungültig.'

    if round_no < 1 or match_count < 1:
        return 'Jede FlatOut-2-Runde braucht mindestens ein Match.'

    for match_index in range(1, match_count + 1):
        match_no = len(match_specs) + 1
        if match_no in seen_match_nos:
            return 'Die FlatOut-2-Matchnummern sind nicht eindeutig.'
        seen_match_nos.add(match_no)

        match_key = f'{round_no}:{match_index}'
        blueprint = raw_match_blueprints.get(match_key)
        if not isinstance(blueprint, dict):
            blueprint = {}

        participant_ids_result = _parse_manual_flatout2_match_participant_ids(
            blueprint, max_players_per_match
        )
        if participant_ids_result.is_err():
            return participant_ids_result.unwrap_err()
        participant_ids = participant_ids_result.unwrap()

        match_specs.append(
            _build_manual_flatout2_match_spec(
                round_no, match_no, participant_ids
            )
        )

    return None


def _parse_manual_flatout2_match_participant_ids(
    blueprint: dict[str, Any],
    max_players_per_match: int,
) -> Result[list[ParticipantID | None], str]:
    raw_participant_ids = blueprint.get('participant_ids')
    if not isinstance(raw_participant_ids, list):
        raw_participant_ids = []

    participant_ids: list[ParticipantID | None] = []
    for raw_participant_id in raw_participant_ids[:max_players_per_match]:
        if not raw_participant_id:
            participant_ids.append(None)
            continue
        try:
            participant_ids.append(ParticipantID(UUID(str(raw_participant_id))))
        except (TypeError, ValueError):
            return Err(
                'Die Teilnehmerzuordnung in der FlatOut-2-Phase ist ungültig.'
            )

    while len(participant_ids) < max_players_per_match:
        participant_ids.append(None)

    real_participant_ids = [
        participant_id
        for participant_id in participant_ids
        if participant_id is not None
    ]
    if len(set(real_participant_ids)) != len(real_participant_ids):
        return Err(
            'Ein FlatOut-2-Match darf denselben Teilnehmer nicht mehrfach enthalten.'
        )

    return Ok(participant_ids)


def _build_manual_flatout2_match_spec(
    round_no: int,
    match_no: int,
    participant_ids: list[ParticipantID | None],
) -> MatchSpec:
    real_participant_ids = [
        participant_id
        for participant_id in participant_ids
        if participant_id is not None
    ]

    slots = [
        SlotSpec(
            slot_no=slot_no,
            participant_id=participant_id,
            source_match_no=None,
        )
        for slot_no, participant_id in enumerate(participant_ids, start=1)
    ]

    return MatchSpec(
        round_no=round_no,
        match_no=match_no,
        state='ready' if len(real_participant_ids) >= 2 else 'pending',
        slots=slots,
    )
