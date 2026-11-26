"""
byceps.services.netsession_tourney.match_generation_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parts of the stage match generation: announcing generated matches
and planning the group split of a round robin builder preliminary.
"""

from __future__ import annotations

from typing import Any

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyStage,
)
from .discord_service import (
    enqueue_discord_event,
)
from .models import (
    Match,
    MatchState,
    StageID,
    TournamentID,
    TournamentStatus,
)
from .notification_service import (
    enqueue_match_ready_notifications,
)
from .round_robin_builder import (
    build_round_robin_builder_group_stage_specs,
)
from .round_robin_group_stages import (
    read_group_plan,
)
from .stage_builder_settings_db import (
    find_builder_main_stage_for_preliminary_stage,
)
from .stage_generation_base import (
    StageGenerationPayload,
)


def _announce_generated_stage_matches(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    payload: StageGenerationPayload,
    matches: list[Match],
    stage_started_now: bool,
) -> None:
    if stage_started_now:
        enqueue_discord_event(
            party_id,
            tournament_id,
            event_name='stage_started',
            payload={
                'stage_id': str(stage_id),
                'stage_name': payload.stage.name,
            },
        )

    if payload.tournament.status == TournamentStatus.live:
        for match in matches:
            if match.state != MatchState.ready:
                continue
            db_match = db.session.get(DbNetsessionTourneyMatch, match.id)
            if db_match is None or db_match.state != MatchState.ready.value:
                continue
            enqueue_match_ready_notifications(db_match)


def _plan_round_robin_builder_group_split(
    tournament_id: TournamentID,
    db_stage: DbNetsessionTourneyStage,
    payload: StageGenerationPayload,
    settings: dict[str, Any],
) -> Result[tuple[int, list[Any], DbNetsessionTourneyStage], str]:
    """Return qualifiers per group, group stage specs and the main stage of
    a builder preliminary that is to be split into group stages."""
    if settings.get('builder_materialized_group_stage_ids'):
        return Err(
            'Diese Vorrunde des Turnierplaners wurde bereits in echte Gruppenphasen aufgeteilt.'
        )

    group_plan_result = read_group_plan(payload.stage.settings)
    if group_plan_result.is_err():
        return Err(group_plan_result.unwrap_err())
    group_count, qualifiers_per_group = group_plan_result.unwrap()

    group_stage_specs = build_round_robin_builder_group_stage_specs(
        payload.participants,
        group_count=group_count,
        qualifiers_per_group=qualifiers_per_group,
    )
    if not group_stage_specs:
        return Err('Es konnten keine Gruppen erzeugt werden.')

    db_main_stage = find_builder_main_stage_for_preliminary_stage(
        tournament_id, db_stage.id
    )
    if db_main_stage is None:
        return Err(
            'Das Hauptturnier des Turnierplaners zur Vorrunde konnte nicht gefunden werden.'
        )

    return Ok((qualifiers_per_group, group_stage_specs, db_main_stage))
