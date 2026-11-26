"""
byceps.services.netsession_tourney.blueprints.site.stage_render_ffa_bracket
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Public bracket of FFA single elimination and FlatOut 2 stages.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask_babel import gettext

from .bracket_helpers import map_source_match_ids_by_slot_id
from .flatout2_public_rendering import build_flatout2_bracket_section
from .round_based_public_rendering import _get_score_display
from .stage_filters import _is_flatout2_stage
from .stage_render_ffa_matches import (
    get_stage_builder_display_title,
    get_stage_total_round_count,
    StageRoundTitles,
)
from .stage_render_grouping import (
    group_matches_by_round,
    group_matches_by_stage_id,
    sort_stage_match_groups,
)


@dataclass(frozen=True, kw_only=True)
class _FfaBracketRenderData:
    slots_by_match_id: Any
    results_by_match_id: Any
    match_labels_by_id: Any
    source_match_id_by_slot_id: dict


def build_ffa_single_elimination_bracket_sections(
    matches,
    slots_by_match_id,
    results_by_match_id,
    match_labels_by_id,
    stages_by_id,
):
    data = _FfaBracketRenderData(
        slots_by_match_id=slots_by_match_id,
        results_by_match_id=results_by_match_id,
        match_labels_by_id=match_labels_by_id,
        source_match_id_by_slot_id=map_source_match_ids_by_slot_id(
            slots_by_match_id
        ),
    )

    matches_by_stage_id = group_matches_by_stage_id(matches)

    sections = []
    only_flatout2_stages = True
    for stage_id, stage_matches in sort_stage_match_groups(
        matches_by_stage_id, stages_by_id
    ):
        stage = stages_by_id.get(stage_id)
        is_flatout2_stage = _is_flatout2_stage(stage)
        only_flatout2_stages = only_flatout2_stages and is_flatout2_stage
        if is_flatout2_stage:
            sections.append(
                _build_flatout2_stage_bracket_section(
                    stage, stage_matches, data
                )
            )
            continue

        sections.append(
            _build_ffa_stage_bracket_section(
                stage_id, stage, stage_matches, data
            )
        )

    if sections and only_flatout2_stages:
        return [_merge_flatout2_bracket_sections(sections)]

    return sections


def _build_flatout2_stage_bracket_section(
    stage, stage_matches, data: _FfaBracketRenderData
):
    return build_flatout2_bracket_section(
        stage,
        stage_matches,
        data.slots_by_match_id,
        data.results_by_match_id,
        data.match_labels_by_id,
        group_matches_by_round=group_matches_by_round,
        source_match_id_by_slot_id=data.source_match_id_by_slot_id,
        get_score_display=_get_score_display,
    )


def _build_ffa_stage_bracket_section(
    stage_id, stage, stage_matches, data: _FfaBracketRenderData
) -> dict:
    grouped_rounds = group_matches_by_round(stage_matches)
    round_count = len(grouped_rounds)
    total_round_count = get_stage_total_round_count(stage)
    builder_display_title = get_stage_builder_display_title(stage)
    round_titles = StageRoundTitles(
        stage=stage,
        total_round_count=total_round_count,
        builder_display_title=builder_display_title,
        round_count=round_count,
    )
    rounds = [
        _build_ffa_bracket_round(round_index, round_data, round_titles, data)
        for round_index, round_data in enumerate(grouped_rounds)
    ]

    return {
        'key': str(stage_id),
        'title': stage.name if stage is not None else None,
        'presentation': 'ffa',
        'rounds': rounds,
    }


def _build_ffa_bracket_round(
    round_index,
    round_data,
    round_titles: StageRoundTitles,
    data: _FfaBracketRenderData,
) -> dict:
    items = [
        _build_ffa_bracket_item(index, match, data)
        for index, match in enumerate(
            sorted(round_data['matches'], key=lambda item: item.match_no)
        )
    ]

    return {
        'round_no': round_data['round_no'],
        'display_round_no': round_data.get(
            'display_round_no', round_data['round_no']
        ),
        'display_title': round_titles.get_title(
            round_index, round_data['round_no']
        ),
        'matches': items,
    }


def _build_ffa_bracket_item(index, match, data: _FfaBracketRenderData) -> dict:
    slots = sorted(
        data.slots_by_match_id.get(match.id, []),
        key=lambda slot: slot.slot_no,
    )
    result = data.results_by_match_id.get(match.id)
    source_match_ids = _collect_source_match_ids(
        slots, data.source_match_id_by_slot_id
    )

    return {
        'match': match,
        'match_label': data.match_labels_by_id.get(
            match.id,
            f'{gettext("Match")} #{match.match_no}',
        ),
        'participant_count': len(
            [slot for slot in slots if slot.participant_id is not None]
        ),
        'slot_capacity': len(slots),
        'source_match_ids': source_match_ids,
        'has_result': (result is not None and result.winner_slot is not None),
        'score_display': _get_score_display(result),
        'round_match_index': index,
        'host_name': None,
    }


def _collect_source_match_ids(slots, source_match_id_by_slot_id) -> list:
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
    return source_match_ids


def _merge_flatout2_bracket_sections(sections: list[dict]) -> dict:
    merged_rounds = []
    display_round_no = 1
    for section in sections:
        section_title = section.get('title')
        for round_data in section.get('rounds', []):
            merged_rounds.append(
                _build_merged_flatout2_round(
                    round_data, section_title, display_round_no
                )
            )
            display_round_no += 1

    return {
        'key': 'flatout2-bracket',
        'title': None,
        'presentation': 'flatout2',
        'rounds': merged_rounds,
    }


def _build_merged_flatout2_round(
    round_data, section_title, display_round_no: int
) -> dict:
    return {
        'round_no': display_round_no,
        'display_round_no': display_round_no,
        'display_title': round_data.get('display_title')
        or section_title
        or gettext('Runde %(round_no)s', round_no=display_round_no),
        'matches': [
            {
                **item,
                'round_match_index': index,
            }
            for index, item in enumerate(round_data.get('matches', []))
        ],
    }
