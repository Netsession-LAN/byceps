"""
byceps.services.netsession_tourney.blueprints.site.routes_preliminaries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Preliminary rounds of stage builder tournaments.
"""

from __future__ import annotations

from uuid import UUID

from flask import (
    g,
    redirect,
    request,
    url_for,
)
from flask_babel import gettext

from byceps.services.netsession_tourney.match_queries import (
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.util.framework.templating import templated

from .blueprint import blueprint
from .builder_display_helpers import (
    build_builder_stage_summary_lines,
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
from .ranking_helpers import (
    build_ranking_rows,
)
from .stage_filters import (
    is_ffa_single_elimination_stage,
    uses_only_ffa_simple_stages,
)
from .stage_render_helpers import (
    build_builder_preliminary_match_sections,
)
from .stage_tabs import build_stage_tab_rows


@blueprint.get('/<slug>/preliminaries')
@templated('site/netsession_tourney/view_preliminaries')
def view_preliminaries(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    preliminary_container_stages = get_materialized_builder_container_stages(
        stages, role='preliminary'
    )
    if not preliminary_container_stages:
        return redirect(url_for('netsession_tourney.view_overview', slug=slug))

    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id, results_by_match_id = load_match_slots_and_results(
        matches
    )
    stages_by_id = index_stages_by_id(stages)
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

    preliminary_summary_stage = preliminary_container_stages[0]
    preliminary_sections = build_builder_preliminary_match_sections(
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
    selected_preliminary_section = select_builder_stage_section(
        preliminary_sections,
        request.args.get('stage'),
    )
    (
        selected_stage,
        preliminary_ranking_subject_label,
        selected_preliminary_ranking_rows,
    ) = _build_selected_preliminary_ranking(
        selected_preliminary_section,
        stages_by_id,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_by_id,
    )
    preliminary_tab_rows = build_stage_tab_rows(
        'netsession_tourney.view_preliminaries',
        tournament.slug,
        preliminary_sections,
        selected_preliminary_section,
    )
    preliminary_summary_lines = _build_preliminary_summary_lines(
        preliminary_summary_stage, stages
    )

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'selected_preliminary_section': selected_preliminary_section,
        'selected_preliminary_stage_type': _get_stage_type(selected_stage),
        'selected_preliminary_is_ffa_stage': _is_ffa_single_elimination_stage(
            selected_stage
        ),
        'selected_preliminary_ranking_rows': selected_preliminary_ranking_rows,
        'preliminary_ranking_subject_label': preliminary_ranking_subject_label,
        'preliminary_tab_rows': preliminary_tab_rows,
        'preliminary_summary_lines': preliminary_summary_lines,
        'users_by_id': users_by_id,
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': True,
        'current_page': current_page_id,
        'current_tournament_page': 'preliminaries',
    }


def _build_selected_preliminary_ranking(
    selected_preliminary_section,
    stages_by_id,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
):
    """Return the selected stage, the ranking subject label, and the
    ranking rows of the selected preliminary section.
    """
    preliminary_ranking_subject_label = gettext('Teilnehmer')
    if selected_preliminary_section is None:
        return None, preliminary_ranking_subject_label, []

    selected_stage_id = UUID(selected_preliminary_section['key'])
    selected_stage = stages_by_id.get(selected_stage_id)
    selected_stage_matches = [
        match for match in matches if match.stage_id == selected_stage_id
    ]
    selected_stage_slots_by_match_id, selected_stage_results_by_match_id = (
        _select_stage_slots_and_results(
            selected_stage_matches, slots_by_match_id, results_by_match_id
        )
    )
    selected_stage_participants = _select_stage_participants(
        participants_by_id, selected_stage_slots_by_match_id
    )
    preliminary_ranking_subject_label = _get_ranking_subject_label(
        selected_stage_participants, preliminary_ranking_subject_label
    )

    selected_preliminary_ranking_rows = []
    if not is_ffa_single_elimination_stage(selected_stage):
        selected_preliminary_ranking_rows = build_ranking_rows(
            selected_stage_participants,
            selected_stage_matches,
            selected_stage_slots_by_match_id,
            selected_stage_results_by_match_id,
            stage_type=_get_stage_type(selected_stage),
        )
    return (
        selected_stage,
        preliminary_ranking_subject_label,
        selected_preliminary_ranking_rows,
    )


def _select_stage_slots_and_results(
    selected_stage_matches, slots_by_match_id, results_by_match_id
):
    selected_stage_match_ids = {match.id for match in selected_stage_matches}
    selected_stage_slots_by_match_id = {
        match_id: slots_by_match_id.get(match_id, [])
        for match_id in selected_stage_match_ids
    }
    selected_stage_results_by_match_id = {
        match_id: results_by_match_id.get(match_id)
        for match_id in selected_stage_match_ids
        if match_id in results_by_match_id
    }
    return selected_stage_slots_by_match_id, selected_stage_results_by_match_id


def _select_stage_participants(
    participants_by_id, selected_stage_slots_by_match_id
) -> list:
    return [
        participant
        for participant in participants_by_id.values()
        if participant.id
        in {
            slot.participant_id
            for slots in selected_stage_slots_by_match_id.values()
            for slot in slots
            if slot.participant_id is not None
        }
    ]


def _get_ranking_subject_label(selected_stage_participants, default_label):
    if selected_stage_participants and all(
        participant.type.value == 'team'
        for participant in selected_stage_participants
    ):
        return gettext('Team')

    if selected_stage_participants and all(
        participant.user_id is not None
        for participant in selected_stage_participants
    ):
        return gettext('Spieler')

    return default_label


def _build_preliminary_summary_lines(preliminary_summary_stage, stages):
    return (
        build_builder_stage_summary_lines(preliminary_summary_stage, stages)
        if preliminary_summary_stage is not None
        else []
    )


def _get_stage_type(stage):
    return stage.type if stage is not None else None


def _is_ffa_single_elimination_stage(stage):
    return (
        is_ffa_single_elimination_stage(stage) if stage is not None else False
    )
