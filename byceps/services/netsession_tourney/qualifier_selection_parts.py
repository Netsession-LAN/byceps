"""
byceps.services.netsession_tourney.qualifier_selection_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Source stages and per-match selection used by the qualifier selection.
"""

from __future__ import annotations

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from .dbmodels import DbNetsessionTourneyStage
from .models import Participant, ParticipantID, Stage, TournamentID
from .participant_admin_service import get_participants_by_ids
from .qualifier_ranking import (
    get_ranked_participant_ids_by_match_for_stage,
)
from .stage_service import parse_source_stage_ids


TOO_FEW_QUALIFIED = (
    'Zu wenige qualifizierte Teilnehmer für diese Phase. '
    'Passe die Quellphasen oder die Top-Anzahl an.'
)


def _get_qualifier_top_n_per_match(stage: Stage) -> Result[int, str]:
    try:
        top_n_per_match = int(
            (stage.settings or {}).get('qualifier_top_n_per_match') or 0
        )
    except TypeError, ValueError:
        top_n_per_match = 0
    if top_n_per_match < 1 or top_n_per_match > 16:
        return Err('Ungültige Top-Anzahl pro Match für die Qualifikation.')
    return Ok(top_n_per_match)


def _select_top_per_match_of_stages(
    db_source_stages: list[DbNetsessionTourneyStage],
    tournament_id: TournamentID,
    top_n_per_match: int,
) -> Result[list[ParticipantID], str]:
    selected_participant_ids: list[ParticipantID] = []
    for db_source_stage in db_source_stages:
        ranked_result = get_ranked_participant_ids_by_match_for_stage(
            db_source_stage.id, tournament_id, top_n_per_match=top_n_per_match
        )
        if ranked_result.is_err():
            return _source_stage_error(
                db_source_stage, ranked_result.unwrap_err()
            )
        selected_participant_ids.extend(ranked_result.unwrap())
    return Ok(selected_participant_ids)


def _require_enough_qualified(
    participants: list[Participant],
) -> Result[list[Participant], str]:
    if len(participants) < 2:
        return Err(TOO_FEW_QUALIFIED)

    return Ok(participants)


def _get_source_stage_ids(stage: Stage) -> Result[list, str]:
    source_stage_ids = parse_source_stage_ids(
        (stage.settings or {}).get('qualifier_source_stage_ids', [])
    )
    if not source_stage_ids:
        return Err(
            'Keine Quellphasen eingestellt. Bitte zuerst die Quellphasen '
            'für die Qualifikation festlegen.'
        )
    if stage.id in source_stage_ids:
        return Err(
            'Eine Phase kann nicht ihre eigene Quelle für Qualifikanten sein.'
        )
    return Ok(source_stage_ids)


def _load_source_stages(
    tournament_id: TournamentID, source_stage_ids: list
) -> Result[list[DbNetsessionTourneyStage], str]:
    unique_source_stage_ids = list(dict.fromkeys(source_stage_ids))
    db_source_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyStage.id.in_(unique_source_stage_ids))
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()
    if len(db_source_stages) != len(unique_source_stage_ids):
        return Err(
            'Mindestens eine der eingestellten Quellphasen existiert nicht.'
        )
    return Ok(list(db_source_stages))


def _source_stage_error(db_source_stage, message: str) -> Err:
    if message.endswith('is not fully completed yet.'):
        message = (
            'ist noch nicht vollständig abgeschlossen. '
            'Schließe zuerst alle Vorrunden-Matches ab.'
        )
    return Err(f'Quellphase „{db_source_stage.name}“: {message}')


def _participants_in_order(
    party_id: PartyID, participant_ids: list[ParticipantID]
) -> list[Participant]:
    participants_by_id = get_participants_by_ids(party_id, set(participant_ids))
    return [
        participants_by_id[participant_id]
        for participant_id in participant_ids
        if participant_id in participants_by_id
    ]
