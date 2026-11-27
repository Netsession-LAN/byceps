"""
byceps.services.netsession_tourney.blueprints.site.stage_render_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


from . import builder_flatout2_placeholders
from .bracket_helpers import build_bracket_data, build_bracket_sections
from .builder_display_helpers import (
    get_builder_main_display_stages,
)
from .builder_helpers import (
    build_pending_builder_round_summary_lines,
    get_builder_container_child_stages,
    get_materialized_builder_container_stages,
)
from .public_match_page_data import index_stages_by_id
from .round_based_public_rendering import build_match_overview_sections
from .stage_filters import (
    _is_flatout2_stage,
    is_ffa_single_elimination_stage,
)
from .stage_render_bracket_sections import (
    build_builder_main_stage_bracket_sections as build_builder_main_stage_bracket_sections,
)
from .stage_render_ffa_match_details import (
    _get_ffa_placement_by_slot_no as _get_ffa_placement_by_slot_no,
    build_ffa_match_detail_rows as build_ffa_match_detail_rows,
)
from .stage_render_ffa_matches import build_ffa_match_sections
from .stage_render_grouping import group_matches_by_stage_id
from .stage_render_team_history import (
    build_team_history_rows as build_team_history_rows,
)


@dataclass(frozen=True, kw_only=True)
class _StageMatchSectionData:
    slots_by_match_id: Any
    results_by_match_id: Any
    participants_by_id: Any
    users_by_id: Any
    slot_scores_by_match_id: Any
    match_labels_by_id: Any
    skipped_match_ids: Any
    stages_by_id: dict

    def build_stage_sections(self, stage, stage_matches):
        return _build_stage_public_match_sections(
            stage,
            stage_matches,
            self.slots_by_match_id,
            self.results_by_match_id,
            self.participants_by_id,
            self.users_by_id,
            self.slot_scores_by_match_id,
            self.match_labels_by_id,
            self.skipped_match_ids,
            self.stages_by_id,
        )


def _build_stage_public_match_sections(
    stage,
    stage_matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    skipped_match_ids,
    stages_by_id,
):
    if not stage_matches:
        if _is_flatout2_stage(stage):
            return builder_flatout2_placeholders._build_flatout2_placeholder_match_sections(
                stage
            )
        return []

    if is_ffa_single_elimination_stage(stage):
        return build_ffa_match_sections(
            stage_matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            users_by_id,
            match_labels_by_id,
            skipped_match_ids,
            stages_by_id,
        )

    stage_bracket = build_bracket_data(
        stage_matches,
        slots_by_match_id,
        participants_by_id,
    )
    return build_match_overview_sections(
        build_bracket_sections(stage_bracket, match_labels_by_id),
        stages_by_id,
        results_by_match_id,
        slot_scores_by_match_id,
        match_labels_by_id,
        users_by_id,
        skipped_match_ids,
    )


def _build_pending_match_summary_section(stage, key: str) -> dict:
    return {
        'kind': 'summary',
        'key': key,
        'title': stage.name,
        'presentation': 'summary',
        'lines': build_pending_builder_round_summary_lines(stage),
    }


def build_builder_preliminary_match_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    skipped_match_ids,
):
    preliminary_containers = get_materialized_builder_container_stages(
        stages, role='preliminary'
    )
    if not preliminary_containers:
        return []

    data = _StageMatchSectionData(
        slots_by_match_id=slots_by_match_id,
        results_by_match_id=results_by_match_id,
        participants_by_id=participants_by_id,
        users_by_id=users_by_id,
        slot_scores_by_match_id=slot_scores_by_match_id,
        match_labels_by_id=match_labels_by_id,
        skipped_match_ids=skipped_match_ids,
        stages_by_id=index_stages_by_id(stages),
    )
    matches_by_stage_id = group_matches_by_stage_id(matches)

    sections = []
    for container_stage in preliminary_containers:
        for stage in get_builder_container_child_stages(
            stages, container_stage
        ):
            section = _build_preliminary_stage_section(
                stage, matches_by_stage_id.get(stage.id, []), data
            )
            if section is not None:
                sections.append(section)

    return sections


def _build_preliminary_stage_section(
    stage, stage_matches, data: _StageMatchSectionData
) -> dict | None:
    if not stage_matches:
        return _build_pending_match_summary_section(stage, str(stage.id))

    stage_match_sections = data.build_stage_sections(stage, stage_matches)
    if not stage_match_sections:
        return None

    combined_rounds = []
    presentation = 'duel'
    for subsection in stage_match_sections:
        combined_rounds.extend(subsection['rounds'])
        presentation = subsection.get('presentation', presentation)

    return {
        'kind': 'matches',
        'key': str(stage.id),
        'title': stage.name,
        'presentation': presentation,
        'rounds': combined_rounds,
    }


def build_builder_main_stage_match_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    skipped_match_ids,
):
    main_stages = get_builder_main_display_stages(stages)
    if not main_stages:
        return []

    stages_by_id = index_stages_by_id(stages)
    matches_by_stage_id = group_matches_by_stage_id(matches)

    sections = []
    for stage in main_stages:
        stage_matches = matches_by_stage_id.get(stage.id, [])
        stage_sections = _build_stage_public_match_sections(
            stage,
            stage_matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            users_by_id,
            slot_scores_by_match_id,
            match_labels_by_id,
            skipped_match_ids,
            stages_by_id,
        )
        if not stage_sections:
            sections.append(
                _build_pending_match_summary_section(
                    stage, f'pending-{stage.id}'
                )
            )
            continue

        sections.extend(stage_sections)

    return sections
