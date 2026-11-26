"""
byceps.services.netsession_tourney.discord_result_summaries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Texts for Discord posts about match and tournament results.
"""

from __future__ import annotations

from typing import Any

from .dbmodels import (
    DbNetsessionTourneyTournament,
)
from .discord_result_summaries_completed import (
    _append_discord_lines_field,
    _append_discord_text_field,
    _clean_discord_text,
    build_discord_match_completed_description as build_discord_match_completed_description,
    build_discord_match_completed_fields as build_discord_match_completed_fields,
)
from .discord_result_summaries_match import (
    build_discord_match_result_summary as build_discord_match_result_summary,
)
from .models import (
    ParticipantID,
)
from .stage_ranking import (
    get_ranked_participant_ids_for_stage,
)
from .tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
)


def build_discord_tournament_result_summary(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any] | None:
    participants_by_id = {
        participant.id: participant
        for participant in get_participants_for_tournament(
            db_tournament.party_id, db_tournament.id
        )
    }
    if not participants_by_id:
        return None

    stages = get_stages_for_tournament(db_tournament.party_id, db_tournament.id)
    for stage in reversed(stages):
        ranked_participant_ids_result = get_ranked_participant_ids_for_stage(
            stage.id, db_tournament.id
        )
        if ranked_participant_ids_result.is_err():
            continue

        placements = _build_discord_stage_placements(
            ranked_participant_ids_result.unwrap(), participants_by_id
        )

        if placements:
            return {
                'stage_name': stage.name,
                'placements': placements,
            }

    return None


def _build_discord_stage_placements(
    ranked_participant_ids: list[ParticipantID],
    participants_by_id: dict[ParticipantID, Any],
) -> list[dict[str, Any]]:
    placements: list[dict[str, Any]] = []
    for position, participant_id in enumerate(
        ranked_participant_ids[:8], start=1
    ):
        participant = participants_by_id.get(participant_id)
        if participant is None:
            continue
        placements.append(
            {
                'position': position,
                'participant_name': participant.name,
            }
        )
    return placements


def build_discord_tournament_finished_description(
    tournament_title: str, payload_data: dict[str, Any]
) -> str:
    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return f'**{tournament_title}**\nDas Turnier wurde beendet.'

    placements = _normalize_discord_tournament_placements(
        result_summary.get('placements')
    )
    if not placements:
        return f'**{tournament_title}**\nDas Turnier wurde beendet.'

    winner_name = placements[0][1]
    stage_name = str(result_summary.get('stage_name') or '').strip()
    lines = [
        f'**{tournament_title}**',
        f'Gewonnen hat **{winner_name}**.',
    ]
    if stage_name:
        lines.append(f'Gewertet wurde die Abschlussphase **{stage_name}**.')
    return '\n'.join(lines)


def build_discord_tournament_finished_fields(
    payload_data: dict[str, Any],
) -> list[dict[str, Any]]:
    summary_and_placements = _extract_discord_tournament_placements(
        payload_data
    )
    if summary_and_placements is None:
        return []

    result_summary, placements = summary_and_placements

    fields: list[dict[str, Any]] = []
    stage_name = _clean_discord_text(result_summary.get('stage_name'))
    _append_discord_text_field(fields, 'Abschlussphase', stage_name, True)

    podium_lines = [
        _format_discord_tournament_placement(position, participant_name)
        for position, participant_name in placements[:3]
    ]
    _append_discord_lines_field(fields, 'Podium', podium_lines)

    remaining_lines = [
        _format_discord_tournament_placement(position, participant_name)
        for position, participant_name in placements[3:]
    ]
    _append_discord_lines_field(fields, 'Weitere Plaetze', remaining_lines)

    return fields


def _extract_discord_tournament_placements(
    payload_data: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[int, str]]] | None:
    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return None

    placements = _normalize_discord_tournament_placements(
        result_summary.get('placements')
    )
    if not placements:
        return None

    return result_summary, placements


def _normalize_discord_tournament_placements(
    raw_placements: Any,
) -> list[tuple[int, str]]:
    if not isinstance(raw_placements, list):
        return []

    normalized: list[tuple[int, str]] = []
    for item in raw_placements:
        placement = _normalize_discord_tournament_placement(item)
        if placement is not None:
            normalized.append(placement)

    return normalized


def _normalize_discord_tournament_placement(
    item: Any,
) -> tuple[int, str] | None:
    if not isinstance(item, dict):
        return None

    participant_name = str(item.get('participant_name') or '').strip()
    if not participant_name:
        return None

    try:
        position = int(item.get('position'))
    except TypeError, ValueError:
        return None

    if position < 1:
        return None

    return position, participant_name


def _format_discord_tournament_placement(
    position: int, participant_name: str
) -> str:
    marker = {1: '🥇', 2: '🥈', 3: '🥉'}.get(position, f'{position}.')
    return f'{marker} {participant_name}'
