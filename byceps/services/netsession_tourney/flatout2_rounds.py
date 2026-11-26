"""
byceps.services.netsession_tourney.flatout2_rounds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2: matches of the current round and the host of a match.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyStage,
)
from .engines.base import MatchSpec, StageEngine
from .gen_flatout2_round_parts import (
    apply_flatout2_match_host,
    build_flatout2_host_match_spec,
    build_flatout2_materialized_round_context,
    Flatout2CurrentRoundGenerationContext,
    get_flatout2_qualified_participants,
    get_flatout2_round_host_participant_ids,
    get_flatout2_stage_db_matches,
)
from .models import (
    Match,
    MatchID,
    MatchState,
    Participant,
    ParticipantID,
    Stage,
    StageType,
    TournamentID,
    TournamentStatus,
)
from .notification_service import (
    enqueue_flatout2_host_assignment_notifications,
)
from .service_helpers import (
    append_audit_log,
    db_match_to_model,
)
from .stage_generation_base import (
    distribute_evenly,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)


def get_flatout2_current_round_generation_context(
    *,
    tournament_id: TournamentID,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
) -> Result[Flatout2CurrentRoundGenerationContext, str]:
    participant_ids = [participant.id for participant in participants]
    full_generation_result = engine.generate(stage, participant_ids)
    if full_generation_result.is_err():
        return Err(full_generation_result.unwrap_err())

    full_specs = full_generation_result.unwrap()
    if not full_specs:
        return Err(
            'Für diese FlatOut-2-Phase konnten keine Runden berechnet werden.'
        )

    if (stage.settings or {}).get('builder_materialized_round_stage'):
        return Ok(
            build_flatout2_materialized_round_context(
                stage, full_specs, participants
            )
        )

    planned_match_nos_by_round_no: dict[int, list[int]] = defaultdict(list)
    for spec in full_specs:
        planned_match_nos_by_round_no[spec.round_no].append(spec.match_no)

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

    if any(match.state != MatchState.completed.value for match in db_matches):
        return Err(
            'Die aktuell generierte FlatOut-2-Runde ist noch nicht abgeschlossen.'
        )

    highest_generated_round_no = max(match.round_no for match in db_matches)
    next_round_no = highest_generated_round_no + 1
    if next_round_no > total_round_count:
        return Err('Alle FlatOut-2-Runden sind bereits generiert.')

    previous_round_matches = [
        match
        for match in db_matches
        if match.round_no == highest_generated_round_no
    ]
    qualified_participants = get_flatout2_qualified_participants(
        previous_round_matches, participants
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


def set_flatout2_match_host_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    host_participant_id: ParticipantID | None,
    initiator: User,
) -> Result[Match, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id, tournament_id=tournament_id)
        .with_for_update()
    )
    if db_match is None:
        return Err('Unbekanntes Match.')

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if (
        db_stage is None
        or db_stage.type != StageType.ffa_flatout2_single_elimination.value
    ):
        return Err('Dieses Match gehört zu keiner FlatOut-2-Phase.')

    allowed_participant_ids = {
        slot.participant_id
        for slot in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
        ).all()
        if slot.participant_id is not None
    }

    if (
        host_participant_id is not None
        and host_participant_id not in allowed_participant_ids
    ):
        return Err('Der gewählte Host spielt nicht in diesem Match.')

    previous_host_participant_id = apply_flatout2_match_host(
        db_match, db_stage, host_participant_id
    )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='flatout2_match_host_updated_by_admin',
        payload={
            'host_participant_id': (
                str(host_participant_id)
                if host_participant_id is not None
                else None
            ),
        },
        created_at=datetime.utcnow(),
    )

    should_notify = (
        host_participant_id is not None
        and str(host_participant_id) != str(previous_host_participant_id or '')
        and db_tournament.status == TournamentStatus.live.value
        and db_match.state == MatchState.ready.value
    )

    if should_notify:
        enqueue_flatout2_host_assignment_notifications(db_match)

    db.session.commit()
    return Ok(db_match_to_model(db_match))
