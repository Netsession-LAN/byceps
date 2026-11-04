"""
byceps.services.netsession_tourney.generation_participants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participants of a stage to generate: from the whole field or qualified from source stages, in seed order.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from uuid import UUID

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .models import (
    Participant,
    ParticipantID,
    Stage,
    StageID,
    TournamentID,
)
from .participant_admin_service import (
    get_participants_by_ids,
)
from .qualifier_ranking import (
    _get_effective_qualifier_top_n_for_source_stage,
    _get_ranked_participant_ids_by_group_for_stage,
    _get_ranked_participant_ids_by_match_for_stage,
)
from .service_helpers import (
    _db_stage_to_model,
)
from .stage_builder_settings import (
    _get_stage_builder_main_stage_size,
    _is_stage_builder_v1_main_stage,
    _is_stage_builder_v1_preliminary_stage,
)
from .stage_ranking import (
    _get_ranked_participant_ids_for_stage,
)
from .stage_service import (
    _parse_source_stage_ids,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
    get_participants_for_tournament,
)


@dataclass(frozen=True, kw_only=True)
class StageMatchGenerationPreviewParticipant:
    participant_id: ParticipantID
    name: str


def get_stage_generation_participants(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
) -> Result[list[Participant], str]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Stage.')

    stage = _db_stage_to_model(db_stage)
    return _select_generation_participants_for_stage(
        party_id, tournament_id, stage
    )


def _order_participants_for_stage_generation(
    participants: list[Participant],
    *,
    shuffle_unseeded: bool,
) -> list[Participant]:
    participant_count = len(participants)
    if participant_count <= 1:
        return participants

    contiguous_seeded: list[Participant] = []
    deferred_unseeded: list[Participant] = []
    seen_seeds: set[int] = set()
    expected_seed = 1

    for participant in sorted(
        participants,
        key=lambda item: (
            item.seed if item.seed is not None else 999_999,
            item.name.lower(),
            str(item.id),
        ),
    ):
        seed = participant.seed
        if (
            seed is None
            or seed < 1
            or seed > participant_count
            or seed in seen_seeds
            or seed != expected_seed
        ):
            deferred_unseeded.append(participant)
            continue

        contiguous_seeded.append(participant)
        seen_seeds.add(seed)
        expected_seed += 1

    if shuffle_unseeded:
        random.shuffle(deferred_unseeded)
    return contiguous_seeded + deferred_unseeded


def _select_generation_participants_for_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage: Stage,
) -> Result[list[Participant], str]:
    all_tournament_participants = get_participants_for_tournament(
        party_id, tournament_id
    )
    is_stage_builder_v1_stage = _is_stage_builder_v1_main_stage(
        stage
    ) or _is_stage_builder_v1_preliminary_stage(stage)
    eligible_participants = (
        domain_service.select_ready_participants(all_tournament_participants)
        if is_stage_builder_v1_stage
        else domain_service.select_bracket_ready_participants(
            all_tournament_participants
        )
    )
    builder_main_stage_size = _get_stage_builder_main_stage_size(stage)
    if (
        _is_stage_builder_v1_main_stage(stage)
        and builder_main_stage_size is not None
    ):
        if (
            stage.settings.get('builder_preliminary_stage_id')
            and len(eligible_participants) <= builder_main_stage_size
        ):
            return Ok(eligible_participants)
        if (
            not stage.settings.get('builder_preliminary_stage_id')
            and len(eligible_participants) > builder_main_stage_size
        ):
            return Err(
                'Die aktuelle Anzahl ready Teilnehmer überschreitet die konfigurierte Main Stage Größe. '
                'Aktiviere eine Vorrunde oder reduziere die Teilnehmerbasis.'
            )

    source_mode = (stage.settings or {}).get('participant_source_mode')
    if source_mode == 'builder_fixed_participants':
        fixed_participant_ids: list[ParticipantID] = []
        for raw_participant_id in (stage.settings or {}).get(
            'builder_fixed_participant_ids', []
        ):
            try:
                fixed_participant_ids.append(
                    ParticipantID(UUID(str(raw_participant_id)))
                )
            except ValueError:
                continue

        if not fixed_participant_ids:
            return Err('Builder-Gruppen-Teilnehmerliste ist leer.')

        ready_participants = domain_service.select_ready_participants(
            all_tournament_participants
        )
        ready_participants_by_id = {
            participant.id: participant for participant in ready_participants
        }
        selected_participants = [
            ready_participants_by_id[participant_id]
            for participant_id in fixed_participant_ids
            if participant_id in ready_participants_by_id
        ]
        if len(selected_participants) < 2:
            return Err('Zu wenige bereite Teilnehmer für diese Gruppe.')
        return Ok(selected_participants)

    if source_mode == 'stage_match_qualifiers':
        source_stage_ids = _parse_source_stage_ids(
            (stage.settings or {}).get('qualifier_source_stage_ids', [])
        )
        if not source_stage_ids:
            return Err(
                'No source stages configured. Configure qualifier source stages first.'
            )
        if stage.id in source_stage_ids:
            return Err('Eine Stage kann nicht ihre eigene Quelle für Qualifikanten sein.')

        try:
            top_n_per_match = int(
                (stage.settings or {}).get('qualifier_top_n_per_match') or 0
            )
        except (TypeError, ValueError):
            top_n_per_match = 0
        if top_n_per_match < 1 or top_n_per_match > 16:
            return Err('Ungültige Top-Anzahl pro Match für die Qualifikation.')

        unique_source_stage_ids = list(dict.fromkeys(source_stage_ids))
        db_source_stages = db.session.scalars(
            select(DbNetsessionTourneyStage)
            .filter_by(tournament_id=tournament_id)
            .filter(DbNetsessionTourneyStage.id.in_(unique_source_stage_ids))
            .order_by(DbNetsessionTourneyStage.order_no.asc())
        ).all()
        if len(db_source_stages) != len(unique_source_stage_ids):
            return Err('Mindestens eine der eingestellten Quell-Stages existiert nicht.')

        selected_participant_ids: list[ParticipantID] = []
        for db_source_stage in db_source_stages:
            ranked_participant_ids_by_match_result = (
                _get_ranked_participant_ids_by_match_for_stage(
                    db_source_stage.id,
                    tournament_id,
                    top_n_per_match=top_n_per_match,
                )
            )
            if ranked_participant_ids_by_match_result.is_err():
                message = ranked_participant_ids_by_match_result.unwrap_err()
                if message.endswith('is not fully completed yet.'):
                    message = (
                        'ist noch nicht vollständig abgeschlossen. '
                        'Schließe zuerst alle Vorrunden-Matches ab.'
                    )
                return Err(
                    f'Quell-Stage „{db_source_stage.name}“: {message}'
                )

            selected_participant_ids.extend(
                ranked_participant_ids_by_match_result.unwrap()
            )

        participants_by_id = get_participants_by_ids(
            party_id, set(selected_participant_ids)
        )
        participants = [
            participants_by_id[participant_id]
            for participant_id in selected_participant_ids
            if participant_id in participants_by_id
        ]
        participants = domain_service.select_ready_participants(participants)
        if len(participants) < 2:
            return Err(
                'Zu wenige qualifizierte Teilnehmer für diese Stage. '
                'Passe die Quell-Stages oder die Top-Anzahl an.'
            )

        return Ok(participants)

    if source_mode != 'stage_qualifiers':
        return Ok(eligible_participants)

    source_stage_ids = _parse_source_stage_ids(
        (stage.settings or {}).get('qualifier_source_stage_ids', [])
    )
    if not source_stage_ids:
        return Err(
            'No source stages configured. Configure qualifier source stages first.'
        )
    if stage.id in source_stage_ids:
        return Err('Eine Stage kann nicht ihre eigene Quelle für Qualifikanten sein.')

    selection_mode = (stage.settings or {}).get(
        'qualifier_selection_mode', 'per_stage'
    )
    if selection_mode not in {'per_stage', 'per_group'}:
        return Err('Ungültige Auswahl der Qualifikanten.')

    unique_source_stage_ids = list(dict.fromkeys(source_stage_ids))
    db_source_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyStage.id.in_(unique_source_stage_ids))
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()
    if len(db_source_stages) != len(unique_source_stage_ids):
        return Err('Mindestens eine der eingestellten Quell-Stages existiert nicht.')

    selected_participant_ids: list[ParticipantID] = []
    for db_source_stage in db_source_stages:
        qualifier_top_n_result = _get_effective_qualifier_top_n_for_source_stage(
            stage,
            db_source_stage,
            tournament_id,
            selection_mode=selection_mode,
        )
        if qualifier_top_n_result.is_err():
            return Err(
                f'Quell-Stage „{db_source_stage.name}“: '
                f'{qualifier_top_n_result.unwrap_err()}'
            )
        top_n = qualifier_top_n_result.unwrap()

        if selection_mode == 'per_group':
            ranked_group_participant_ids_result = (
                _get_ranked_participant_ids_by_group_for_stage(
                    db_source_stage.id,
                    tournament_id,
                )
            )
            if ranked_group_participant_ids_result.is_err():
                message = ranked_group_participant_ids_result.unwrap_err()
                if message.endswith('is not fully completed yet.'):
                    message = (
                        'ist noch nicht vollständig abgeschlossen. '
                        'Schließe zuerst alle Vorrunden-Matches ab.'
                    )
                return Err(
                    f'Quell-Stage „{db_source_stage.name}“: '
                    f'{message}'
                )

            for ranked_group_participant_ids in (
                ranked_group_participant_ids_result.unwrap()
            ):
                if len(ranked_group_participant_ids) < top_n:
                    return Err(
                        f'Quell-Stage „{db_source_stage.name}“ hat eine Gruppe mit '
                        f'nur {len(ranked_group_participant_ids)} gewerteten '
                        f'Teilnehmern, gebraucht werden aber die Top {top_n} pro Gruppe.'
                    )

                selected_participant_ids.extend(
                    ranked_group_participant_ids[:top_n]
                )
        else:
            ranked_participant_ids_result = _get_ranked_participant_ids_for_stage(
                db_source_stage.id, tournament_id
            )
            if ranked_participant_ids_result.is_err():
                message = ranked_participant_ids_result.unwrap_err()
                if message.endswith('is not fully completed yet.'):
                    message = (
                        'ist noch nicht vollständig abgeschlossen. '
                        'Schließe zuerst alle Vorrunden-Matches ab.'
                    )
                return Err(
                    f'Quell-Stage „{db_source_stage.name}“: '
                    f'{message}'
                )

            ranked_participant_ids = ranked_participant_ids_result.unwrap()
            if len(ranked_participant_ids) < top_n:
                return Err(
                    f'Quell-Stage „{db_source_stage.name}“ hat nur '
                    f'{len(ranked_participant_ids)} gewertete Teilnehmer, '
                    f'gebraucht werden aber die Top {top_n}.'
                )

            selected_participant_ids.extend(ranked_participant_ids[:top_n])

    deduplicated_participant_ids = list(dict.fromkeys(selected_participant_ids))
    participants_by_id = get_participants_by_ids(
        party_id, set(deduplicated_participant_ids)
    )
    participants = [
        participants_by_id[participant_id]
        for participant_id in deduplicated_participant_ids
        if participant_id in participants_by_id
    ]
    participants = (
        domain_service.select_ready_participants(participants)
        if is_stage_builder_v1_stage
        else domain_service.select_bracket_ready_participants(participants)
    )

    if len(participants) < 2:
        return Err(
            'Zu wenige qualifizierte Teilnehmer für diese Stage. '
            'Passe die Quell-Stages oder die Top-Anzahl an.'
        )

    return Ok(participants)
