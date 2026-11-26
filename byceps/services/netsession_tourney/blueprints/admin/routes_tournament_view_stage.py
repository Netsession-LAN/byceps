"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view_stage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Selected stage of the tournament detail page: its matches, slots,
participants and bracket sections (see `routes_tournament_view`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from byceps.services.netsession_tourney import participant_admin_service
from byceps.services.netsession_tourney.blueprints.site.bracket_helpers import (
    build_bracket_data,
    build_bracket_sections,
)
from byceps.services.netsession_tourney.blueprints.site.match_helpers import (
    build_match_labels,
    build_skipped_double_grand_final_match_ids,
    build_slot_scores_by_match_id,
)
from byceps.services.netsession_tourney.blueprints.site.round_based_public_rendering import (
    build_match_overview_sections,
)
from byceps.services.netsession_tourney.blueprints.site.swiss_public_rendering import (
    build_swiss_bracket_sections,
)
from byceps.services.netsession_tourney.models import StageType
from byceps.services.party.models import PartyID
from byceps.services.user import user_service


def _empty_selected_stage_context() -> dict[str, Any]:
    return {
        'selected_stage_matches': [],
        'selected_stage_slots_by_match_id': {},
        'selected_stage_results_by_match_id': {},
        'selected_stage_match_labels_by_id': {},
        'selected_stage_participants_by_id': {},
        'selected_stage_users_by_id': {},
        'selected_stage_slot_scores_by_match_id': {},
        'selected_stage_skipped_double_grand_final_match_ids': set(),
        'selected_stage_bracket_sections': [],
        'selected_stage_round_based_sections': [],
        'selected_stage_swiss_bracket_sections': [],
        'selected_stage_state_counts': {},
    }


def _get_slots_and_results(
    match_ids: set[Any],
    slots_by_match_id: dict[Any, Any],
    results_by_match_id: dict[Any, Any],
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    selected_stage_slots_by_match_id = {
        match_id: slots_by_match_id.get(match_id, []) for match_id in match_ids
    }
    selected_stage_results_by_match_id = {
        match_id: results_by_match_id.get(match_id)
        for match_id in match_ids
        if match_id in results_by_match_id
    }
    return selected_stage_slots_by_match_id, selected_stage_results_by_match_id


def _get_participant_ids(slots_by_match_id: dict[Any, Any]) -> set[Any]:
    return {
        slot.participant_id
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.participant_id is not None
    }


def _load_participants_and_users(
    party_id: PartyID, participant_ids: set[Any]
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    if not participant_ids:
        return {}, {}

    participants_by_id = participant_admin_service.get_participants_by_ids(
        party_id, participant_ids
    )
    user_ids = {
        participant.user_id
        for participant in participants_by_id.values()
        if participant.user_id is not None
    }
    users_by_id = user_service.get_users_indexed_by_id(
        user_ids,
        include_avatars=True,
    )
    return participants_by_id, users_by_id


def _build_round_sections(
    selected_stage: Any, stage_context: dict[str, Any]
) -> tuple[list[Any], list[Any]]:
    """Return the Swiss and the round-based sections of the stage."""
    if selected_stage.type not in {
        StageType.swiss,
        StageType.round_robin_groups,
        StageType.league,
    }:
        return [], []

    if selected_stage.type == StageType.swiss:
        return build_swiss_bracket_sections(
            stage_context['selected_stage_matches'],
            stage_context['selected_stage_slots_by_match_id'],
            stage_context['selected_stage_results_by_match_id'],
            stage_context['selected_stage_slot_scores_by_match_id'],
            stage_context['selected_stage_participants_by_id'],
            stage_context['selected_stage_users_by_id'],
            stage_context['selected_stage_match_labels_by_id'],
            {selected_stage.id: selected_stage},
        ), []

    return [], build_match_overview_sections(
        stage_context['selected_stage_bracket_sections'],
        {selected_stage.id: selected_stage},
        stage_context['selected_stage_results_by_match_id'],
        stage_context['selected_stage_slot_scores_by_match_id'],
        stage_context['selected_stage_match_labels_by_id'],
        stage_context['selected_stage_users_by_id'],
        stage_context['selected_stage_skipped_double_grand_final_match_ids'],
    )


def _count_match_states(matches: list[Any]) -> dict[str, int]:
    selected_stage_state_counts = {
        'pending': 0,
        'ready': 0,
        'in_progress': 0,
        'pending_confirmation': 0,
        'needs_admin_review': 0,
        'completed': 0,
        'disputed': 0,
    }
    for match in matches:
        key = match.state.value
        selected_stage_state_counts[key] = (
            selected_stage_state_counts.get(key, 0) + 1
        )
    return selected_stage_state_counts


def _build_stage_match_context(
    selected_stage: Any, context: dict[str, Any]
) -> dict[str, Any]:
    matches = [
        match
        for match in context['matches']
        if match.stage_id == selected_stage.id
    ]
    slots_by_match_id, results_by_match_id = _get_slots_and_results(
        {match.id for match in matches},
        context['slots_by_match_id'],
        context['results_by_match_id'],
    )
    stages_by_id = context['stages_by_id']
    return {
        'selected_stage_matches': matches,
        'selected_stage_slots_by_match_id': slots_by_match_id,
        'selected_stage_results_by_match_id': results_by_match_id,
        'selected_stage_match_labels_by_id': build_match_labels(
            matches, slots_by_match_id, stages_by_id
        ),
        'selected_stage_skipped_double_grand_final_match_ids': (
            build_skipped_double_grand_final_match_ids(
                matches, slots_by_match_id, results_by_match_id, stages_by_id
            )
        ),
        'selected_stage_slot_scores_by_match_id': build_slot_scores_by_match_id(
            matches, slots_by_match_id, results_by_match_id
        ),
    }


def build_selected_stage_context(
    party_id: PartyID, selected_stage: Any, context: dict[str, Any]
) -> dict[str, Any]:
    """Return matches, slots, participants and sections of the stage."""
    if selected_stage is None:
        return _empty_selected_stage_context()

    stage_context = _build_stage_match_context(selected_stage, context)
    participants_by_id, users_by_id = _load_participants_and_users(
        party_id,
        _get_participant_ids(stage_context['selected_stage_slots_by_match_id']),
    )
    stage_context['selected_stage_participants_by_id'] = participants_by_id
    stage_context['selected_stage_users_by_id'] = users_by_id
    selected_stage_bracket = build_bracket_data(
        stage_context['selected_stage_matches'],
        stage_context['selected_stage_slots_by_match_id'],
        participants_by_id,
    )
    stage_context['selected_stage_bracket_sections'] = build_bracket_sections(
        selected_stage_bracket,
        stage_context['selected_stage_match_labels_by_id'],
    )
    swiss_sections, round_based_sections = _build_round_sections(
        selected_stage, stage_context
    )
    stage_context['selected_stage_swiss_bracket_sections'] = swiss_sections
    stage_context['selected_stage_round_based_sections'] = round_based_sections
    stage_context['selected_stage_state_counts'] = _count_match_states(
        stage_context['selected_stage_matches']
    )
    return stage_context
