"""
byceps.services.netsession_tourney.flatout2_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2: round stages of the stage builder and match generation.
"""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any

from byceps.database import db
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .engines.base import MatchSpec, SlotSpec, StageEngine
from .flatout2_rounds import (
    build_flatout2_current_round_match_specs,
    get_flatout2_current_round_generation_context,
)
from .gen_flatout2_builder_parts import (
    append_manual_flatout2_round_match_specs,
    build_flatout2_builder_round_stage_settings,
    create_flatout2_builder_container_stage,
    Flatout2InitialRoundSource,
    read_manual_flatout2_max_players_per_match,
)
from .models import (
    Participant,
    Stage,
    StageID,
    StageType,
    Tournament,
    TournamentID,
)
from .stage_generation_base import (
    distribute_evenly,
    StageGenerationPayload,
)


def summarize_flatout2_builder_rounds(
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
        match_count = math.ceil(
            current_participant_count / max_players_per_match
        )
        if match_count < 1:
            break

        round_summaries.append(
            _build_flatout2_builder_round_summary(
                round_no, current_participant_count, match_count
            )
        )

        qualified_participant_count = match_count * qualifier_count_per_match
        if _is_last_flatout2_builder_round(
            match_count,
            qualified_participant_count,
            stop_when_participants_at_most,
        ):
            break

        current_participant_count = qualified_participant_count
        round_no += 1

    return round_summaries


def _build_flatout2_builder_round_summary(
    round_no: int, participant_count: int, match_count: int
) -> dict[str, int]:
    heat_sizes = distribute_evenly(participant_count, match_count)
    max_heat_size = max(heat_sizes) if heat_sizes else 0
    return {
        'round_no': round_no,
        'match_count': match_count,
        'max_heat_size': max_heat_size,
    }


def _is_last_flatout2_builder_round(
    match_count: int,
    qualified_participant_count: int,
    stop_when_participants_at_most: int | None,
) -> bool:
    if match_count == 1:
        return True

    return (
        stop_when_participants_at_most is not None
        and qualified_participant_count <= stop_when_participants_at_most
    )


def _build_flatout2_round_stage_display_title(
    round_no: int, total_round_count: int, role: str
) -> str:
    if role == 'preliminary':
        return f'Vorrunde {round_no}'

    if total_round_count > 0 and round_no == total_round_count:
        return 'Finale'

    return f'Runde {round_no}'


def create_flatout2_builder_round_stages(
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
    container_settings, container_stage = (
        create_flatout2_builder_container_stage(
            tournament_id=tournament_id,
            order_no_start=order_no_start,
            container_name=container_name,
            role=role,
            stage_type=stage_type,
            common_settings=common_settings,
            now=now,
        )
    )
    initial_source = Flatout2InitialRoundSource(
        source_mode=initial_source_mode,
        source_stage_ids=initial_source_stage_ids,
        qualifier_top_n=initial_qualifier_top_n,
        qualifier_top_n_per_match=initial_qualifier_top_n_per_match,
    )

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
        round_settings = build_flatout2_builder_round_stage_settings(
            common_settings,
            role=role,
            container_stage_id=container_stage.id,
            round_no=round_no,
            display_title=display_title,
            total_round_count=total_round_count,
            round_summary=round_summary,
            previous_stage_id=previous_stage_id,
            initial_source=initial_source,
        )

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


def build_manual_flatout2_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
) -> Result[StageGenerationPayload, str]:
    settings = stage.settings or {}
    raw_rounds = settings.get('flatout2_rounds')
    if not isinstance(raw_rounds, list) or not raw_rounds:
        return Err('Bitte die FlatOut-2-Phase zuerst vorbereiten.')

    max_players_per_match_result = read_manual_flatout2_max_players_per_match(
        settings
    )
    if max_players_per_match_result.is_err():
        return Err(max_players_per_match_result.unwrap_err())
    max_players_per_match = max_players_per_match_result.unwrap()

    raw_match_blueprints = _get_flatout2_match_blueprints(settings)

    match_specs: list[MatchSpec] = []
    round_error = _append_manual_flatout2_match_specs(
        raw_rounds,
        raw_match_blueprints=raw_match_blueprints,
        max_players_per_match=max_players_per_match,
        match_specs=match_specs,
    )
    if round_error is not None:
        return Err(round_error)

    if not match_specs:
        return Err('Bitte mindestens ein FlatOut-2-Match konfigurieren.')

    return Ok(
        StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=[],
            match_specs=match_specs,
            replace_existing_matches=True,
        )
    )


def _get_flatout2_match_blueprints(settings: dict[str, Any]) -> dict[str, Any]:
    raw_match_blueprints = settings.get('flatout2_match_blueprints')
    if not isinstance(raw_match_blueprints, dict):
        raw_match_blueprints = {}
    return raw_match_blueprints


def _append_manual_flatout2_match_specs(
    raw_rounds: list[Any],
    *,
    raw_match_blueprints: dict[str, Any],
    max_players_per_match: int,
    match_specs: list[MatchSpec],
) -> str | None:
    seen_match_nos: set[int] = set()

    for raw_round in raw_rounds:
        if not isinstance(raw_round, dict):
            continue

        round_error = append_manual_flatout2_round_match_specs(
            raw_round,
            raw_match_blueprints=raw_match_blueprints,
            max_players_per_match=max_players_per_match,
            match_specs=match_specs,
            seen_match_nos=seen_match_nos,
        )
        if round_error is not None:
            return round_error

    return None


def build_flatout2_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
    tournament_id: TournamentID,
    require_hosts: bool,
) -> Result[StageGenerationPayload, str]:
    context_result = get_flatout2_current_round_generation_context(
        tournament_id=tournament_id,
        stage=stage,
        engine=engine,
        participants=participants,
    )
    if context_result.is_err():
        return Err(context_result.unwrap_err())

    context = context_result.unwrap()
    if require_hosts:
        match_specs_result = build_flatout2_current_round_match_specs(
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
        StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=context.participants,
            match_specs=match_specs,
            replace_existing_matches=context.replace_existing_matches,
        )
    )
