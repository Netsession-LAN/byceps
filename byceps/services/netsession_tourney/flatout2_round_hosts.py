"""
byceps.services.netsession_tourney.flatout2_round_hosts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Setting the host of a FlatOut 2 match by an admin.
"""

from __future__ import annotations

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
from .gen_flatout2_round_parts import (
    apply_flatout2_match_host,
)
from .models import (
    Match,
    MatchID,
    MatchState,
    ParticipantID,
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
from .tournament_queries import (
    find_db_tournament_for_party,
)


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

    match_and_stage_result = _find_flatout2_match_and_stage_for_update(
        tournament_id, match_id
    )
    if match_and_stage_result.is_err():
        return Err(match_and_stage_result.unwrap_err())
    db_match, db_stage = match_and_stage_result.unwrap()

    allowed_participant_ids = _get_match_slot_participant_ids(match_id)

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
            'host_participant_id': _format_optional_participant_id(
                host_participant_id
            ),
        },
        created_at=datetime.utcnow(),
    )

    if _should_notify_flatout2_host_assignment(
        db_tournament,
        db_match,
        host_participant_id,
        previous_host_participant_id,
    ):
        enqueue_flatout2_host_assignment_notifications(db_match)

    db.session.commit()
    return Ok(db_match_to_model(db_match))


def _find_flatout2_match_and_stage_for_update(
    tournament_id: TournamentID, match_id: MatchID
) -> Result[tuple[DbNetsessionTourneyMatch, DbNetsessionTourneyStage], str]:
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

    return Ok((db_match, db_stage))


def _get_match_slot_participant_ids(match_id: MatchID) -> set[ParticipantID]:
    return {
        slot.participant_id
        for slot in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
        ).all()
        if slot.participant_id is not None
    }


def _format_optional_participant_id(
    participant_id: ParticipantID | None,
) -> str | None:
    return str(participant_id) if participant_id is not None else None


def _should_notify_flatout2_host_assignment(
    db_tournament,
    db_match: DbNetsessionTourneyMatch,
    host_participant_id: ParticipantID | None,
    previous_host_participant_id: ParticipantID | None,
) -> bool:
    return (
        host_participant_id is not None
        and str(host_participant_id) != str(previous_host_participant_id or '')
        and db_tournament.status == TournamentStatus.live.value
        and db_match.state == MatchState.ready.value
    )
