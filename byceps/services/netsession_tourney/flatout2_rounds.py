"""
byceps.services.netsession_tourney.flatout2_rounds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2: matches of the current round and the host of a match.
"""

from __future__ import annotations

from collections import defaultdict

from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
)
from .engines.base import MatchSpec, StageEngine
from .flatout2_round_hosts import (
    set_flatout2_match_host_by_admin as set_flatout2_match_host_by_admin,
)
from .gen_flatout2_round_parts import (
    build_flatout2_host_match_spec,
    build_flatout2_materialized_round_context,
    Flatout2CurrentRoundGenerationContext,
    get_flatout2_qualified_participants,
    get_flatout2_round_host_participant_ids,
    get_flatout2_stage_db_matches,
)
from .models import (
    MatchState,
    Participant,
    Stage,
    TournamentID,
)
from .stage_generation_base import (
    distribute_evenly,
)


def get_flatout2_current_round_generation_context(
    *,
    tournament_id: TournamentID,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
) -> Result[Flatout2CurrentRoundGenerationContext, str]:
    full_specs_result = _generate_flatout2_full_specs(
        stage, engine, participants
    )
    if full_specs_result.is_err():
        return Err(full_specs_result.unwrap_err())
    full_specs = full_specs_result.unwrap()

    if (stage.settings or {}).get('builder_materialized_round_stage'):
        return Ok(
            build_flatout2_materialized_round_context(
                stage, full_specs, participants
            )
        )

    planned_match_nos_by_round_no = _group_planned_match_nos_by_round_no(
        full_specs
    )
    total_round_count = max(planned_match_nos_by_round_no.keys())
    db_matches = get_flatout2_stage_db_matches(tournament_id, stage.id)

    if not db_matches:
        return Ok(
            Flatout2CurrentRoundGenerationContext(
                current_round_no=1,
                total_round_count=total_round_count,
                match_nos=planned_match_nos_by_round_no.get(1, []),
                participants=participants,
                replace_existing_matches=True,
            )
        )

    return _build_flatout2_next_round_context(
        db_matches,
        planned_match_nos_by_round_no,
        total_round_count,
        participants,
    )


def _generate_flatout2_full_specs(
    stage: Stage, engine: StageEngine, participants: list[Participant]
) -> Result[list[MatchSpec], str]:
    participant_ids = [participant.id for participant in participants]
    full_generation_result = engine.generate(stage, participant_ids)
    if full_generation_result.is_err():
        return Err(full_generation_result.unwrap_err())

    full_specs = full_generation_result.unwrap()
    if not full_specs:
        return Err(
            'Für diese FlatOut-2-Phase konnten keine Runden berechnet werden.'
        )

    return Ok(full_specs)


def _group_planned_match_nos_by_round_no(
    full_specs: list[MatchSpec],
) -> dict[int, list[int]]:
    planned_match_nos_by_round_no: dict[int, list[int]] = defaultdict(list)
    for spec in full_specs:
        planned_match_nos_by_round_no[spec.round_no].append(spec.match_no)
    return planned_match_nos_by_round_no


def _build_flatout2_next_round_context(
    db_matches: list[DbNetsessionTourneyMatch],
    planned_match_nos_by_round_no: dict[int, list[int]],
    total_round_count: int,
    participants: list[Participant],
) -> Result[Flatout2CurrentRoundGenerationContext, str]:
    next_round_no_result = _get_flatout2_next_round_no(
        db_matches, total_round_count
    )
    if next_round_no_result.is_err():
        return Err(next_round_no_result.unwrap_err())
    next_round_no = next_round_no_result.unwrap()

    qualified_participants = _get_flatout2_round_qualified_participants(
        db_matches, next_round_no - 1, participants
    )
    if len(qualified_participants) < 2:
        return Err(
            'Es stehen noch nicht genug Qualifikanten für die nächste FlatOut-2-Runde fest.'
        )

    return Ok(
        Flatout2CurrentRoundGenerationContext(
            current_round_no=next_round_no,
            total_round_count=total_round_count,
            match_nos=planned_match_nos_by_round_no.get(next_round_no, []),
            participants=qualified_participants,
            replace_existing_matches=False,
        )
    )


def _get_flatout2_next_round_no(
    db_matches: list[DbNetsessionTourneyMatch], total_round_count: int
) -> Result[int, str]:
    if any(match.state != MatchState.completed.value for match in db_matches):
        return Err(
            'Die aktuell generierte FlatOut-2-Runde ist noch nicht abgeschlossen.'
        )

    highest_generated_round_no = max(match.round_no for match in db_matches)
    next_round_no = highest_generated_round_no + 1
    if next_round_no > total_round_count:
        return Err('Alle FlatOut-2-Runden sind bereits generiert.')

    return Ok(next_round_no)


def _get_flatout2_round_qualified_participants(
    db_matches: list[DbNetsessionTourneyMatch],
    round_no: int,
    participants: list[Participant],
) -> list[Participant]:
    previous_round_matches = [
        match for match in db_matches if match.round_no == round_no
    ]
    return get_flatout2_qualified_participants(
        previous_round_matches, participants
    )


def build_flatout2_current_round_match_specs(
    *,
    stage: Stage,
    context: Flatout2CurrentRoundGenerationContext,
) -> Result[list[MatchSpec], str]:
    host_participant_ids_result = get_flatout2_round_host_participant_ids(
        stage, context
    )
    if host_participant_ids_result.is_err():
        return Err(host_participant_ids_result.unwrap_err())
    host_participant_ids = host_participant_ids_result.unwrap()

    ordered_participant_ids = [
        participant.id for participant in context.participants
    ]
    host_participant_id_set = set(host_participant_ids)
    remaining_participant_ids = [
        participant_id
        for participant_id in ordered_participant_ids
        if participant_id not in host_participant_id_set
    ]
    additional_sizes = distribute_evenly(
        len(remaining_participant_ids), len(host_participant_ids)
    )

    specs: list[MatchSpec] = []
    offset = 0
    for index, match_no in enumerate(context.match_nos):
        host_participant_id = host_participant_ids[index]
        additional_count = additional_sizes[index]
        participant_ids_for_match = [host_participant_id]
        participant_ids_for_match.extend(
            remaining_participant_ids[offset : offset + additional_count]
        )
        offset += additional_count

        specs.append(
            build_flatout2_host_match_spec(
                context.current_round_no, match_no, participant_ids_for_match
            )
        )

    return Ok(specs)
