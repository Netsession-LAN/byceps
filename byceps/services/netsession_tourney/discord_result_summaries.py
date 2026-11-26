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
from .score_parsing import (
    parse_match_result_slot_scores,
)
from .stage_ranking import (
    get_ranked_participant_ids_for_stage,
)
from .tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
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
    raw_placements = _get_discord_ranking_data_entry(ranking_data, 'placements')
    raw_points = _get_discord_ranking_data_entry(ranking_data, 'points')
    if not isinstance(raw_placements, dict):
        return None

    rows: list[dict[str, Any]] = []
    for db_slot in occupied_slots:
        row = _build_discord_ffa_result_row(
            db_slot, db_participants_by_id, raw_placements, raw_points
        )
        if row is not None:
            rows.append(row)

    if not rows:
        return None

    rows.sort(key=lambda item: (item['position'], item['participant_name']))
    return {'format': 'ffa', 'rows': rows}


def _get_discord_ranking_data_entry(ranking_data: Any, key: str) -> Any:
    return ranking_data.get(key) if isinstance(ranking_data, dict) else None


def _build_discord_ffa_result_row(
    db_slot: DbNetsessionTourneyMatchSlot,
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    raw_placements: dict[Any, Any],
    raw_points: Any,
) -> dict[str, Any] | None:
    participant = db_participants_by_id.get(db_slot.participant_id)
    if participant is None:
        return None

    placement = _get_discord_slot_keyed_value(raw_placements, db_slot.slot_no)
    if placement is None:
        return None

    points = None
    if isinstance(raw_points, dict):
        points = _get_discord_slot_keyed_value(raw_points, db_slot.slot_no)

    return {
        'position': int(placement),
        'participant_name': participant.name,
        'points': points,
    }


def _get_discord_slot_keyed_value(mapping: dict[Any, Any], slot_no: int) -> Any:
    value = mapping.get(str(slot_no))
    if value is None:
        value = mapping.get(slot_no)
    return value


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


def _clean_discord_text(value: Any) -> str:
    return str(value or '').strip()


def _append_discord_text_field(
    fields: list[dict[str, Any]], name: str, value: str, inline: bool
) -> None:
    if value:
        fields.append(
            {
                'name': name,
                'value': value[:1024],
                'inline': inline,
            }
        )


def _append_discord_lines_field(
    fields: list[dict[str, Any]], name: str, lines: list[str]
) -> None:
    if lines:
        fields.append(
            {
                'name': name,
                'value': '\n'.join(lines)[:1024],
                'inline': False,
            }
        )


def build_discord_match_completed_description(
    tournament_title: str, payload_data: dict[str, Any]
) -> str:
    stage_name = _clean_discord_text(payload_data.get('stage_name'))
    match_label = _clean_discord_text(payload_data.get('match_label'))
    result_summary = payload_data.get('result_summary')

    lines = [f'**{tournament_title}**']
    lines.append(_build_discord_match_completed_line(stage_name, match_label))

    winner_name = _find_discord_match_winner_name(result_summary)
    if winner_name:
        lines.append(f'Gewonnen hat **{winner_name}**.')

    return '\n'.join(lines)


def _build_discord_match_completed_line(
    stage_name: str, match_label: str
) -> str:
    if stage_name and match_label:
        return f'{stage_name} - {match_label} ist abgeschlossen.'
    if match_label:
        return f'{match_label} ist abgeschlossen.'
    return 'Ein Match ist abgeschlossen.'


def _find_discord_match_winner_name(result_summary: Any) -> str:
    if not isinstance(result_summary, dict):
        return ''

    rows = result_summary.get('rows')
    if not isinstance(rows, list) or not rows:
        return ''

    return _clean_discord_text(rows[0].get('participant_name'))


def build_discord_match_completed_fields(
    payload_data: dict[str, Any],
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    stage_name = _clean_discord_text(payload_data.get('stage_name'))
    _append_discord_text_field(fields, 'Phase', stage_name, True)

    match_label = _clean_discord_text(payload_data.get('match_label'))
    _append_discord_text_field(fields, 'Match', match_label, True)

    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return fields

    rows = result_summary.get('rows')
    if not isinstance(rows, list) or not rows:
        return fields

    if result_summary.get('format') == 'ffa':
        ranking_lines = _build_discord_ffa_ranking_lines(rows)
        _append_discord_lines_field(fields, 'Ranking', ranking_lines)
    else:
        result_lines = _build_discord_duel_result_lines(rows)
        _append_discord_lines_field(fields, 'Ergebnis', result_lines)

    return fields


def _build_discord_ffa_ranking_lines(rows: list[Any]) -> list[str]:
    ranking_lines = []
    for row in rows[:8]:
        participant_name = str(row.get('participant_name') or '').strip()
        if not participant_name:
            continue
        try:
            position = int(row.get('position'))
        except TypeError, ValueError:
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
