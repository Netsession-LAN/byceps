"""
byceps.services.netsession_tourney.stage_generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match generation of a stage: payload and preview (round titles, pairings).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from .checkin_service import check_generation_allowed
from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .engines.base import StageEngine
from .engines.registry import (
    find_stage_engine,
    get_stage_type_spec,
)
from .flatout2_builder import (
    build_flatout2_stage_generation_payload,
    build_manual_flatout2_stage_generation_payload,
)
from .gen_preview_titles import (
    build_generation_preview_round_titles_by_round_no,
)
from .generation_participants import (
    order_participants_for_stage_generation,
    select_generation_participants_for_stage,
    StageMatchGenerationPreviewParticipant,
)
from .match_schedule import (
    build_round_starts_at_schedule,
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
from .registration_validation import (
    validate_bracket_ready_team_sizes,
)
from .service_helpers import (
    db_stage_to_model,
    db_tournament_to_model,
)
from .stage_builder_preview import (
    resolve_stage_builder_stage_for_generation,
)
from .stage_generation_base import (
    StageGenerationPayload,
)
from .swiss_stage import (
    build_swiss_stage_generation_payload,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)


@dataclass(frozen=True, kw_only=True)
class StageRoundGenerationPreview:
    round_no: int
    match_count: int
    suggested_starts_at: datetime | None
    display_title: str | None = None


@dataclass(frozen=True, kw_only=True)
class StageGeneratedMatchPreview:
    round_no: int
    match_no: int
    participants: list[StageMatchGenerationPreviewParticipant]


@dataclass(frozen=True, kw_only=True)
class StageMatchGenerationPreview:
    stage: Stage
    participant_count: int
    match_count: int
    rounds: list[StageRoundGenerationPreview]
    matches_by_round_no: dict[int, list[StageGeneratedMatchPreview]]


def preview_stage_match_generation(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
) -> Result[StageMatchGenerationPreview, str]:
    payload_result = build_stage_generation_payload(
        party_id,
        tournament_id,
        stage_id,
        require_flatout2_hosts=False,
    )
    if payload_result.is_err():
        return Err(payload_result.unwrap_err())
    payload = payload_result.unwrap()

    round_match_counts: dict[int, int] = defaultdict(int)
    for spec in payload.match_specs:
        round_match_counts[spec.round_no] += 1

    suggested_round_starts_at = build_round_starts_at_schedule(
        tournament_starts_at=payload.tournament.starts_at,
        stage=payload.stage,
        round_match_counts=round_match_counts,
    )
    display_titles_by_round_no = (
        build_generation_preview_round_titles_by_round_no(
            payload.stage,
            payload.match_specs,
        )
    )
    preview_participants_by_id = {
        participant.id: participant for participant in payload.participants
    }
    matches_by_round_no: dict[int, list[StageGeneratedMatchPreview]] = (
        defaultdict(list)
    )
    for spec in sorted(
        payload.match_specs, key=lambda item: (item.round_no, item.match_no)
    ):
        matches_by_round_no[spec.round_no].append(
            StageGeneratedMatchPreview(
                round_no=spec.round_no,
                match_no=spec.match_no,
                participants=[
                    StageMatchGenerationPreviewParticipant(
                        participant_id=slot.participant_id,
                        name=preview_participants_by_id[
                            slot.participant_id
                        ].name,
                    )
                    for slot in spec.slots
                    if slot.participant_id is not None
                    and slot.participant_id in preview_participants_by_id
                ],
            )
        )
    rounds = [
        StageRoundGenerationPreview(
            round_no=round_no,
            match_count=round_match_counts[round_no],
            suggested_starts_at=suggested_round_starts_at.get(round_no),
            display_title=display_titles_by_round_no.get(round_no),
        )
        for round_no in sorted(round_match_counts.keys())
    ]

    return Ok(
        StageMatchGenerationPreview(
            stage=payload.stage,
            participant_count=len(payload.participants),
            match_count=len(payload.match_specs),
            rounds=rounds,
            matches_by_round_no=dict(matches_by_round_no),
        )
    )


@dataclass(frozen=True, kw_only=True)
class _StageGenerationSetup:
    tournament: Tournament
    stage: Stage
    engine: StageEngine


def build_stage_generation_payload(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    *,
    stage_settings_override: dict[str, Any] | None = None,
    require_flatout2_hosts: bool = True,
) -> Result[StageGenerationPayload, str]:
    setup_result = _load_stage_generation_setup(
        party_id,
        tournament_id,
        stage_id,
        stage_settings_override=stage_settings_override,
    )
    if setup_result.is_err():
        return Err(setup_result.unwrap_err())
    setup = setup_result.unwrap()
    tournament = setup.tournament
    stage = setup.stage
    engine = setup.engine

    ordered_participants_result = _select_ordered_generation_participants(
        party_id, tournament_id, tournament, stage
    )
    if ordered_participants_result.is_err():
        return Err(ordered_participants_result.unwrap_err())
    ordered_participants = ordered_participants_result.unwrap()

    participant_ids = [participant.id for participant in ordered_participants]
    resolved_stage_result = resolve_stage_builder_stage_for_generation(
        stage,
        participant_count=len(participant_ids),
    )
    if resolved_stage_result.is_err():
        return Err(resolved_stage_result.unwrap_err())
    stage = resolved_stage_result.unwrap()

    if stage.type == StageType.ffa_flatout2_single_elimination and (
        (stage.settings or {}).get('flatout2_manual_stage')
        or not (stage.settings or {}).get('builder_kind')
    ):
        return build_manual_flatout2_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
        )

    return _generate_stage_generation_payload(
        tournament=tournament,
        stage=stage,
        engine=engine,
        ordered_participants=ordered_participants,
        participant_ids=participant_ids,
        tournament_id=tournament_id,
        require_flatout2_hosts=require_flatout2_hosts,
    )


def _load_stage_generation_setup(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    *,
    stage_settings_override: dict[str, Any] | None,
) -> Result[_StageGenerationSetup, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Phase.')

    stage = db_stage_to_model(db_stage)
    if stage_settings_override:
        merged_stage_settings = dict(stage.settings or {})
        merged_stage_settings.update(stage_settings_override)
        stage = replace(stage, settings=merged_stage_settings)
    tournament = db_tournament_to_model(db_tournament)
    stage_type_spec = get_stage_type_spec(stage.type)
    if not stage_type_spec.enabled:
        return Err('Dieser Phasentyp ist zurzeit deaktiviert.')

    engine = find_stage_engine(stage.type)
    if engine is None:
        return Err('Für diesen Phasentyp gibt es noch keine Match-Erzeugung.')

    return Ok(
        _StageGenerationSetup(tournament=tournament, stage=stage, engine=engine)
    )


def _select_ordered_generation_participants(
    party_id: PartyID,
    tournament_id: TournamentID,
    tournament: Tournament,
    stage: Stage,
) -> Result[list[Participant], str]:
    checkin_error = check_generation_allowed(tournament)
    if checkin_error is not None:
        return Err(checkin_error)

    selected_participants_result = select_generation_participants_for_stage(
        party_id,
        tournament_id,
        stage,
    )
    if selected_participants_result.is_err():
        return Err(selected_participants_result.unwrap_err())
    participants = selected_participants_result.unwrap()

    team_size_validation_result = validate_bracket_ready_team_sizes(
        tournament, participants
    )
    if team_size_validation_result.is_err():
        return Err(team_size_validation_result.unwrap_err())

    ordered_participants = order_participants_for_stage_generation(
        participants,
        shuffle_unseeded=(
            (stage.settings or {}).get('participant_source_mode')
            not in {
                'stage_qualifiers',
                'stage_match_qualifiers',
                'builder_fixed_participants',
            }
        ),
    )
    return Ok(ordered_participants)


def _generate_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
    ordered_participants: list[Participant],
    participant_ids: list[ParticipantID],
    tournament_id: TournamentID,
    require_flatout2_hosts: bool,
) -> Result[StageGenerationPayload, str]:
    validation_result = engine.validate(stage, participant_ids)
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    if stage.type == StageType.ffa_flatout2_single_elimination:
        return build_flatout2_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            tournament_id=tournament_id,
            require_hosts=require_flatout2_hosts,
        )

    if stage.type == StageType.swiss:
        return build_swiss_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            tournament_id=tournament_id,
        )

    generation_result = engine.generate(stage, participant_ids)
    if generation_result.is_err():
        return Err(generation_result.unwrap_err())

    return Ok(
        StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            match_specs=generation_result.unwrap(),
        )
    )
