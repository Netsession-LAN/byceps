"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Route to show the tournament detail page (see `routes_tournament`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view_data import (
    collect_category_context,
    collect_core_data,
    collect_match_groups,
    get_current_subtab,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view_forms import (
    build_discord_form,
    collect_stage_builder_data,
    select_stage,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view_push import (
    collect_push_and_admin_data,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view_stage import (
    build_selected_stage_context,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_display import (
    build_stage_display_rows,
    build_visible_stage_tabs,
)
from byceps.services.netsession_tourney.forms import (
    TournamentNotificationSendForm,
)
from byceps.services.netsession_tourney.screen_name_suggestions import (
    get_suggested_screen_names_for_party,
)
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required


# Template context keys in the order the detail page has always used.
VIEW_CONTEXT_KEYS = (
    'party',
    'tournament',
    'category',
    'selected_rules_template',
    'prizes',
    'current_subtab',
    'stages',
    'stage_tabs',
    'stage_display_rows',
    'participants',
    'participants_by_id',
    'active_participant_count',
    'suggested_screen_names',
    'tournament_admin_users',
    'members_by_participant_id',
    'matches',
    'sorted_matches',
    'matches_by_stage',
    'stages_by_id',
    'match_labels_by_id',
    'slots_by_match_id',
    'results_by_match_id',
    'selected_stage',
    'selected_stage_matches',
    'selected_stage_slots_by_match_id',
    'selected_stage_match_labels_by_id',
    'selected_stage_results_by_match_id',
    'selected_stage_participants_by_id',
    'selected_stage_users_by_id',
    'selected_stage_slot_scores_by_match_id',
    'selected_stage_skipped_double_grand_final_match_ids',
    'selected_stage_bracket_sections',
    'selected_stage_round_based_sections',
    'selected_stage_swiss_bracket_sections',
    'selected_stage_state_counts',
    'stage_builder_meta_by_id',
    'stage_generation_state_by_id',
    'stage_builder_container_preview_meta_by_id',
    'discord_form',
    'discord_forum_thread_id',
    'notification_send_form',
    'discord_dm_config',
    'browser_push_config',
    'browser_push_subscribed_participant_count',
    'browser_push_subscribed_user_ids',
    'browser_push_recipient_rows',
    'browser_push_outbox_entries',
    'browser_push_outbox_users_by_id',
)


def _collect_stage_context(
    party_id: Any, context: dict[str, Any]
) -> dict[str, Any]:
    stages = context['stages']
    stage_tabs = build_visible_stage_tabs(stages)
    stage_display_rows = build_stage_display_rows(stages)
    selected_stage = select_stage(stages, stage_tabs)
    return {
        'stage_tabs': stage_tabs,
        'stage_display_rows': stage_display_rows,
        'selected_stage': selected_stage,
        **build_selected_stage_context(party_id, selected_stage, context),
    }


def _finish_view_context(
    party_id: Any, tournament: Any, context: dict[str, Any]
) -> dict[str, Any]:
    context['discord_form'] = build_discord_form(party_id, tournament)
    context['discord_forum_thread_id'] = tournament.discord_thread_id
    context['suggested_screen_names'] = get_suggested_screen_names_for_party(
        party_id
    )
    context['notification_send_form'] = TournamentNotificationSendForm(
        data={
            'title': tournament.title,
            'target_url': f'/ns-tourneys/{tournament.slug}',
        }
    )
    return {key: context[key] for key in VIEW_CONTEXT_KEYS}


def register_tournament_view_routes(blueprint) -> None:
    @blueprint.get('/for_party/<party_id>/tournaments/<uuid:tournament_id>')
    @permission_required('netsession_tourney.view')
    @templated
    def view(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        context: dict[str, Any] = {
            'party': party,
            'tournament': tournament,
            'current_subtab': get_current_subtab(),
        }
        context.update(collect_category_context(party.id, tournament))
        context.update(collect_core_data(party.id, tournament.id))
        context.update(collect_match_groups(context))
        context.update(
            collect_push_and_admin_data(party.id, tournament.id, context)
        )
        context.update(_collect_stage_context(party.id, context))
        context.update(
            collect_stage_builder_data(party.id, tournament.id, context)
        )
        return _finish_view_context(party.id, tournament, context)
