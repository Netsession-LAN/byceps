"""
byceps.services.netsession_tourney.flatout2_builder_payload
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generation payloads of FlatOut 2 builder round stages (automatic and
manual).
"""

from __future__ import annotations

from typing import Any

from byceps.util.result import Err, Ok, Result

from .engines.base import MatchSpec, SlotSpec, StageEngine
from .flatout2_rounds import (
    build_flatout2_current_round_match_specs,
    get_flatout2_current_round_generation_context,
)
from .gen_flatout2_builder_parts import (
    append_manual_flatout2_round_match_specs,
    read_manual_flatout2_max_players_per_match,
)
from .models import (
    Participant,
    Stage,
    Tournament,
    TournamentID,
)
from .stage_generation_base import (
    StageGenerationPayload,
)


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
