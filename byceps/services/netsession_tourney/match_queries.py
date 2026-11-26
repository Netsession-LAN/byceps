"""
byceps.services.netsession_tourney.match_queries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Matches, their slots and timeline (read-only).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import or_, select

from byceps.database import db
from byceps.services.party.models import PartyID

from .dbmodels import (
    DbNetsessionTourneyAuditLog,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyTournament,
)
from .models import (
    Match,
    MatchID,
    MatchSlot,
    MatchState,
    ParticipantID,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    calculate_match_state_for_slots,
    get_participant_status_value_by_participant_id_for_slots,
)
from .service_helpers import (
    db_match_slot_to_model,
    db_match_to_model,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)


def get_matches_for_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    only_open: bool = False,
) -> list[Match]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return []

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()

    match_ids = [db_match.id for db_match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id = _group_tournament_slots_by_match_id(db_slots)

    participant_status_value_by_participant_id = (
        get_participant_status_value_by_participant_id_for_slots(db_slots)
    )

    matches = [
        _db_match_to_model_with_effective_state(
            item,
            tournament_status=db_tournament.status,
            db_match_slots=slots_by_match_id.get(item.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        )
        for item in db_matches
    ]
    if only_open:
        matches = _select_open_tournament_matches(matches)

    return matches


def _group_tournament_slots_by_match_id(
    db_slots: Sequence[DbNetsessionTourneyMatchSlot],
) -> dict[MatchID, list[DbNetsessionTourneyMatchSlot]]:
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)
    return slots_by_match_id


def _select_open_tournament_matches(matches: list[Match]) -> list[Match]:
    return [
        match
        for match in matches
        if match.state
        in {
            MatchState.ready,
            MatchState.in_progress,
            MatchState.pending_confirmation,
            MatchState.needs_admin_review,
        }
    ]


def get_open_matches_for_party(party_id: PartyID) -> list[Match]:
    stmt = (
        select(DbNetsessionTourneyMatch)
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyMatch.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(
            DbNetsessionTourneyTournament.status == TournamentStatus.live.value
        )
        .filter(
            DbNetsessionTourneyMatch.state.in_(
                [
                    MatchState.ready.value,
                    MatchState.in_progress.value,
                    MatchState.pending_confirmation.value,
                    MatchState.needs_admin_review.value,
                ]
            )
        )
        .order_by(DbNetsessionTourneyMatch.scheduled_at.asc().nullslast())
    )
    db_matches = db.session.scalars(stmt).all()
    if not db_matches:
        return []

    match_ids = [db_match.id for db_match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        get_participant_status_value_by_participant_id_for_slots(db_slots)
    )

    return [
        match
        for match in (
            _db_match_to_model_with_effective_state(
                db_match,
                tournament_status=TournamentStatus.live.value,
                db_match_slots=slots_by_match_id.get(db_match.id, []),
                participant_status_value_by_participant_id=participant_status_value_by_participant_id,
            )
            for db_match in db_matches
        )
        if match.state
        in {
            MatchState.ready,
            MatchState.in_progress,
            MatchState.pending_confirmation,
            MatchState.needs_admin_review,
        }
    ]


def find_match_for_tournament(
    party_id: PartyID, tournament_id: TournamentID, match_id: MatchID
) -> Match | None:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return None

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch).filter_by(
            id=match_id,
            tournament_id=tournament_id,
        )
    )
    if db_match is None:
        return None

    db_match_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    participant_status_value_by_participant_id = (
        get_participant_status_value_by_participant_id_for_slots(db_match_slots)
    )

    return _db_match_to_model_with_effective_state(
        db_match,
        tournament_status=db_tournament.status,
        db_match_slots=db_match_slots,
        participant_status_value_by_participant_id=participant_status_value_by_participant_id,
    )


def get_match_slots_for_match(match_id: MatchID) -> list[MatchSlot]:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    return [db_match_slot_to_model(item) for item in db_slots]


def get_match_timeline_entries(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
) -> list[dict[str, Any]]:
    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return []

    db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
    if db_match is None:
        return []

    # Tournament events only from the match's lifetime: "tournament is
    # live" usually happened before the match existed.
    db_entries = db.session.scalars(
        select(DbNetsessionTourneyAuditLog)
        .filter(
            or_(
                (
                    (DbNetsessionTourneyAuditLog.object_type == 'match')
                    & (DbNetsessionTourneyAuditLog.object_id == match_id)
                ),
                (
                    (DbNetsessionTourneyAuditLog.object_type == 'tournament')
                    & (DbNetsessionTourneyAuditLog.object_id == tournament_id)
                    & (
                        DbNetsessionTourneyAuditLog.created_at
                        >= db_match.created_at
                    )
                    & DbNetsessionTourneyAuditLog.action.in_(
                        [
                            'tournament_published',
                            'tournament_closed',
                            'tournament_canceled',
                        ]
                    )
                ),
            )
        )
        .order_by(DbNetsessionTourneyAuditLog.created_at.asc())
    ).all()

    return [
        {
            'id': entry.id,
            'actor_user_id': entry.actor_user_id,
            'action': entry.action,
            'payload': dict(entry.payload_json or {}),
            'created_at': entry.created_at,
        }
        for entry in db_entries
        if entry.action != 'chat_message_posted'
    ]


def get_match_slots(match_ids: set[MatchID]) -> dict[MatchID, list[MatchSlot]]:
    if not match_ids:
        return {}

    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[MatchSlot]] = defaultdict(list)
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(
            db_match_slot_to_model(db_slot)
        )
    return dict(slots_by_match_id)


def _db_match_to_model_with_effective_state(
    db_match: DbNetsessionTourneyMatch,
    *,
    tournament_status: str,
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
    participant_status_value_by_participant_id: dict[ParticipantID, str],
) -> Match:
    match = db_match_to_model(db_match)
    if match.state in {MatchState.pending, MatchState.ready}:
        effective_state = calculate_match_state_for_slots(
            tournament_status=tournament_status,
            db_match_slots=db_match_slots,
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        )
        if effective_state != match.state:
            return replace(match, state=effective_state)

    return match
