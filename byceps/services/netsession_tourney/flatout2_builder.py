"""
byceps.services.netsession_tourney.flatout2_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2: round stages of the stage builder and match generation.
"""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any
from uuid import UUID

from byceps.database import db
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .engines.base import MatchSpec, SlotSpec, StageEngine
from .flatout2_rounds import (
    _build_flatout2_current_round_match_specs,
    _get_flatout2_current_round_generation_context,
)
from .models import (
    Participant,
    ParticipantID,
    Stage,
    StageID,
    StageType,
    Tournament,
    TournamentID,
)
from .result_report_mode import (
    RESULT_REPORT_MODE_ADMIN_ONLY,
)
from .stage_generation_base import (
    _distribute_evenly,
    _StageGenerationPayload,
)


def _summarize_flatout2_builder_rounds(
    *,
    participant_count: int,
    max_players_per_match: int,
    stop_when_participants_at_most: int | None,
) -> list[dict[str, int]]:
    if participant_count < 2 or max_players_per_match < 2:
        return []

    qualifier_count_per_match = 3
    round_summaries: list[dict[str, int]] = []
    current_participant_count = participant_count
    round_no = 1

    while current_participant_count > 1:
        match_count = math.ceil(current_participant_count / max_players_per_match)
        if match_count < 1:
            break

        heat_sizes = _distribute_evenly(current_participant_count, match_count)
        max_heat_size = max(heat_sizes) if heat_sizes else 0
        round_summaries.append(
            {
                'round_no': round_no,
                'match_count': match_count,
                'max_heat_size': max_heat_size,
            }
        )

        if match_count == 1:
            break

        qualified_participant_count = match_count * qualifier_count_per_match
        if (
            stop_when_participants_at_most is not None
            and qualified_participant_count <= stop_when_participants_at_most
        ):
            break

        current_participant_count = qualified_participant_count
        round_no += 1

    return round_summaries


def _build_flatout2_round_stage_display_title(
    round_no: int, total_round_count: int, role: str
) -> str:
    if role == 'preliminary':
        return f'Vorrunde {round_no}'

    if total_round_count > 0 and round_no == total_round_count:
        return 'Finale'

    return f'Runde {round_no}'


def _create_flatout2_builder_round_stages(
    *,
    tournament_id: TournamentID,
    order_no_start: int,
    container_name: str,
    role: str,
    stage_type: StageType,
    round_summaries: list[dict[str, int]],
    common_settings: dict[str, Any],
    initial_source_mode: str,
    initial_source_stage_ids: list[StageID] | None,
    initial_qualifier_top_n: int | None,
    initial_qualifier_top_n_per_match: int | None,
    now: datetime,
) -> tuple[DbNetsessionTourneyStage, list[DbNetsessionTourneyStage]]:
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

    created_round_stages: list[DbNetsessionTourneyStage] = []
    previous_stage_id: StageID | None = None
    total_round_count = len(round_summaries)

    for index, round_summary in enumerate(round_summaries, start=1):
        round_no = int(round_summary.get('round_no') or index)
        display_title = _build_flatout2_round_stage_display_title(
            round_no,
            total_round_count,
            role,
        )
        stage_name = display_title
        round_settings = dict(common_settings)
        round_settings.update(
            {
                'builder_role': f'{role}_round',
                'builder_parent_stage_id': str(container_stage.id),
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
            round_settings['participant_source_mode'] = initial_source_mode
            if initial_source_mode in {'stage_qualifiers', 'stage_match_qualifiers'}:
                round_settings['qualifier_source_stage_ids'] = [
                    str(stage_id) for stage_id in (initial_source_stage_ids or [])
                ]
            if initial_qualifier_top_n is not None:
                round_settings['qualifier_top_n'] = initial_qualifier_top_n
            if initial_qualifier_top_n_per_match is not None:
                round_settings['qualifier_top_n_per_match'] = (
                    initial_qualifier_top_n_per_match
                )
        else:
            round_settings['participant_source_mode'] = 'stage_match_qualifiers'
            round_settings['qualifier_source_stage_ids'] = [str(previous_stage_id)]
            round_settings['qualifier_top_n_per_match'] = 3

        db_round_stage = DbNetsessionTourneyStage(
            StageID(generate_uuid7()),
            tournament_id,
            order_no_start + index,
            stage_type,
            stage_name,
            now,
            settings_json=round_settings,
        )
        db.session.add(db_round_stage)
        created_round_stages.append(db_round_stage)
        previous_stage_id = db_round_stage.id

    container_settings['builder_materialized_stage_ids'] = [
        str(db_stage.id) for db_stage in created_round_stages
    ]
    container_settings['builder_materialized_stage_count'] = len(
        created_round_stages
    )
    container_stage.settings_json = container_settings

    return container_stage, created_round_stages


def _build_manual_flatout2_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
) -> Result[_StageGenerationPayload, str]:
    settings = stage.settings or {}
    raw_rounds = settings.get('flatout2_rounds')
    if not isinstance(raw_rounds, list) or not raw_rounds:
        return Err('Bitte die FlatOut-2-Stage zuerst vorbereiten.')

    try:
        max_players_per_match = int(settings.get('max_players_per_match') or 8)
    except (TypeError, ValueError):
        return Err('Die maximale Teilnehmerzahl pro FlatOut-2-Match ist ungültig.')

    if max_players_per_match < 2 or max_players_per_match > 8:
        return Err(
            'FlatOut 2 unterstützt pro Match nur eine Teilnehmerzahl zwischen 2 und 8.'
        )

    raw_match_blueprints = settings.get('flatout2_match_blueprints')
    if not isinstance(raw_match_blueprints, dict):
        raw_match_blueprints = {}

    match_specs: list[MatchSpec] = []
    seen_match_nos: set[int] = set()

    for raw_round in raw_rounds:
        if not isinstance(raw_round, dict):
            continue

        try:
            round_no = int(raw_round.get('round_no') or 0)
            match_count = int(raw_round.get('match_count') or 0)
        except (TypeError, ValueError):
            return Err('Die FlatOut-2-Rundenkonfiguration ist ungültig.')

        if round_no < 1 or match_count < 1:
            return Err('Jede FlatOut-2-Runde braucht mindestens ein Match.')

        for match_index in range(1, match_count + 1):
            match_no = len(match_specs) + 1
            if match_no in seen_match_nos:
                return Err('Die FlatOut-2-Matchnummern sind nicht eindeutig.')
            seen_match_nos.add(match_no)

            match_key = f'{round_no}:{match_index}'
            blueprint = raw_match_blueprints.get(match_key)
            if not isinstance(blueprint, dict):
                blueprint = {}

            raw_participant_ids = blueprint.get('participant_ids')
            if not isinstance(raw_participant_ids, list):
                raw_participant_ids = []

            participant_ids: list[ParticipantID | None] = []
            for raw_participant_id in raw_participant_ids[:max_players_per_match]:
                if not raw_participant_id:
                    participant_ids.append(None)
                    continue
                try:
                    participant_ids.append(
                        ParticipantID(UUID(str(raw_participant_id)))
                    )
                except (TypeError, ValueError):
                    return Err(
                        'Die Teilnehmerzuordnung in der FlatOut-2-Stage ist ungültig.'
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

            slots = [
                SlotSpec(
                    slot_no=slot_no,
                    participant_id=participant_id,
                    source_match_no=None,
                )
                for slot_no, participant_id in enumerate(participant_ids, start=1)
            ]

            match_specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='ready' if len(real_participant_ids) >= 2 else 'pending',
                    slots=slots,
                )
            )

    if not match_specs:
        return Err('Bitte mindestens ein FlatOut-2-Match konfigurieren.')

    return Ok(
        _StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=[],
            match_specs=match_specs,
            replace_existing_matches=True,
        )
    )


def _build_flatout2_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
    tournament_id: TournamentID,
    require_hosts: bool,
) -> Result[_StageGenerationPayload, str]:
    context_result = _get_flatout2_current_round_generation_context(
        tournament_id=tournament_id,
        stage=stage,
        engine=engine,
        participants=participants,
    )
    if context_result.is_err():
        return Err(context_result.unwrap_err())

    context = context_result.unwrap()
    if require_hosts:
        match_specs_result = _build_flatout2_current_round_match_specs(
            stage=stage,
            context=context,
        )
        if match_specs_result.is_err():
            return Err(match_specs_result.unwrap_err())
        match_specs = match_specs_result.unwrap()
    else:
        match_specs = [
            MatchSpec(
                round_no=context.current_round_no,
                match_no=match_no,
                state='pending',
                slots=[
                    SlotSpec(
                        slot_no=index + 1,
                        participant_id=participant.id,
                        source_match_no=None,
                    )
                    for index, participant in enumerate(context.participants)
                ],
            )
            for match_no in context.match_nos
        ]

    return Ok(
        _StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=context.participants,
            match_specs=match_specs,
            replace_existing_matches=context.replace_existing_matches,
        )
    )
