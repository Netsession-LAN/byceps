"""
byceps.services.netsession_tourney.blueprints.site.common
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shared helpers of the public tournament pages.
"""

from __future__ import annotations

from collections import defaultdict

from flask import (
    abort,
    g,
)
from flask_babel import gettext
from markupsafe import Markup

from byceps.services.netsession_tourney.enum_labels import (
    stage_type_display_name,
)
from byceps.services.netsession_tourney.models import (
    TournamentRuleTemplate,
    TournamentStatus,
)
from byceps.services.netsession_tourney.participant_admin_service import (
    get_participants_by_ids,
)
from byceps.services.netsession_tourney.tournament_rule_template_service import (
    find_tournament_rule_template_by_slug_for_party,
)
from byceps.services.netsession_tourney.tournament_service import (
    find_tournament_by_slug_for_party,
)
from byceps.services.party.models import PartyID

from .body_rendering import (
    render_formatted_body_html as _render_formatted_body_html,
)
from .common_navigation import (
    find_netsession_tourney_subnav_menu_id as find_netsession_tourney_subnav_menu_id,
    get_main_nav_current_page_id as get_main_nav_current_page_id,
)


def build_public_tournament_status(tournament) -> dict[str, str]:
    if tournament.status == TournamentStatus.canceled:
        return {
            'label': gettext('Abgesagt'),
            'class_name': 'ns-tourney-status-tag status-canceled',
        }

    if tournament.status == TournamentStatus.closed:
        return {
            'label': gettext('Beendet'),
            'class_name': 'ns-tourney-status-tag status-closed',
        }

    if tournament.status == TournamentStatus.live:
        return {
            'label': gettext('Live'),
            'class_name': 'ns-tourney-status-tag status-live',
        }

    if tournament.registration_open:
        return {
            'label': gettext('Registrierung offen'),
            'class_name': 'ns-tourney-status-tag status-registration-open',
        }

    return {
        'label': gettext('Registrierung geschlossen'),
        'class_name': 'ns-tourney-status-tag status-registration-closed',
    }


def get_categories_with_tournaments(categories, tournaments):
    categories_sorted = sorted(
        categories, key=lambda category: category.position
    )
    tournaments_by_category_id = defaultdict(list)
    for tournament in tournaments:
        tournaments_by_category_id[tournament.category_id].append(tournament)

    categories_with_tournaments = []
    for category in categories_sorted:
        tournaments_in_category = tournaments_by_category_id.pop(
            category.id, []
        )
        if tournaments_in_category:
            categories_with_tournaments.append(
                (category, tournaments_in_category)
            )

    uncategorized_tournaments = [
        tournament
        for tournaments_in_category in tournaments_by_category_id.values()
        for tournament in tournaments_in_category
    ]

    return categories_with_tournaments, uncategorized_tournaments


def _find_tournament_rule_template(
    tournament,
) -> TournamentRuleTemplate | None:
    if not tournament.rules_page_slug:
        return None

    return find_tournament_rule_template_by_slug_for_party(
        tournament.party_id, tournament.rules_page_slug
    )


def render_tournament_rule_template_body_html(
    rule_template: TournamentRuleTemplate | None,
) -> Markup | None:
    if rule_template is None:
        return None

    return _render_formatted_body_html(
        rule_template.body, rule_template.body_format
    )


def _get_tournament_or_404(slug):
    if not g.party:
        abort(404)

    tournament = find_tournament_by_slug_for_party(
        g.party.id, slug, visible_on_site=True
    )
    if tournament is None:
        abort(404)

    return tournament


def build_slot_score_payload(slots, points_by_slot_no: dict[int, int]) -> dict:
    if not slots:
        return {}

    ordered_slots = sorted(slots, key=lambda slot: slot.slot_no)
    display_values = []
    normalized_points = {}
    for slot in ordered_slots:
        points = points_by_slot_no.get(slot.slot_no, 0)
        display_values.append(str(points))
        normalized_points[str(slot.slot_no)] = points

    return {
        'display': ':'.join(display_values),
        'slots': normalized_points,
    }


def _is_builder_main_stage(stage) -> bool:
    settings = stage.settings or {}
    return (
        settings.get('builder_kind') == 'stage_builder_v1'
        and settings.get('builder_role') == 'main'
    )


def _find_builder_main_stage(stages):
    return next(
        (
            stage
            for stage in sorted(stages, key=lambda item: item.order_no)
            if _is_builder_main_stage(stage)
        ),
        None,
    )


def _build_primary_stage_type_label(stages) -> str:
    primary_stage = stages[0] if stages else None
    return stage_type_display_name(
        primary_stage.type if primary_stage else None
    )


def build_overview_stage_type_label(stages) -> str:
    builder_main_stage = _find_builder_main_stage(stages)
    if builder_main_stage is None:
        return _build_primary_stage_type_label(stages)

    main_stage_label = stage_type_display_name(builder_main_stage.type)
    if (builder_main_stage.settings or {}).get('builder_preliminary_stage_id'):
        return gettext(
            '%(main_stage_label)s + Vorrunden',
            main_stage_label=main_stage_label,
        )

    return main_stage_label


def get_participants_for_tournament_indexed_by_id(
    party_id: PartyID, participant_ids: set
) -> dict:
    return get_participants_by_ids(party_id, participant_ids)


_TIMELINE_ACTION_LABEL_FACTORIES = {
    'tournament_published': lambda: gettext('Turnier ist jetzt live.'),
    'tournament_closed': lambda: gettext('Turnier wurde beendet.'),
    'tournament_canceled': lambda: gettext('Turnier wurde abgesagt.'),
    'match_ready': lambda: gettext('Match ist spielbereit.'),
    'flatout2_host_assigned': lambda: gettext(
        'Du wurdest als FlatOut-2-Host ausgewählt.'
    ),
    'result_reported': lambda: gettext('Ergebnis übermittelt.'),
    'match_rescheduled': lambda: gettext('Match-Zeit wurde geändert.'),
    'match_disputed': lambda: gettext('Ein Konflikt wurde gemeldet.'),
    'match_needs_admin_review': lambda: gettext(
        'Match wartet auf Admin-Prüfung.'
    ),
    'result_confirmation_timed_out': lambda: gettext(
        'Bestätigungsfrist abgelaufen, Match wartet auf Admin-Prüfung.'
    ),
}


def format_timeline_action(entry):
    action = entry['action']
    label_factory = _TIMELINE_ACTION_LABEL_FACTORIES.get(action)
    if label_factory is not None:
        return label_factory()

    return action.replace('_', ' ')
