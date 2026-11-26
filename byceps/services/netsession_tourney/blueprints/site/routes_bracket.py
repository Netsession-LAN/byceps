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

from byceps.services.netsession_tourney.double_grand_final import (
    get_match_results,
)
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.services.user import user_service
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
    get_participants_for_tournament_indexed_by_id,
)
from .match_helpers import (
    build_match_labels,
    build_skipped_double_grand_final_match_ids,
    build_slot_scores_by_match_id,
)
from .presentation_helpers import (
    select_builder_stage_section,
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
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
    participants_by_id = get_participants_for_tournament_indexed_by_id(
        g.party.id,
        {
            slot.participant_id
            for slots in slots_by_match_id.values()
            for slot in slots
            if slot.participant_id
        },
    )
    participant_user_ids = {
        participant.user_id
        for participant in participants_by_id.values()
        if participant.user_id is not None
    }
    users_by_id = user_service.get_users_indexed_by_id(
        participant_user_ids,
        include_avatars=True,
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
    is_ffa_match_overview_tournament = (
        is_ffa_scoring_tournament or is_ffa_single_elimination_tournament
    )
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    is_swiss_tournament = uses_only_swiss_stages(stages, matches)
    is_round_based_duel_tournament = uses_only_round_based_duel_stages(
        stages, matches
    )
    ffa_match_sections = (
        build_ffa_match_sections(
            matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            users_by_id,
            match_labels_by_id,
            skipped_double_grand_final_match_ids,
            stages_by_id,
        )
        if is_ffa_scoring_tournament
        and not is_ffa_single_elimination_tournament
        else []
    )
    ffa_single_elimination_bracket_sections = (
        build_ffa_single_elimination_bracket_sections(
            matches,
            slots_by_match_id,
            results_by_match_id,
            match_labels_by_id,
            stages_by_id,
        )
        if is_ffa_single_elimination_tournament
        else []
    )
    swiss_bracket_sections = (
        build_swiss_bracket_sections(
            matches,
            slots_by_match_id,
            results_by_match_id,
            slot_scores_by_match_id,
            participants_by_id,
            users_by_id,
            match_labels_by_id,
            stages_by_id,
        )
        if is_swiss_tournament
        else []
    )
    round_based_match_sections = (
        build_match_overview_sections(
            bracket_sections,
            stages_by_id,
            results_by_match_id,
            slot_scores_by_match_id,
            match_labels_by_id,
            users_by_id,
            skipped_double_grand_final_match_ids,
        )
        if is_round_based_duel_tournament and not is_swiss_tournament
        else []
    )
    add_round_robin_groups(
        round_based_match_sections,
        stages_by_id,
        slots_by_match_id,
        results_by_match_id,
        participants_by_id,
    )
    main_builder_display_stages = get_builder_main_display_stages(stages)
    builder_stage_bracket_sections = (
        build_builder_main_stage_bracket_sections(
            stages,
            matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
        )
        if bool(main_builder_display_stages)
        and not is_flatout2_tournament
        and not is_swiss_tournament
        else []
    )
    if builder_stage_bracket_sections:
        is_ffa_single_elimination_tournament = is_ffa_scoring_tournament = False
    selected_builder_bracket_section = None
    builder_bracket_tab_rows = []
    if builder_stage_bracket_sections:
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
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        )
        and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'bracket',
    }


@blueprint.get('/<slug>/matches')
@templated
def view_matches(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
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
    participants_by_id = get_participants_for_tournament_indexed_by_id(
        g.party.id,
        {
            slot.participant_id
            for slots in slots_by_match_id.values()
            for slot in slots
            if slot.participant_id
        },
    )
    participant_user_ids = {
        participant.user_id
        for participant in participants_by_id.values()
        if participant.user_id is not None
    }
    users_by_id = user_service.get_users_indexed_by_id(
        participant_user_ids,
        include_avatars=True,
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
    is_ffa_match_overview_tournament = (
        is_ffa_scoring_tournament or is_ffa_single_elimination_tournament
    )
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    match_sections = (
        build_ffa_match_sections(
            matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            users_by_id,
            match_labels_by_id,
            skipped_double_grand_final_match_ids,
            stages_by_id,
        )
        if is_ffa_match_overview_tournament or is_flatout2_tournament
        else build_match_overview_sections(
            bracket_sections,
            stages_by_id,
            results_by_match_id,
            slot_scores_by_match_id,
            match_labels_by_id,
            users_by_id,
            skipped_double_grand_final_match_ids,
        )
    )
    is_flatout2_tournament = uses_only_flatout2_stages(stages, matches)
    main_builder_display_stages = get_builder_main_display_stages(stages)
    builder_stage_match_sections = (
        build_builder_main_stage_match_sections(
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
        if bool(main_builder_display_stages) and not is_flatout2_tournament
        else []
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
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        )
        and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'matches',
    }
