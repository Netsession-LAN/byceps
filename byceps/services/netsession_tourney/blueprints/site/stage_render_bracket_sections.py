"""
byceps.services.netsession_tourney.blueprints.site.stage_render_bracket_sections
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Public bracket sections of stages and of builder main stages.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from . import builder_flatout2_placeholders
from .bracket_helpers import build_bracket_data, build_bracket_sections
from .builder_display_helpers import (
    get_builder_main_display_stages,
)
from .builder_helpers import (
    build_pending_builder_round_summary_lines,
)
from .match_helpers import build_match_labels
from .presentation_helpers import combine_stage_section_title
from .public_match_page_data import index_stages_by_id
from .stage_filters import (
    _is_flatout2_stage,
    is_ffa_single_elimination_stage,
)
from .stage_render_ffa_bracket import (
    build_ffa_single_elimination_bracket_sections,
)
from .stage_render_ffa_match_details import (
    _get_ffa_placement_by_slot_no as _get_ffa_placement_by_slot_no,
    build_ffa_match_detail_rows as build_ffa_match_detail_rows,
)
from .stage_render_grouping import group_matches_by_stage_id
from .stage_render_team_history import (
    build_team_history_rows as build_team_history_rows,
)


def _build_stage_public_bracket_sections(
    stage,
    stage_matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    match_labels_by_id,
    stages_by_id,
):
    if not stage_matches:
        if _is_flatout2_stage(stage):
            return builder_flatout2_placeholders._build_flatout2_placeholder_bracket_sections(
                stage
            )
        return []

    if is_ffa_single_elimination_stage(stage):
        return build_ffa_single_elimination_bracket_sections(
            stage_matches,
            slots_by_match_id,
            results_by_match_id,
            match_labels_by_id,
            stages_by_id,
        )

    stage_bracket = build_bracket_data(
        stage_matches,
        slots_by_match_id,
        participants_by_id,
    )
    return build_bracket_sections(stage_bracket, match_labels_by_id)


def _get_subsection_title(subsection, stage):
    """Return the subsection title unless it just repeats the stage name."""
    subsection_title = subsection.get('title')
    if subsection_title == stage.name:
        subsection_title = None
    return subsection_title


def _build_pending_bracket_summary_section(stage) -> dict:
    return {
        'kind': 'summary',
        'key': f'pending-{stage.id}',
        'title': stage.name,
        'lines': build_pending_builder_round_summary_lines(stage),
    }


def build_builder_main_stage_bracket_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
):
    main_stages = get_builder_main_display_stages(stages)
    if not main_stages:
        return []

    stages_by_id = index_stages_by_id(stages)
    matches_by_stage_id = group_matches_by_stage_id(matches)

    sections = []
    for stage in main_stages:
        stage_matches = matches_by_stage_id.get(stage.id, [])
        sections.extend(
            _build_main_stage_bracket_sections(
                stage,
                stage_matches,
                slots_by_match_id,
                results_by_match_id,
                participants_by_id,
                stages_by_id,
            )
        )

    return sections


def _build_main_stage_bracket_sections(
    stage,
    stage_matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    stages_by_id,
) -> list[dict]:
    (
        stage_slots_by_match_id,
        stage_participants_by_id,
        stage_match_labels_by_id,
    ) = _scope_to_stage(
        stage_matches, slots_by_match_id, participants_by_id, stages_by_id
    )
    stage_sections = _build_stage_public_bracket_sections(
        stage,
        stage_matches,
        stage_slots_by_match_id,
        results_by_match_id,
        stage_participants_by_id,
        stage_match_labels_by_id,
        stages_by_id,
    )
    if not stage_sections:
        return [_build_pending_bracket_summary_section(stage)]

    return [
        {
            'kind': 'bracket',
            'key': f'{stage.id}-{subsection["key"]}',
            'title': combine_stage_section_title(
                stage.name, _get_subsection_title(subsection, stage)
            ),
            'presentation': _get_bracket_presentation(stage),
            'match_labels_by_id': stage_match_labels_by_id,
            'rounds': subsection['rounds'],
        }
        for subsection in stage_sections
    ]


def _get_bracket_presentation(stage) -> str:
    return 'ffa' if is_ffa_single_elimination_stage(stage) else 'duel'


def _scope_to_stage(
    stage_matches, slots_by_match_id, participants_by_id, stages_by_id
):
    """Return slots, participants and match labels limited to the
    stage's matches.
    """
    stage_match_ids = {match.id for match in stage_matches}
    stage_slots_by_match_id = {
        match_id: slots_by_match_id.get(match_id, [])
        for match_id in stage_match_ids
    }
    stage_participants_by_id = _select_stage_participants_by_id(
        stage_slots_by_match_id, participants_by_id
    )
    stage_match_labels_by_id = build_match_labels(
        stage_matches,
        stage_slots_by_match_id,
        stages_by_id,
    )
    return (
        stage_slots_by_match_id,
        stage_participants_by_id,
        stage_match_labels_by_id,
    )


def _select_stage_participants_by_id(
    stage_slots_by_match_id, participants_by_id
) -> dict:
    stage_participant_ids = {
        slot.participant_id
        for slots in stage_slots_by_match_id.values()
        for slot in slots
        if slot.participant_id is not None
    }
    return {
        participant_id: participants_by_id[participant_id]
        for participant_id in stage_participant_ids
        if participant_id in participants_by_id
    }
