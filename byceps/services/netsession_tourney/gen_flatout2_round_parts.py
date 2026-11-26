"""
byceps.services.netsession_tourney.gen_flatout2_round_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2 round helpers: generation context of the current round,
host-based match specs and host settings of a match.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyStage,
)
from .engines.base import MatchSpec, SlotSpec
from .ffa_qualifiers import (
    get_ffa_single_elimination_qualifier_ids,
)
from .models import (
    MatchID,
    Participant,
    ParticipantID,
    Stage,
    StageID,
    TournamentID,
)


@dataclass(frozen=True, kw_only=True)
class Flatout2CurrentRoundGenerationContext:
    current_round_no: int
    total_round_count: int
    match_nos: list[int]
    participants: list[Participant]
    replace_existing_matches: bool


def build_flatout2_materialized_round_context(
    stage: Stage,
    full_specs: list[MatchSpec],
    participants: list[Participant],
) -> Flatout2CurrentRoundGenerationContext:
    first_round_no = min(spec.round_no for spec in full_specs)
    current_round_specs = [
        spec for spec in full_specs if spec.round_no == first_round_no
    ]
    try:
        display_round_no = int(
            (stage.settings or {}).get('builder_display_round_no')
            or first_round_no
        )
    except TypeError, ValueError:
        display_round_no = first_round_no

    return Flatout2CurrentRoundGenerationContext(
        current_round_no=display_round_no,
        total_round_count=display_round_no,
        match_nos=[spec.match_no for spec in current_round_specs],
        participants=participants,
        replace_existing_matches=True,
    )


def get_flatout2_stage_db_matches(
    tournament_id: TournamentID, stage_id: StageID
) -> list[DbNetsessionTourneyMatch]:
    return db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id, stage_id=stage_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()


def get_flatout2_qualified_participants(
    previous_round_matches: list[DbNetsessionTourneyMatch],
    participants: list[Participant],
) -> list[Participant]:
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
            get_ffa_single_elimination_qualifier_ids(
                previous_round_match.id,
                sorted(
                    slots_by_match_id.get(previous_round_match.id, []),
                    key=lambda item: item.slot_no,
                ),
                3,
            )
        )

    participants_by_id = {
        participant.id: participant for participant in participants
    }
    return [
        participants_by_id[participant_id]
        for participant_id in qualified_participant_ids
        if participant_id in participants_by_id
    ]


def get_flatout2_round_host_participant_ids(
    stage: Stage,
    context: Flatout2CurrentRoundGenerationContext,
) -> Result[list[ParticipantID], str]:
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
        except TypeError, ValueError:
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

    allowed_participant_ids = {
        participant.id for participant in context.participants
    }
    if any(
        host_participant_id not in allowed_participant_ids
        for host_participant_id in host_participant_ids
    ):
        return Err(
            'Mindestens ein ausgewählter FlatOut-2-Host gehört nicht zum Teilnehmerfeld dieser Runde.'
        )

    return Ok(host_participant_ids)


def build_flatout2_host_match_spec(
    round_no: int,
    match_no: int,
    participant_ids_for_match: list[ParticipantID],
) -> MatchSpec:
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

    return MatchSpec(
        round_no=round_no,
        match_no=match_no,
        state='ready' if len(participant_ids_for_match) >= 2 else 'pending',
        slots=slots,
    )


def apply_flatout2_match_host(
    db_match: DbNetsessionTourneyMatch,
    db_stage: DbNetsessionTourneyStage,
    host_participant_id: ParticipantID | None,
) -> str | None:
    """Store the host in match and stage settings; return the previous one."""
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

    return previous_host_participant_id
