"""
byceps.services.netsession_tourney.flatout2_rounds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2: matches of the current round and the host of a match.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

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
from .engines.base import MatchSpec, SlotSpec, StageEngine
from .ffa_qualifiers import (
    _get_ffa_single_elimination_qualifier_ids,
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
    _enqueue_flatout2_host_assignment_notifications,
)
from .service_helpers import (
    _append_audit_log,
    _db_match_to_model,
)
from .stage_generation_base import (
    _distribute_evenly,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
)


@dataclass(frozen=True, kw_only=True)
class _Flatout2CurrentRoundGenerationContext:
    current_round_no: int
    total_round_count: int
    match_nos: list[int]
    participants: list[Participant]
    replace_existing_matches: bool


def _get_flatout2_current_round_generation_context(
    *,
    tournament_id: TournamentID,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
) -> Result[_Flatout2CurrentRoundGenerationContext, str]:
    participant_ids = [participant.id for participant in participants]
    full_generation_result = engine.generate(stage, participant_ids)
    if full_generation_result.is_err():
        return Err(full_generation_result.unwrap_err())

    full_specs = full_generation_result.unwrap()
    if not full_specs:
        return Err('Für diese FlatOut-2-Stage konnten keine Runden berechnet werden.')

    if (stage.settings or {}).get('builder_materialized_round_stage'):
        first_round_no = min(spec.round_no for spec in full_specs)
        current_round_specs = [
            spec for spec in full_specs if spec.round_no == first_round_no
        ]
        try:
            display_round_no = int(
                (stage.settings or {}).get('builder_display_round_no')
                or first_round_no
            )
        except (TypeError, ValueError):
            display_round_no = first_round_no

        return Ok(
            _Flatout2CurrentRoundGenerationContext(
                current_round_no=display_round_no,
                total_round_count=display_round_no,
                match_nos=[spec.match_no for spec in current_round_specs],
                participants=participants,
                replace_existing_matches=True,
            )
        )

    planned_match_nos_by_round_no: dict[int, list[int]] = defaultdict(list)
    for spec in full_specs:
        planned_match_nos_by_round_no[spec.round_no].append(spec.match_no)

    total_round_count = max(planned_match_nos_by_round_no.keys())
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id, stage_id=stage.id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()

    if not db_matches:
        return Ok(
            _Flatout2CurrentRoundGenerationContext(
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
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(
                [match.id for match in previous_round_matches]
            )
        )
    ).all():
        slots_by_match_id[db_slot.match_id].append(db_slot)

    qualified_participant_ids: list[ParticipantID] = []
    for previous_round_match in sorted(
        previous_round_matches, key=lambda item: item.match_no
    ):
        qualified_participant_ids.extend(
            _get_ffa_single_elimination_qualifier_ids(
                previous_round_match.id,
                sorted(
                    slots_by_match_id.get(previous_round_match.id, []),
                    key=lambda item: item.slot_no,
                ),
                3,
            )
        )

    participants_by_id = {participant.id: participant for participant in participants}
    qualified_participants = [
        participants_by_id[participant_id]
        for participant_id in qualified_participant_ids
        if participant_id in participants_by_id
    ]
    if len(qualified_participants) < 2:
        return Err(
            'Es stehen noch nicht genug Qualifikanten für die nächste FlatOut-2-Runde fest.'
        )

    return Ok(
        _Flatout2CurrentRoundGenerationContext(
            current_round_no=next_round_no,
            total_round_count=total_round_count,
            match_nos=planned_match_nos_by_round_no.get(next_round_no, []),
            participants=qualified_participants,
            replace_existing_matches=False,
        )
    )


def _build_flatout2_current_round_match_specs(
    *,
    stage: Stage,
    context: _Flatout2CurrentRoundGenerationContext,
) -> Result[list[MatchSpec], str]:
    raw_hosts_by_round = (stage.settings or {}).get('flatout2_round_hosts', {})
    if not isinstance(raw_hosts_by_round, dict):
        raw_hosts_by_round = {}

    raw_host_ids = raw_hosts_by_round.get(str(context.current_round_no)) or []
    if not isinstance(raw_host_ids, list):
        raw_host_ids = []

    host_participant_ids: list[ParticipantID] = []
    for raw_host_id in raw_host_ids:
        try:
            host_participant_ids.append(ParticipantID(UUID(str(raw_host_id))))
        except (TypeError, ValueError):
            return Err(
                'Die Host-Auswahl für die aktuelle FlatOut-2-Runde ist ungültig.'
            )

    if len(host_participant_ids) != len(context.match_nos):
        return Err(
            'Bitte für jedes Match der aktuellen FlatOut-2-Runde genau einen Host auswählen.'
        )

    if len(set(host_participant_ids)) != len(host_participant_ids):
        return Err(
            'Jeder FlatOut-2-Host darf in einer Runde nur einmal ausgewählt werden.'
        )

    allowed_participant_ids = {participant.id for participant in context.participants}
    if any(
        host_participant_id not in allowed_participant_ids
        for host_participant_id in host_participant_ids
    ):
        return Err(
            'Mindestens ein ausgewählter FlatOut-2-Host gehört nicht zum Teilnehmerfeld dieser Runde.'
        )

    ordered_participant_ids = [
        participant.id
        for participant in context.participants
    ]
    host_participant_id_set = set(host_participant_ids)
    remaining_participant_ids = [
        participant_id
        for participant_id in ordered_participant_ids
        if participant_id not in host_participant_id_set
    ]
    additional_sizes = _distribute_evenly(
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

        slots = [
            SlotSpec(
                slot_no=slot_index + 1,
                participant_id=participant_id,
                source_match_no=None,
            )
            for slot_index, participant_id in enumerate(participant_ids_for_match)
        ]
        if len(slots) == 1:
            slots.append(
                SlotSpec(
                    slot_no=2,
                    participant_id=None,
                    source_match_no=None,
                )
            )

        specs.append(
            MatchSpec(
                round_no=context.current_round_no,
                match_no=match_no,
                state='ready' if len(participant_ids_for_match) >= 2 else 'pending',
                slots=slots,
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
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
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
        return Err('Dieses Match gehört zu keiner FlatOut-2-Stage.')

    allowed_participant_ids = {
        slot.participant_id
        for slot in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
        ).all()
        if slot.participant_id is not None
    }

    if host_participant_id is not None and host_participant_id not in allowed_participant_ids:
        return Err('Der gewählte Host spielt nicht in diesem Match.')

    settings = dict(db_match.settings_json or {})
    previous_host_participant_id = settings.get('host_participant_id')
    if host_participant_id is None:
        settings.pop('host_participant_id', None)
    else:
        settings['host_participant_id'] = str(host_participant_id)

    db_match.settings_json = settings
    db_match.updated_at = datetime.utcnow()
    stage_settings = dict(db_stage.settings_json or {})
    match_hosts = dict(stage_settings.get('flatout2_match_hosts') or {})
    match_key = f'{db_match.round_no}:{db_match.match_no}'
    if host_participant_id is None:
        match_hosts.pop(match_key, None)
    else:
        match_hosts[match_key] = str(host_participant_id)
    stage_settings['flatout2_match_hosts'] = match_hosts
    db_stage.settings_json = stage_settings

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='flatout2_match_host_updated_by_admin',
        payload={
            'host_participant_id': (
                str(host_participant_id) if host_participant_id is not None else None
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
        _enqueue_flatout2_host_assignment_notifications(db_match)

    db.session.commit()
    return Ok(_db_match_to_model(db_match))
