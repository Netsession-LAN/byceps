"""
byceps.services.netsession_tourney.discord_result_summaries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Texts for Discord posts about match and tournament results.
"""

from __future__ import annotations

from typing import Any

from .dbmodels import (
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTournament,
)
from .models import (
    ParticipantID,
    Stage,
    StageType,
)
from .stage_ranking import (
    get_ranked_participant_ids_for_stage,
)
from .tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
)
from .score_parsing import (
    parse_match_result_slot_scores,
)


def build_discord_match_result_summary(
    *,
    stage: Stage,
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
    ranking_data: dict[str, Any],
) -> dict[str, Any] | None:
    occupied_slots = [
        db_slot
        for db_slot in sorted(db_slots, key=lambda item: item.slot_no)
        if db_slot.participant_id is not None
        and db_slot.participant_id in db_participants_by_id
    ]
    if not occupied_slots:
        return None

    is_ffa_stage = stage.type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }

    if is_ffa_stage:
        return _build_discord_ffa_match_result_summary(
            occupied_slots, db_participants_by_id, ranking_data
        )

    return _build_discord_duel_match_result_summary(
        occupied_slots, db_slots, db_participants_by_id, winner_slot, score_data
    )


def _build_discord_ffa_match_result_summary(
    occupied_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    ranking_data: dict[str, Any],
) -> dict[str, Any] | None:
    raw_placements = (
        ranking_data.get('placements')
        if isinstance(ranking_data, dict)
        else None
    )
    raw_points = (
        ranking_data.get('points')
        if isinstance(ranking_data, dict)
        else None
    )
    if not isinstance(raw_placements, dict):
        return None

    rows: list[dict[str, Any]] = []
    for db_slot in occupied_slots:
        participant = db_participants_by_id.get(db_slot.participant_id)
        if participant is None:
            continue

        placement = raw_placements.get(str(db_slot.slot_no))
        if placement is None:
            placement = raw_placements.get(db_slot.slot_no)
        if placement is None:
            continue

        points = None
        if isinstance(raw_points, dict):
            points = raw_points.get(str(db_slot.slot_no))
            if points is None:
                points = raw_points.get(db_slot.slot_no)

        rows.append(
            {
                'position': int(placement),
                'participant_name': participant.name,
                'points': points,
            }
        )

    if not rows:
        return None

    rows.sort(key=lambda item: (item['position'], item['participant_name']))
    return {'format': 'ffa', 'rows': rows}


def _build_discord_duel_match_result_summary(
    occupied_slots: list[DbNetsessionTourneyMatchSlot],
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
) -> dict[str, Any] | None:
    parsed_scores = parse_match_result_slot_scores(
        db_slots, score_data, winner_slot=winner_slot
    )
    rows = []
    for db_slot in occupied_slots:
        participant = db_participants_by_id.get(db_slot.participant_id)
        if participant is None:
            continue

        rows.append(
            {
                'slot_no': db_slot.slot_no,
                'participant_name': participant.name,
                'score': parsed_scores.get(db_slot.slot_no),
                'is_winner': winner_slot == db_slot.slot_no,
            }
        )

    if not rows:
        return None

    rows.sort(
        key=lambda item: (
            0 if item['is_winner'] else 1,
            item['slot_no'],
        )
    )
    return {'format': 'duel', 'rows': rows}


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

        placements: list[dict[str, Any]] = []
        for position, participant_id in enumerate(
            ranked_participant_ids_result.unwrap()[:8], start=1
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

        if placements:
            return {
                'stage_name': stage.name,
                'placements': placements,
            }

    return None


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
        lines.append(f'Gewertet wurde die Abschluss-Stage **{stage_name}**.')
    return '\n'.join(lines)


def build_discord_tournament_finished_fields(
    payload_data: dict[str, Any],
) -> list[dict[str, Any]]:
    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return []

    placements = _normalize_discord_tournament_placements(
        result_summary.get('placements')
    )
    if not placements:
        return []

    fields: list[dict[str, Any]] = []
    stage_name = str(result_summary.get('stage_name') or '').strip()
    if stage_name:
        fields.append(
            {
                'name': 'Abschluss-Stage',
                'value': stage_name[:1024],
                'inline': True,
            }
        )

    podium_lines = [
        _format_discord_tournament_placement(position, participant_name)
        for position, participant_name in placements[:3]
    ]
    if podium_lines:
        fields.append(
            {
                'name': 'Podium',
                'value': '\n'.join(podium_lines)[:1024],
                'inline': False,
            }
        )

    remaining_lines = [
        _format_discord_tournament_placement(position, participant_name)
        for position, participant_name in placements[3:]
    ]
    if remaining_lines:
        fields.append(
            {
                'name': 'Weitere Plaetze',
                'value': '\n'.join(remaining_lines)[:1024],
                'inline': False,
            }
        )

    return fields


def build_discord_match_completed_description(
    tournament_title: str, payload_data: dict[str, Any]
) -> str:
    stage_name = str(payload_data.get('stage_name') or '').strip()
    match_label = str(payload_data.get('match_label') or '').strip()
    result_summary = payload_data.get('result_summary')

    lines = [f'**{tournament_title}**']
    if stage_name and match_label:
        lines.append(f'{stage_name} - {match_label} ist abgeschlossen.')
    elif match_label:
        lines.append(f'{match_label} ist abgeschlossen.')
    else:
        lines.append('Ein Match ist abgeschlossen.')

    if isinstance(result_summary, dict):
        rows = result_summary.get('rows')
        if isinstance(rows, list) and rows:
            winner_name = str(rows[0].get('participant_name') or '').strip()
            if winner_name:
                lines.append(f'Gewonnen hat **{winner_name}**.')

    return '\n'.join(lines)


def build_discord_match_completed_fields(
    payload_data: dict[str, Any]
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    stage_name = str(payload_data.get('stage_name') or '').strip()
    if stage_name:
        fields.append(
            {
                'name': 'Stage',
                'value': stage_name[:1024],
                'inline': True,
            }
        )

    match_label = str(payload_data.get('match_label') or '').strip()
    if match_label:
        fields.append(
            {
                'name': 'Match',
                'value': match_label[:1024],
                'inline': True,
            }
        )

    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return fields

    rows = result_summary.get('rows')
    if not isinstance(rows, list) or not rows:
        return fields

    if result_summary.get('format') == 'ffa':
        ranking_lines = _build_discord_ffa_ranking_lines(rows)
        if ranking_lines:
            fields.append(
                {
                    'name': 'Ranking',
                    'value': '\n'.join(ranking_lines)[:1024],
                    'inline': False,
                }
            )
    else:
        result_lines = _build_discord_duel_result_lines(rows)
        if result_lines:
            fields.append(
                {
                    'name': 'Ergebnis',
                    'value': '\n'.join(result_lines)[:1024],
                    'inline': False,
                }
            )

    return fields


def _build_discord_ffa_ranking_lines(rows: list[Any]) -> list[str]:
    ranking_lines = []
    for row in rows[:8]:
        participant_name = str(row.get('participant_name') or '').strip()
        if not participant_name:
            continue
        try:
            position = int(row.get('position'))
        except (TypeError, ValueError):
            continue

        points = row.get('points')
        line = f'{position}. {participant_name}'
        if points is not None and str(points).strip():
            line += f' - {points} Pkt.'
        ranking_lines.append(line)
    return ranking_lines


def _build_discord_duel_result_lines(rows: list[Any]) -> list[str]:
    result_lines = []
    for row in rows[:8]:
        participant_name = str(row.get('participant_name') or '').strip()
        if not participant_name:
            continue
        score = row.get('score')
        score_suffix = (
            f' - {score}' if score is not None and str(score).strip() else ''
        )
        prefix = 'W' if row.get('is_winner') else '-'
        result_lines.append(f'{prefix} {participant_name}{score_suffix}')
    return result_lines


def _normalize_discord_tournament_placements(
    raw_placements: Any,
) -> list[tuple[int, str]]:
    if not isinstance(raw_placements, list):
        return []

    normalized: list[tuple[int, str]] = []
    for item in raw_placements:
        if not isinstance(item, dict):
            continue

        participant_name = str(item.get('participant_name') or '').strip()
        if not participant_name:
            continue

        try:
            position = int(item.get('position'))
        except (TypeError, ValueError):
            continue

        if position < 1:
            continue

        normalized.append((position, participant_name))

    return normalized


def _format_discord_tournament_placement(
    position: int, participant_name: str
) -> str:
    marker = {1: '🥇', 2: '🥈', 3: '🥉'}.get(position, f'{position}.')
    return f'{marker} {participant_name}'
