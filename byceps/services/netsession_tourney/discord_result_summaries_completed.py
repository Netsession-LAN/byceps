"""
byceps.services.netsession_tourney.discord_result_summaries_completed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord texts for a completed match, and the embed field helpers
shared with the tournament summaries.
"""

from __future__ import annotations

from typing import Any


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
