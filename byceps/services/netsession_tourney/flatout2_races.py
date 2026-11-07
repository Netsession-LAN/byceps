"""
byceps.services.netsession_tourney.flatout2_races
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FlatOut 2 rounds: races, hosts and their summaries.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from byceps.database import db
from byceps.services.user.models import UserID

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTeamMember,
)
from .flatout2 import get_flatout2_mode_label
from .models import (
    ParticipantID,
)
from .tournament_queries import ACTIVE_PARTICIPANT_STATUS_VALUES


def get_flatout2_round_races(
    match_settings: dict[str, Any]
) -> list[dict[str, str]]:
    if not isinstance(match_settings, dict):
        return []

    raw_round_races = match_settings.get('flatout2_races')
    if not isinstance(raw_round_races, list):
        return []

    normalized_races = []
    for race in raw_round_races:
        if not isinstance(race, dict):
            continue
        mode = str(race.get('mode') or '').strip() or 'single_race'
        track = str(race.get('track') or '').strip()
        vehicle = str(race.get('vehicle') or '').strip()
        if not track or not vehicle:
            continue
        normalized_races.append(
            {'mode': mode, 'track': track, 'vehicle': vehicle}
        )

    return normalized_races


def get_match_host_participant_id(
    db_match: DbNetsessionTourneyMatch,
) -> ParticipantID | None:
    raw_value = (db_match.settings_json or {}).get('host_participant_id')
    if not raw_value:
        return None

    try:
        return ParticipantID(UUID(str(raw_value)))
    except (TypeError, ValueError):
        return None


def get_selected_host_user_ids(
    db_match: DbNetsessionTourneyMatch,
) -> set[UserID]:
    participant_id = get_match_host_participant_id(db_match)
    if participant_id is None:
        return set()

    db_participant = db.session.get(DbNetsessionTourneyParticipant, participant_id)
    if (
        db_participant is None
        or db_participant.status not in ACTIVE_PARTICIPANT_STATUS_VALUES
    ):
        return set()

    user_ids = {
        db_participant.user_id,
        db_participant.manager_user_id,
    } - {None}
    user_ids.update(
        db.session.scalars(
            select(DbNetsessionTourneyTeamMember.user_id).filter_by(
                participant_id=participant_id
            )
        ).all()
    )
    return user_ids


def build_flatout2_round_race_lines(payload: dict[str, Any]) -> list[str]:
    raw_races = payload.get('flatout2_round_races')
    if not isinstance(raw_races, list):
        return []

    lines = []
    for index, race in enumerate(raw_races, start=1):
        if not isinstance(race, dict):
            continue
        mode = str(race.get('mode') or '').strip() or 'single_race'
        track = str(race.get('track') or '').strip()
        vehicle = str(race.get('vehicle') or '').strip()
        if not track or not vehicle:
            continue
        lines.append(
            f'{index}. {get_flatout2_mode_label(mode)} / {track} / {vehicle}'
        )
    return lines


def build_flatout2_first_race_summary(payload: dict[str, Any]) -> str:
    race_lines = build_flatout2_round_race_lines(payload)
    if not race_lines:
        return ''

    return f'Erstes Rennen: {race_lines[0][3:]}'
