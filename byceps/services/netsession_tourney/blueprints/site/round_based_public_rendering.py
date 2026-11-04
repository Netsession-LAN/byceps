"""
byceps.services.netsession_tourney.blueprints.site.round_based_public_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from .presentation_helpers import (
    _build_match_overview_slot_data,
    _build_round_time_range_label,
    _get_stage_duration_minutes,
)


def _build_match_overview_sections(
    bracket_sections,
    stages_by_id,
    results_by_match_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    users_by_id,
    skipped_match_ids,
):
    stage_duration_minutes_by_id = {
        stage_id: _get_stage_duration_minutes(stage)
        for stage_id, stage in stages_by_id.items()
    }

    sections = []
    for bracket_section in bracket_sections:
        rounds = []
        for round_data in bracket_section['rounds']:
            matches_in_round = sorted(
                round_data['matches'],
                key=lambda item: item['match'].match_no,
            )

            round_time_range_label = _build_round_time_range_label(
                [item['match'] for item in matches_in_round],
                stage_duration_minutes_by_id,
            )

            rows = []
            for item in matches_in_round:
                match = item['match']
                slots = sorted(
                    item.get('slots', []),
                    key=lambda slot: slot['slot_no'],
                )
                left_slot = slots[0] if len(slots) >= 1 else None
                right_slot = slots[1] if len(slots) >= 2 else None
                result = results_by_match_id.get(match.id)
                winner_slot = result.winner_slot if result else None
                slot_scores = slot_scores_by_match_id.get(match.id, {})

                score_display = _get_match_overview_score_display(
                    slots, slot_scores, result, get_score_display=_get_score_display
                )

                rows.append(
                    {
                        'match': match,
                        'match_label': match_labels_by_id.get(
                            match.id,
                            f'{gettext("Match")} #{match.match_no}',
                        ),
                        'left': _build_match_overview_slot_data(
                            left_slot, winner_slot, users_by_id
                        ),
                        'right': _build_match_overview_slot_data(
                            right_slot, winner_slot, users_by_id
                        ),
                        'score_display': score_display,
                        'has_result': (
                            result is not None and winner_slot is not None
                        ),
                        'is_struck': match.id in skipped_match_ids,
                    }
                )

            if not rows:
                continue

            rounds.append(
                {
                    **round_data,
                    'time_range_label': round_time_range_label,
                    'rows': rows,
                }
            )

        if rounds:
            sections.append(
                {
                    'key': bracket_section['key'],
                    'title': bracket_section['title'],
                    'presentation': 'duel',
                    'rounds': rounds,
                }
            )

    return sections


def _get_match_overview_score_display(
    slots,
    slot_scores,
    result,
    *,
    get_score_display,
) -> str:
    if len(slots) >= 2:
        left_score = slot_scores.get(slots[0]['slot_no'])
        right_score = slot_scores.get(slots[1]['slot_no'])
        if left_score is not None and right_score is not None:
            return f'{left_score} : {right_score}'

    return get_score_display(result)


def _get_score_display(result) -> str:
    if result is None:
        return '-'
    if not result.score:
        return '-'

    return result.score.get('display') or '-'
