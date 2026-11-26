"""
byceps.services.netsession_tourney.blueprints.site.routes_bracket
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournament bracket and match overview.
"""

from __future__ import annotations

from flask import (
    g,
    request,
)

from byceps.services.netsession_tourney.match_queries import (
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.util.framework.templating import templated

from .blueprint import blueprint
from .bracket_helpers import build_bracket_data, build_bracket_sections
from .builder_display_helpers import (
    get_builder_main_display_stages,
    select_matches_for_public_bracket,
)
from .builder_helpers import get_materialized_builder_container_stages
from .common import (
    _get_tournament_or_404,
    get_main_nav_current_page_id,
)
from .match_helpers import (
    build_match_labels,
    build_skipped_double_grand_final_match_ids,
    build_slot_scores_by_match_id,
)
from .presentation_helpers import (
    select_builder_stage_section,
)
from .public_match_page_data import (
    index_stages_by_id,
    load_match_participants_and_users,
    load_match_slots_and_results,
)
from .round_robin_groups_display import add_round_robin_groups
from .stage_filters import (
    uses_only_ffa_scoring_stages,
    uses_only_ffa_simple_stages,
    uses_only_ffa_single_elimination_stages,
    uses_only_flatout2_stages,
    uses_only_round_based_duel_stages,
    uses_only_swiss_stages,
)
from .stage_render_helpers import (
    build_builder_main_stage_bracket_sections,
    build_builder_main_stage_match_sections,
    build_ffa_match_sections,
    build_ffa_single_elimination_bracket_sections,
    build_match_overview_sections,
)
from .stage_tabs import build_stage_tab_rows
from .swiss_public_rendering import build_swiss_bracket_sections


@blueprint.get('/<slug>/bracket')
@templated
def view_bracket(slug):
    tournament = _get_tournament_or_404(slug)
    stages, stages_by_id, matches, slots_by_match_id, results_by_match_id = (
        _load_tournament_matches(tournament)
    )
    participants_by_id, users_by_id = load_match_participants_and_users(
        slots_by_match_id
    )
    slot_scores_by_match_id = build_slot_scores_by_match_id(
        matches, slots_by_match_id, results_by_match_id
    )
    match_labels_by_id = build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    skipped_double_grand_final_match_ids = (
        build_skipped_double_grand_final_match_ids(
            matches,
            slots_by_match_id,
            results_by_match_id,
            stages_by_id,
        )
    )
    matches_for_bracket = select_matches_for_public_bracket(stages, matches)
    bracket = build_bracket_data(
        matches_for_bracket, slots_by_match_id, participants_by_id
    )
    bracket_sections = build_bracket_sections(bracket, match_labels_by_id)
    is_ffa_scoring_tournament = uses_only_ffa_scoring_stages(stages, matches)
    is_ffa_single_elimination_tournament = (
        uses_only_ffa_single_elimination_stages(stages, matches)
    )
    is_ffa_match_overview_tournament = _either(
        is_ffa_scoring_tournament, is_ffa_single_elimination_tournament
    )
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    is_swiss_tournament = uses_only_swiss_stages(stages, matches)
    is_round_based_duel_tournament = uses_only_round_based_duel_stages(
        stages, matches
    )
    ffa_match_sections = _build_sections_if(
        _and_not(
            is_ffa_scoring_tournament, is_ffa_single_elimination_tournament
        ),
        build_ffa_match_sections,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_by_id,
        users_by_id,
        match_labels_by_id,
        skipped_double_grand_final_match_ids,
        stages_by_id,
    )
    ffa_single_elimination_bracket_sections = _build_sections_if(
        is_ffa_single_elimination_tournament,
        build_ffa_single_elimination_bracket_sections,
        matches,
        slots_by_match_id,
        results_by_match_id,
        match_labels_by_id,
        stages_by_id,
    )
    swiss_bracket_sections = _build_sections_if(
        is_swiss_tournament,
        build_swiss_bracket_sections,
        matches,
        slots_by_match_id,
        results_by_match_id,
        slot_scores_by_match_id,
        participants_by_id,
        users_by_id,
        match_labels_by_id,
        stages_by_id,
    )
    round_based_match_sections = _build_sections_if(
        _and_not(is_round_based_duel_tournament, is_swiss_tournament),
        build_match_overview_sections,
        bracket_sections,
        stages_by_id,
        results_by_match_id,
        slot_scores_by_match_id,
        match_labels_by_id,
        users_by_id,
        skipped_double_grand_final_match_ids,
    )
    add_round_robin_groups(
        round_based_match_sections,
        stages_by_id,
        slots_by_match_id,
        results_by_match_id,
        participants_by_id,
    )
    main_builder_display_stages = get_builder_main_display_stages(stages)
    builder_stage_bracket_sections = _build_sections_if(
        _shows_builder_bracket_sections(
            main_builder_display_stages,
            is_flatout2_tournament,
            is_swiss_tournament,
        ),
        build_builder_main_stage_bracket_sections,
        stages,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_by_id,
    )
    if builder_stage_bracket_sections:
        is_ffa_single_elimination_tournament = is_ffa_scoring_tournament = False
    selected_builder_bracket_section, builder_bracket_tab_rows = (
        _select_builder_bracket_tab(tournament, builder_stage_bracket_sections)
    )

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'matches': matches,
        'slots_by_match_id': slots_by_match_id,
        'results_by_match_id': results_by_match_id,
        'participants_by_id': participants_by_id,
        'users_by_id': users_by_id,
        'slot_scores_by_match_id': slot_scores_by_match_id,
        'match_labels_by_id': match_labels_by_id,
        'skipped_double_grand_final_match_ids': skipped_double_grand_final_match_ids,
        'bracket': bracket,
        'bracket_sections': bracket_sections,
        'is_ffa_scoring_tournament': is_ffa_scoring_tournament,
        'is_ffa_single_elimination_tournament': is_ffa_single_elimination_tournament,
        'is_ffa_match_overview_tournament': is_ffa_match_overview_tournament,
        'is_flatout2_tournament': is_flatout2_tournament,
        'is_swiss_tournament': is_swiss_tournament,
        'is_round_based_duel_tournament': is_round_based_duel_tournament,
        'ffa_match_sections': ffa_match_sections,
        'round_based_match_sections': round_based_match_sections,
        'builder_stage_bracket_sections': builder_stage_bracket_sections,
        'selected_builder_bracket_section': selected_builder_bracket_section,
        'builder_bracket_tab_rows': builder_bracket_tab_rows,
        'ffa_single_elimination_bracket_sections': (
            ffa_single_elimination_bracket_sections
        ),
        'swiss_bracket_sections': swiss_bracket_sections,
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': _shows_preliminaries_tab(
            stages, is_flatout2_tournament
        ),
        'current_page': current_page_id,
        'current_tournament_page': 'bracket',
    }


@blueprint.get('/<slug>/matches')
@templated
def view_matches(slug):
    tournament = _get_tournament_or_404(slug)
    stages, stages_by_id, matches, slots_by_match_id, results_by_match_id = (
        _load_tournament_matches(tournament)
    )
    match_labels_by_id = build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    skipped_double_grand_final_match_ids = (
        build_skipped_double_grand_final_match_ids(
            matches,
            slots_by_match_id,
            results_by_match_id,
            stages_by_id,
        )
    )
    participants_by_id, users_by_id = load_match_participants_and_users(
        slots_by_match_id
    )
    slot_scores_by_match_id = build_slot_scores_by_match_id(
        matches, slots_by_match_id, results_by_match_id
    )
    bracket = build_bracket_data(matches, slots_by_match_id, participants_by_id)
    bracket_sections = build_bracket_sections(bracket, match_labels_by_id)
    is_ffa_scoring_tournament = uses_only_ffa_scoring_stages(stages, matches)
    is_ffa_single_elimination_tournament = (
        uses_only_ffa_single_elimination_stages(stages, matches)
    )
    is_ffa_match_overview_tournament = _either(
        is_ffa_scoring_tournament, is_ffa_single_elimination_tournament
    )
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    match_sections = _build_match_overview_or_ffa_sections(
        _either(is_ffa_match_overview_tournament, is_flatout2_tournament),
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_by_id,
        users_by_id,
        match_labels_by_id,
        skipped_double_grand_final_match_ids,
        stages_by_id,
        bracket_sections,
        slot_scores_by_match_id,
    )
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    main_builder_display_stages = get_builder_main_display_stages(stages)
    builder_stage_match_sections = _build_sections_if(
        _and_not(bool(main_builder_display_stages), is_flatout2_tournament),
        build_builder_main_stage_match_sections,
        stages,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_by_id,
        users_by_id,
        slot_scores_by_match_id,
        match_labels_by_id,
        skipped_double_grand_final_match_ids,
    )
    selected_builder_match_section = None
    builder_match_tab_rows = []
    if builder_stage_match_sections:
        match_sections = builder_stage_match_sections

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'matches': matches,
        'match_sections': match_sections,
        'builder_stage_match_sections': builder_stage_match_sections,
        'selected_builder_match_section': selected_builder_match_section,
        'builder_match_tab_rows': builder_match_tab_rows,
        'slots_by_match_id': slots_by_match_id,
        'results_by_match_id': results_by_match_id,
        'match_labels_by_id': match_labels_by_id,
        'skipped_double_grand_final_match_ids': skipped_double_grand_final_match_ids,
        'participants_by_id': participants_by_id,
        'users_by_id': users_by_id,
        'is_ffa_scoring_tournament': is_ffa_scoring_tournament,
        'is_ffa_match_overview_tournament': is_ffa_match_overview_tournament,
        'is_flatout2_tournament': is_flatout2_tournament,
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': _shows_preliminaries_tab(
            stages, is_flatout2_tournament
        ),
        'current_page': current_page_id,
        'current_tournament_page': 'matches',
    }


def _load_tournament_matches(tournament):
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = index_stages_by_id(stages)
    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id, results_by_match_id = load_match_slots_and_results(
        matches
    )
    return stages, stages_by_id, matches, slots_by_match_id, results_by_match_id


def _either(flag, other_flag):
    return flag or other_flag


def _and_not(flag, excluded_flag):
    return flag and not excluded_flag


def _build_sections_if(condition, build_sections, *args) -> list:
    return build_sections(*args) if condition else []


def _shows_builder_bracket_sections(
    main_builder_display_stages, is_flatout2_tournament, is_swiss_tournament
):
    return (
        bool(main_builder_display_stages)
        and not is_flatout2_tournament
        and not is_swiss_tournament
    )


def _select_builder_bracket_tab(tournament, builder_stage_bracket_sections):
    if not builder_stage_bracket_sections:
        return None, []

    selected_builder_bracket_section = select_builder_stage_section(
        builder_stage_bracket_sections,
        request.args.get('stage'),
    )
    builder_bracket_tab_rows = build_stage_tab_rows(
        'netsession_tourney.view_bracket',
        tournament.slug,
        builder_stage_bracket_sections,
        selected_builder_bracket_section,
    )
    return selected_builder_bracket_section, builder_bracket_tab_rows


def _build_match_overview_or_ffa_sections(
    use_ffa_sections,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    match_labels_by_id,
    skipped_double_grand_final_match_ids,
    stages_by_id,
    bracket_sections,
    slot_scores_by_match_id,
):
    if use_ffa_sections:
        return build_ffa_match_sections(
            matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            users_by_id,
            match_labels_by_id,
            skipped_double_grand_final_match_ids,
            stages_by_id,
        )

    return build_match_overview_sections(
        bracket_sections,
        stages_by_id,
        results_by_match_id,
        slot_scores_by_match_id,
        match_labels_by_id,
        users_by_id,
        skipped_double_grand_final_match_ids,
    )


def _shows_preliminaries_tab(stages, is_flatout2_tournament) -> bool:
    return (
        bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        )
        and not is_flatout2_tournament
    )
