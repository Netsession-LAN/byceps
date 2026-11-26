"""
byceps.services.netsession_tourney.blueprints.site.flatout2_public_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.flatout2 import get_flatout2_mode_label

from .flatout2_round_helpers import (
    get_flatout2_expected_round_summaries,
    merge_flatout2_missing_bracket_rounds,
    merge_flatout2_missing_match_rounds,
)


def build_flatout2_match_section(
    stage,
    stage_matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    match_labels_by_id,
    skipped_match_ids,
    stage_duration_minutes_by_id,
    *,
    group_matches_by_round,
    build_participant_data,
    parse_slot_scores,
    get_placement_by_slot_no,
    get_score_display,
    build_round_time_range_label,
):
    grouped_rounds = group_matches_by_round(stage_matches)
    round_titles_by_round_no = {
        int(summary['round_no']): str(summary['display_title'])
        for summary in get_flatout2_expected_round_summaries(stage)
    }

    rounds = []
    for round_data in grouped_rounds:
        matches_in_round = sorted(
            round_data['matches'],
            key=lambda match: match.match_no,
        )
        rows = []
        for match in matches_in_round:
            current_host_participant_id = get_flatout2_host_participant_id(
                match
            )
            slots = sorted(
                slots_by_match_id.get(match.id, []),
                key=lambda slot: slot.slot_no,
            )
            result = results_by_match_id.get(match.id)
            slot_scores = parse_slot_scores(slots, result)
            placement_by_slot_no = get_placement_by_slot_no(result, slots)
            participants = [
                build_participant_data(
                    slot,
                    participants_by_id,
                    users_by_id,
                    result.winner_slot if result else None,
                    slot_scores.get(slot.slot_no),
                    placement_by_slot_no.get(slot.slot_no),
                    is_host=(
                        bool(current_host_participant_id)
                        and str(slot.participant_id)
                        == current_host_participant_id
                    ),
                )
                for slot in slots
                if slot.participant_id is not None
            ]
            participants.sort(
                key=lambda participant: (
                    participant['placement']
                    if participant['placement'] is not None
                    else 999999,
                    -participant['kills_value'],
                    participant['slot_no'],
                    participant['name'].lower(),
                )
            )
            rows.append(
                {
                    'match': match,
                    'match_label': match_labels_by_id.get(
                        match.id,
                        f'{gettext("Match")} #{match.match_no}',
                    ),
                    'participants': participants,
                    'score_display': get_score_display(result),
                    'has_result': result is not None
                    and result.winner_slot is not None,
                    'is_struck': match.id in skipped_match_ids,
                    'show_kills': False,
                    'host_participant_id': current_host_participant_id,
                    'host_name': next(
                        (
                            participant['name']
                            for participant in participants
                            if participant['is_host']
                        ),
                        None,
                    ),
                    'round_races': get_flatout2_round_races_for_stage_round(
                        stage,
                        round_data['round_no'],
                    ),
                }
            )

        rounds.append(
            {
                'round_no': round_data['round_no'],
                'display_round_no': round_data['round_no'],
                'display_title': round_titles_by_round_no.get(
                    round_data['round_no']
                ),
                'time_range_label': build_round_time_range_label(
                    matches_in_round,
                    stage_duration_minutes_by_id,
                ),
                'rows': rows,
            }
        )

    return {
        'key': str(stage.id),
        'title': stage.name if stage is not None else None,
        'presentation': 'ffa',
        'rounds': merge_flatout2_missing_match_rounds(stage, rounds),
    }


def build_flatout2_bracket_section(
    stage,
    stage_matches,
    slots_by_match_id,
    results_by_match_id,
    match_labels_by_id,
    *,
    group_matches_by_round,
    source_match_id_by_slot_id,
    get_score_display,
):
    grouped_rounds = group_matches_by_round(stage_matches)
    round_titles_by_round_no = {
        int(summary['round_no']): str(summary['display_title'])
        for summary in get_flatout2_expected_round_summaries(stage)
    }

    rounds = []
    for round_data in grouped_rounds:
        items = []
        for index, match in enumerate(
            sorted(round_data['matches'], key=lambda item: item.match_no)
        ):
            slots = sorted(
                slots_by_match_id.get(match.id, []),
                key=lambda slot: slot.slot_no,
            )
            result = results_by_match_id.get(match.id)
            current_host_participant_id = get_flatout2_host_participant_id(
                match
            )
            source_match_ids = []
            for slot in slots:
                if slot.source_match_slot_id is None:
                    continue
                source_match_id = source_match_id_by_slot_id.get(
                    slot.source_match_slot_id
                )
                if (
                    source_match_id is not None
                    and source_match_id not in source_match_ids
                ):
                    source_match_ids.append(source_match_id)

            items.append(
                {
                    'match': match,
                    'match_label': match_labels_by_id.get(
                        match.id,
                        f'{gettext("Match")} #{match.match_no}',
                    ),
                    'participant_count': len(
                        [
                            slot
                            for slot in slots
                            if slot.participant_id is not None
                        ]
                    ),
                    'slot_capacity': len(slots),
                    'source_match_ids': source_match_ids,
                    'has_result': (
                        result is not None and result.winner_slot is not None
                    ),
                    'score_display': get_score_display(result),
                    'round_match_index': index,
                    'host_name': next(
                        (
                            getattr(slot.participant, 'name', None)
                            for slot in slots
                            if getattr(slot, 'participant', None) is not None
                            and str(slot.participant.id)
                            == current_host_participant_id
                        ),
                        None,
                    ),
                }
            )

        rounds.append(
            {
                'round_no': round_data['round_no'],
                'display_round_no': round_data.get(
                    'display_round_no', round_data['round_no']
                ),
                'display_title': round_titles_by_round_no.get(
                    round_data['round_no']
                ),
                'matches': items,
            }
        )

    return {
        'key': str(stage.id),
        'title': stage.name if stage is not None else None,
        'presentation': 'ffa',
        'rounds': merge_flatout2_missing_bracket_rounds(stage, rounds),
    }


def get_flatout2_host_participant_id(match) -> str:
    return str((match.settings or {}).get('host_participant_id') or '').strip()


def get_flatout2_round_races_for_stage_round(
    stage, round_no: int
) -> list[dict]:
    raw_round_races = (
        (stage.settings or {})
        .get('flatout2_round_races', {})
        .get(str(round_no))
        or (stage.settings or {})
        .get('flatout2_round_races', {})
        .get(round_no, [])
        or []
    )

    return [
        {
            **race,
            'mode_label': get_flatout2_mode_label(
                str(race.get('mode') or '').strip() or 'single_race'
            ),
        }
        for race in raw_round_races
        if isinstance(race, dict)
    ]
