"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournament, participant and match data of the tournament detail page
(see `routes_tournament_view`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from flask import request

from byceps.services.netsession_tourney import (
    double_grand_final,
    match_queries,
    registration_validation,
    tournament_category_service,
    tournament_prize_service,
    tournament_queries,
    tournament_rule_template_service,
)
from byceps.services.netsession_tourney.blueprints.admin.route_config import (
    TOURNAMENT_DETAIL_TABS,
)
from byceps.services.netsession_tourney.blueprints.site.match_helpers import (
    build_match_labels,
)
from byceps.services.party.models import PartyID


def get_current_subtab() -> str:
    """Return the requested tab of the detail page."""
    requested_tab = (request.args.get('tab') or 'overview').strip().lower()
    return (
        requested_tab if requested_tab in TOURNAMENT_DETAIL_TABS else 'overview'
    )


def collect_category_context(
    party_id: PartyID, tournament: Any
) -> dict[str, Any]:
    """Return the category and the rules template of the tournament."""
    categories_by_id = {
        category.id: category
        for category in tournament_category_service.get_tournament_categories_for_party(
            party_id
        )
    }
    category = categories_by_id.get(tournament.category_id)
    rule_templates_by_slug = {
        template.slug: template
        for template in tournament_rule_template_service.get_tournament_rule_templates_for_party(
            party_id
        )
    }
    selected_rules_template = (
        rule_templates_by_slug.get(tournament.rules_page_slug)
        if tournament.rules_page_slug
        else None
    )
    return {
        'category': category,
        'selected_rules_template': selected_rules_template,
    }


def _get_match_ids(matches: list[Any]) -> set[Any]:
    return {match.id for match in matches}


def collect_core_data(party_id: PartyID, tournament_id: Any) -> dict[str, Any]:
    """Return prizes, stages, participants, matches, slots and results."""
    prizes = tournament_prize_service.get_tournament_prizes_for_tournament(
        tournament_id
    )
    stages = tournament_queries.get_stages_for_tournament(
        party_id, tournament_id
    )
    participants = tournament_queries.get_participants_for_tournament(
        party_id, tournament_id
    )
    participants_by_id = {
        participant.id: participant for participant in participants
    }
    members_by_participant_id = (
        registration_validation.get_team_members_for_participants(
            {participant.id for participant in participants}
        )
    )
    matches = match_queries.get_matches_for_tournament(party_id, tournament_id)
    slots_by_match_id = match_queries.get_match_slots(_get_match_ids(matches))
    results_by_match_id = double_grand_final.get_match_results(
        _get_match_ids(matches)
    )
    return {
        'prizes': prizes,
        'stages': stages,
        'participants': participants,
        'participants_by_id': participants_by_id,
        'members_by_participant_id': members_by_participant_id,
        'matches': matches,
        'slots_by_match_id': slots_by_match_id,
        'results_by_match_id': results_by_match_id,
        'stages_by_id': {stage.id: stage for stage in stages},
    }


def _sort_matches(matches: list[Any], stages_by_id: dict[Any, Any]) -> list:
    return sorted(
        matches,
        key=lambda item: (
            stages_by_id.get(item.stage_id).order_no
            if stages_by_id.get(item.stage_id) is not None
            else 9999,
            item.round_no,
            item.match_no,
        ),
    )


def _group_by_stage_id(sorted_matches: list[Any]) -> dict[UUID, list]:
    matches_by_stage_id: dict[UUID, list] = {}
    for match in sorted_matches:
        matches_by_stage_id.setdefault(match.stage_id, []).append(match)
    return matches_by_stage_id


def _add_known_stage_groups(
    matches_by_stage: list[dict[str, Any]],
    stages: list[Any],
    matches_by_stage_id: dict[UUID, list],
) -> None:
    for stage in stages:
        grouped_matches = matches_by_stage_id.get(stage.id, [])
        if grouped_matches:
            matches_by_stage.append(
                {
                    'stage': stage,
                    'matches': grouped_matches,
                }
            )


def _add_orphan_stage_groups(
    matches_by_stage: list[dict[str, Any]],
    stage_ids_in_order: list[Any],
    stages_by_id: dict[Any, Any],
    matches_by_stage_id: dict[UUID, list],
) -> None:
    for stage_id, grouped_matches in matches_by_stage_id.items():
        if stage_id in stage_ids_in_order or not grouped_matches:
            continue
        matches_by_stage.append(
            {
                'stage': stages_by_id.get(stage_id),
                'matches': grouped_matches,
            }
        )


def collect_match_groups(context: dict[str, Any]) -> dict[str, Any]:
    """Return the matches sorted, grouped by stage and labelled."""
    stages = context['stages']
    stages_by_id = context['stages_by_id']
    sorted_matches = _sort_matches(context['matches'], stages_by_id)
    stage_ids_in_order = [stage.id for stage in stages]
    matches_by_stage_id = _group_by_stage_id(sorted_matches)
    matches_by_stage_lookup = {
        stage_id: grouped_matches
        for stage_id, grouped_matches in matches_by_stage_id.items()
    }
    matches_by_stage: list[dict[str, Any]] = []
    _add_known_stage_groups(matches_by_stage, stages, matches_by_stage_id)
    _add_orphan_stage_groups(
        matches_by_stage, stage_ids_in_order, stages_by_id, matches_by_stage_id
    )
    match_labels_by_id = build_match_labels(
        context['matches'],
        context['slots_by_match_id'],
        stages_by_id,
    )
    return {
        'sorted_matches': sorted_matches,
        'matches_by_stage': matches_by_stage,
        'match_labels_by_id': match_labels_by_id,
        'matches_by_stage_lookup': matches_by_stage_lookup,
    }
