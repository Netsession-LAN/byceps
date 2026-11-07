"""
byceps.services.netsession_tourney.tournament_queries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Read-only lookups shared by the tournament service modules: tournaments,
stages, participants, site paths, score parsing and FlatOut 2 races.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID

from .dbmodels import (
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTeamMember,
    DbNetsessionTourneyTournament,
)
from .models import (
    Participant,
    ParticipantStatus,
    Stage,
    StageStatus,
    TournamentID,
    TournamentStatus,
)
from .service_helpers import (
    db_participant_to_model,
    db_stage_to_model,
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
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
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
    if find_db_tournament_for_party(party_id, tournament_id) is None:
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
    return [db_participant_to_model(item) for item in db_participants]


def find_db_tournament_for_party(
    party_id: PartyID, tournament_id: TournamentID
) -> DbNetsessionTourneyTournament | None:
    return db.session.scalar(
        select(DbNetsessionTourneyTournament).filter_by(
            id=tournament_id, party_id=party_id
        )
    )


def _db_stage_to_model_with_effective_status(
    db_stage: DbNetsessionTourneyStage, *, tournament_status: str
) -> Stage:
    stage = db_stage_to_model(db_stage)
    if (
        tournament_status == TournamentStatus.draft.value
        and stage.status == StageStatus.live
    ):
        return replace(stage, status=StageStatus.draft)

    return stage


def get_user_active_participation_tournament_ids(
    party_id: PartyID, tournament_ids: set[TournamentID], user_id: UserID
) -> set[TournamentID]:
    if not tournament_ids:
        return set()

    direct_rows = db.session.scalars(
        select(DbNetsessionTourneyParticipant.tournament_id)
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyParticipant.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(DbNetsessionTourneyParticipant.tournament_id.in_(tournament_ids))
        .filter(DbNetsessionTourneyParticipant.user_id == user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()

    team_rows = db.session.scalars(
        select(DbNetsessionTourneyParticipant.tournament_id)
        .join(
            DbNetsessionTourneyTeamMember,
            DbNetsessionTourneyTeamMember.participant_id
            == DbNetsessionTourneyParticipant.id,
        )
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyParticipant.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(DbNetsessionTourneyParticipant.tournament_id.in_(tournament_ids))
        .filter(DbNetsessionTourneyTeamMember.user_id == user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()

    return set(direct_rows).union(team_rows)
