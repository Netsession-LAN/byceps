"""
byceps.services.netsession_tourney.blueprints.site.stage_render_ffa_matches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Public match overview of FFA stages, including FFA match detail rows.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask_babel import gettext

from byceps.services.netsession_tourney.models import StageType

from .ffa_single_elimination_rendering import (
    get_ffa_single_elimination_round_title,
)
from .flatout2_public_rendering import build_flatout2_match_section
from .match_helpers import _parse_slot_scores
from .presentation_helpers import (
    _build_round_time_range_label,
    get_stage_duration_minutes,
)
from .round_based_public_rendering import _get_score_display
from .stage_filters import _is_flatout2_stage
from .stage_render_ffa_match_details import (
    _build_ffa_match_participant_data,
    _get_ffa_placement_by_slot_no,
    _get_kills_sort_key,
    build_ffa_match_detail_rows as build_ffa_match_detail_rows,
)
from .stage_render_grouping import (
    group_matches_by_round,
    group_matches_by_stage_id,
    sort_stage_match_groups,
)


@dataclass(frozen=True, kw_only=True)
class _FfaMatchRenderData:
    slots_by_match_id: Any
    results_by_match_id: Any
    participants_by_id: Any
    users_by_id: Any
    match_labels_by_id: Any
    skipped_match_ids: Any
    stage_duration_minutes_by_id: dict


def build_ffa_match_sections(
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    match_labels_by_id,
    skipped_match_ids,
    stages_by_id,
):
    matches_by_stage_id = group_matches_by_stage_id(matches)

    stage_duration_minutes_by_id = {
        stage_id: get_stage_duration_minutes(stage)
        for stage_id, stage in stages_by_id.items()
    }

    data = _FfaMatchRenderData(
        slots_by_match_id=slots_by_match_id,
        results_by_match_id=results_by_match_id,
        participants_by_id=participants_by_id,
        users_by_id=users_by_id,
        match_labels_by_id=match_labels_by_id,
        skipped_match_ids=skipped_match_ids,
        stage_duration_minutes_by_id=stage_duration_minutes_by_id,
    )

    sections = []
    for stage_id, stage_matches in sort_stage_match_groups(
        matches_by_stage_id, stages_by_id
    ):
        stage = stages_by_id.get(stage_id)
        if _is_flatout2_stage(stage):
            sections.append(
                _build_flatout2_stage_match_section(stage, stage_matches, data)
            )
            continue

        sections.append(
            _build_ffa_stage_match_section(stage_id, stage, stage_matches, data)
        )

    return sections


def _build_flatout2_stage_match_section(
    stage, stage_matches, data: _FfaMatchRenderData
):
    return build_flatout2_match_section(
        stage,
        stage_matches,
        data.slots_by_match_id,
        data.results_by_match_id,
        data.participants_by_id,
        data.users_by_id,
        data.match_labels_by_id,
        data.skipped_match_ids,
        data.stage_duration_minutes_by_id,
        group_matches_by_round=group_matches_by_round,
        build_participant_data=_build_ffa_match_participant_data,
        parse_slot_scores=_parse_slot_scores,
        get_placement_by_slot_no=_get_ffa_placement_by_slot_no,
        get_score_display=_get_score_display,
        build_round_time_range_label=_build_round_time_range_label,
    )


def _build_ffa_stage_match_section(
    stage_id, stage, stage_matches, data: _FfaMatchRenderData
) -> dict:
    grouped_rounds = group_matches_by_round(stage_matches)
    is_ffa_single_elimination = stage is not None and stage.type in {
        StageType.ffa_single_elimination,
    }
    round_titles = StageRoundTitles(
        stage=stage,
        total_round_count=get_stage_total_round_count(stage),
        builder_display_title=get_stage_builder_display_title(stage),
        round_count=len(grouped_rounds),
    )
    rounds = [
        _build_ffa_round(
            round_index,
            round_data,
            round_titles if is_ffa_single_elimination else None,
            data,
        )
        for round_index, round_data in enumerate(grouped_rounds)
    ]

    return {
        'key': str(stage_id),
        'title': stage.name if stage is not None else None,
        'presentation': 'ffa',
        'rounds': rounds,
    }


def _build_ffa_round(
    round_index,
    round_data,
    round_titles: StageRoundTitles | None,
    data: _FfaMatchRenderData,
) -> dict:
    matches_in_round = sorted(
        round_data['matches'],
        key=lambda match: match.match_no,
    )
    rows = [_build_ffa_match_row(match, data) for match in matches_in_round]

    return {
        'round_no': round_data['round_no'],
        'display_round_no': round_data['round_no'],
        'display_title': (
            round_titles.get_title(round_index, round_data['round_no'])
            if round_titles is not None
            else None
        ),
        'time_range_label': _build_round_time_range_label(
            matches_in_round,
            data.stage_duration_minutes_by_id,
        ),
        'rows': rows,
    }


@dataclass(frozen=True, kw_only=True)
class StageRoundTitles:
    stage: Any
    total_round_count: int
    builder_display_title: str
    round_count: int

    def get_title(self, round_index: int, round_no):
        """Return the builder display title if set, the generated FFA
        single elimination round title otherwise.
        """
        return (
            self.builder_display_title
            or get_ffa_single_elimination_round_title(
                round_index,
                self.round_count,
                stage_type=self.stage.type if self.stage is not None else None,
                round_no=round_no,
                total_round_count=self.total_round_count or None,
            )
        )


def get_stage_total_round_count(stage) -> int:
    try:
        return int((stage.settings or {}).get('round_count') or 0)
    except AttributeError, TypeError, ValueError:
        return 0


def get_stage_builder_display_title(stage) -> str:
    if stage is None:
        return ''

    return str(
        (stage.settings or {}).get('builder_display_title') or ''
    ).strip()


def _build_ffa_match_row(match, data: _FfaMatchRenderData) -> dict:
    slots = sorted(
        data.slots_by_match_id.get(match.id, []),
        key=lambda slot: slot.slot_no,
    )
    result = data.results_by_match_id.get(match.id)
    slot_scores = _parse_slot_scores(slots, result)
    placement_by_slot_no = _get_ffa_placement_by_slot_no(result, slots)
    participants = [
        _build_ffa_match_participant_data(
            slot,
            data.participants_by_id,
            data.users_by_id,
            result.winner_slot if result else None,
            slot_scores.get(slot.slot_no),
            placement_by_slot_no.get(slot.slot_no),
        )
        for slot in slots
        if slot.participant_id is not None
    ]
    participants.sort(key=_get_kills_sort_key)
    return {
        'match': match,
        'match_label': data.match_labels_by_id.get(
            match.id,
            f'{gettext("Match")} #{match.match_no}',
        ),
        'participants': participants,
        'score_display': _get_score_display(result),
        'has_result': result is not None and result.winner_slot is not None,
        'is_struck': match.id in data.skipped_match_ids,
        'show_kills': True,
        'host_participant_id': '',
        'host_name': None,
        'round_races': [],
    }
