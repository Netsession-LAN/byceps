"""
byceps.services.netsession_tourney.result_deletion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Deleting stored results (with the matches that depend on them) and disputes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyResultReportReceipt,
    DbNetsessionTourneyStage,
)
from .models import (
    Match,
    MatchID,
    MatchState,
    StageType,
    TournamentID,
)
from .notification_service import (
    append_notifications_for_match,
)
from .participant_state import (
    calculate_match_state_for_slots,
    get_tournament_status_value,
)
from .service_helpers import (
    append_audit_log,
    db_match_to_model,
    db_stage_to_model,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)
from .site_paths import (
    build_site_match_path,
)


log = structlog.get_logger()


def delete_match_result_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    initiator: User,
) -> Result[None, str]:
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
    if db_stage is None:
        return Err('Unbekannte Stage.')

    stage = db_stage_to_model(db_stage)
    if stage.type == StageType.swiss:
        return Err(
            'Bei Swiss lassen sich gespeicherte Ergebnisse noch nicht löschen.'
        )

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult)
        .filter_by(match_id=match_id)
        .with_for_update()
    )
    if db_result is None:
        return Err('Für dieses Match ist kein Ergebnis gespeichert.')

    blocking_match_id = find_match_result_delete_blocker(match_id)
    if blocking_match_id is not None:
        db_blocking_match = db.session.get(
            DbNetsessionTourneyMatch, blocking_match_id
        )
        if db_blocking_match is None:
            return Err(
                'Das Ergebnis lässt sich nicht löschen, weil ein Folge-Match schon ein gemeldetes Ergebnis hat.'
            )

        return Err(
            'Das Ergebnis lässt sich nicht löschen, weil ein Folge-Match '
            f'(Runde {db_blocking_match.round_no}, Match {db_blocking_match.match_no}) '
            'schon ein gemeldetes Ergebnis hat.'
        )

    deleted_match_ids: set[MatchID] = set()
    _delete_match_result_branch(match_id, deleted_match_ids=deleted_match_ids)

    now = datetime.utcnow()
    append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='result_deleted',
        payload={
            'deleted_match_ids': [str(item) for item in sorted(deleted_match_ids)],
            'deleted_match_count': len(deleted_match_ids),
        },
        created_at=now,
    )
    db.session.commit()

    return Ok(None)


def find_match_result_delete_blocker(
    match_id: MatchID, *, visited: set[MatchID] | None = None
) -> MatchID | None:
    if visited is None:
        visited = set()

    source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id, slot_no=1)
    )
    if source_slot is None:
        return None

    downstream_match_ids = {
        downstream_match_id
        for downstream_match_id in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot.match_id).filter_by(
                source_match_slot_id=source_slot.id
            )
        ).all()
    }

    for downstream_match_id in sorted(downstream_match_ids):
        if downstream_match_id in visited:
            continue

        visited.add(downstream_match_id)
        db_result = db.session.scalar(
            select(DbNetsessionTourneyMatchResult).filter_by(
                match_id=downstream_match_id
            )
        )
        if db_result is None:
            continue

        if db_result.submitted_by_user_id is not None:
            return downstream_match_id

        blocking_match_id = find_match_result_delete_blocker(
            downstream_match_id, visited=visited
        )
        if blocking_match_id is not None:
            return blocking_match_id

    return None


def _delete_match_result_branch(
    match_id: MatchID,
    *,
    deleted_match_ids: set[MatchID],
    visited: set[MatchID] | None = None,
) -> None:
    if visited is None:
        visited = set()

    if match_id in visited:
        return

    visited.add(match_id)

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id)
        .with_for_update()
    )
    if db_match is None:
        return

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult)
        .filter_by(match_id=match_id)
        .with_for_update()
    )
    if db_result is None:
        return

    downstream_slots = _get_downstream_slots(match_id)
    downstream_match_ids = sorted({db_slot.match_id for db_slot in downstream_slots})

    for downstream_match_id in downstream_match_ids:
        db_downstream_result = db.session.scalar(
            select(DbNetsessionTourneyMatchResult)
            .filter_by(match_id=downstream_match_id)
            .with_for_update()
        )
        if db_downstream_result is None:
            continue

        _delete_match_result_branch(
            downstream_match_id,
            deleted_match_ids=deleted_match_ids,
            visited=visited,
        )

    db.session.execute(
        delete(DbNetsessionTourneyResultReportReceipt).filter_by(match_id=match_id)
    )
    db.session.delete(db_result)
    _reset_match_after_result_delete(db_match)

    _clear_downstream_slots(downstream_slots)

    deleted_match_ids.add(match_id)


def _get_downstream_slots(
    match_id: MatchID,
) -> list[DbNetsessionTourneyMatchSlot]:
    """Return the slots that are fed by the match's results."""
    source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id, slot_no=1)
    )
    return (
        db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(
                source_match_slot_id=source_slot.id
            )
        ).all()
        if source_slot is not None
        else []
    )


def _clear_downstream_slots(
    downstream_slots: list[DbNetsessionTourneyMatchSlot],
) -> None:
    """Remove the participants from the downstream slots and reset the
    affected matches."""
    affected_downstream_match_ids: set[MatchID] = set()
    for db_slot in downstream_slots:
        if db_slot.participant_id is not None:
            db_slot.participant_id = None
        affected_downstream_match_ids.add(db_slot.match_id)

    for downstream_match_id in affected_downstream_match_ids:
        db_downstream_match = db.session.scalar(
            select(DbNetsessionTourneyMatch)
            .filter_by(id=downstream_match_id)
            .with_for_update()
        )
        if db_downstream_match is None:
            continue

        _reset_match_after_result_delete(db_downstream_match)


def _reset_match_after_result_delete(db_match: DbNetsessionTourneyMatch) -> None:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=db_match.id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()

    db_match.state = calculate_match_state_for_slots(
        tournament_status=get_tournament_status_value(db_match.tournament_id),
        db_match_slots=db_slots,
    ).value

    db_match.reported_by_user_id = None
    db_match.confirmed_by_admin_id = None
    db_match.confirmation_deadline_at = None
    db_match.dispute_reason_code = None
    db_match.dispute_comment = None
    db_match.updated_at = datetime.utcnow()
    db_match.lock_version += 1


DISPUTABLE_MATCH_STATES = frozenset(
    state.value
    for state in (
        MatchState.ready,
        MatchState.in_progress,
        MatchState.pending_confirmation,
        MatchState.needs_admin_review,
    )
)


def open_match_dispute(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    initiator: User,
    *,
    reason_code: str,
    comment: str,
    correlation_id: str | None = None,
) -> Result[Match, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    reason_code = reason_code.strip()
    comment = comment.strip()
    if not reason_code:
        return Err('Bitte einen Grund angeben.')
    if not comment:
        return Err('Bitte einen Kommentar angeben.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch).filter_by(
            id=match_id, tournament_id=tournament_id
        )
    )
    if db_match is None:
        return Err('Unbekanntes Match.')
    if db_match.state not in DISPUTABLE_MATCH_STATES:
        return Err(
            'Ein Streitfall ist nur bei offenen Matches möglich. Ein '
            'abgeschlossenes Ergebnis lässt sich korrigieren.'
        )

    db_match.state = MatchState.disputed.value
    db_match.dispute_reason_code = reason_code
    db_match.dispute_comment = comment
    db_match.updated_at = datetime.utcnow()

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='match_disputed',
        payload={
            'reason_code': reason_code,
            'comment': comment,
            'correlation_id': correlation_id,
        },
        created_at=datetime.utcnow(),
    )

    append_notifications_for_match(
        db_match,
        actor_user_id=initiator.id,
        kind='dispute_opened',
        payload={
            'match_id': str(db_match.id),
            'reason_code': reason_code,
            'url': build_site_match_path(db_tournament.slug, db_match.id),
        },
    )

    db.session.commit()

    log.info(
        'netsession_tourney.match_disputed',
        tournament_id=str(tournament_id),
        match_id=str(match_id),
        actor_user_id=str(initiator.id),
        reason_code=reason_code,
        correlation_id=correlation_id,
    )

    return Ok(db_match_to_model(db_match))
