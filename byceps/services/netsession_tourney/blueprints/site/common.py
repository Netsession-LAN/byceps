"""
byceps.services.netsession_tourney.blueprints.site.common
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shared helpers of the public tournament pages.
"""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit
from uuid import UUID

from flask import (
    abort,
    g,
    url_for,
)
from flask_babel import get_locale, gettext
from markupsafe import Markup

from byceps.services.party.models import PartyID
from byceps.services.site_navigation import site_navigation_service
from byceps.services.site_navigation.models import NavItem, NavItemTargetType
from byceps.util.l10n import get_default_locale

from ...enum_labels import stage_type_display_name
from ...models import (
    TournamentRuleTemplate,
    TournamentStatus,
)
from ...participant_admin_service import (
    get_participants_by_ids,
)
from ...tournament_rule_template_service import (
    find_tournament_rule_template_by_slug_for_party,
)
from ...tournament_service import (
    find_tournament_by_slug_for_party,
)
from .body_rendering import (
    render_formatted_body_html as _render_formatted_body_html,
)


def _build_public_tournament_status(tournament) -> dict[str, str]:
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


def _get_main_nav_current_page_id() -> str:
    """Return the `current_page_id` configured for the NS tourney main-nav item."""
    site = getattr(g, 'site', None)
    if site is None:
        return 'ns_tourney_index'

    locale = get_locale()
    if locale is None:
        return 'ns_tourney_index'

    language_codes = [locale.language]

    default_locale = get_default_locale()
    if default_locale.language not in language_codes:
        language_codes.append(default_locale.language)

    for language_code in language_codes:
        items = site_navigation_service.get_items_for_menu(
            site.id, 'main', language_code
        )
        item_current_page_id = _find_main_nav_item_current_page_id(items)
        if item_current_page_id is not None:
            return item_current_page_id

    return 'ns_tourney_index'


def _find_netsession_tourney_subnav_menu_id(*view_names: str) -> UUID | None:
    site = getattr(g, 'site', None)
    if site is None:
        return None

    locale = get_locale()
    if locale is None:
        return None

    language_codes = [locale.language]

    default_locale = get_default_locale()
    if default_locale.language not in language_codes:
        language_codes.append(default_locale.language)

    for language_code in language_codes:
        for view_name in view_names:
            menu_id = site_navigation_service.find_submenu_id_for_view(
                site.id, language_code, view_name
            )
            if menu_id is not None:
                return menu_id

    return None


def _find_main_nav_item_current_page_id(items: list[NavItem]) -> str | None:
    ns_tourney_index_url = url_for('netsession_tourney.index')
    ns_tourney_prefix = (
        ns_tourney_index_url.rstrip('/')
        if ns_tourney_index_url != '/'
        else '/'
    )

    for item in items:
        if (
            item.target_type == NavItemTargetType.endpoint
            and item.target == 'netsession_tourney.index'
        ):
            return item.current_page_id

        if item.target_type != NavItemTargetType.url:
            continue

        target = item.target.strip()
        if not target:
            continue

        target_path = urlsplit(target).path if '://' in target else target
        if target_path and not target_path.startswith('/'):
            target_path = '/' + target_path

        target_normalized = (
            target_path.rstrip('/') if target_path != '/' else '/'
        )
        if target_normalized == ns_tourney_prefix:
            return item.current_page_id

    return None


def _get_categories_with_tournaments(categories, tournaments):
    categories_sorted = sorted(categories, key=lambda category: category.position)
    tournaments_by_category_id = defaultdict(list)
    for tournament in tournaments:
        tournaments_by_category_id[tournament.category_id].append(tournament)

    categories_with_tournaments = []
    for category in categories_sorted:
        tournaments_in_category = tournaments_by_category_id.pop(category.id, [])
        if tournaments_in_category:
            categories_with_tournaments.append((category, tournaments_in_category))

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


def _render_tournament_rule_template_body_html(
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


def _build_slot_score_payload(slots, points_by_slot_no: dict[int, int]) -> dict:
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


def _build_overview_stage_type_label(stages) -> str:
    builder_main_stage = next(
        (
            stage
            for stage in sorted(stages, key=lambda item: item.order_no)
            if (stage.settings or {}).get('builder_kind') == 'stage_builder_v1'
            and (stage.settings or {}).get('builder_role') == 'main'
        ),
        None,
    )
    if builder_main_stage is None:
        primary_stage = stages[0] if stages else None
        return stage_type_display_name(
            primary_stage.type if primary_stage else None
        )

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


def format_timeline_action(entry):
    action = entry['action']
    if action == 'tournament_published':
        return gettext('Turnier ist jetzt live.')
    if action == 'tournament_closed':
        return gettext('Turnier wurde beendet.')
    if action == 'tournament_canceled':
        return gettext('Turnier wurde abgesagt.')
    if action == 'match_ready':
        return gettext('Match ist spielbereit.')
    if action == 'flatout2_host_assigned':
        return gettext('Du wurdest als FlatOut-2-Host ausgewählt.')
    if action == 'result_reported':
        return gettext('Ergebnis übermittelt.')
    if action == 'match_rescheduled':
        return gettext('Match-Zeit wurde geändert.')
    if action == 'match_disputed':
        return gettext('Ein Konflikt wurde gemeldet.')
    if action == 'match_needs_admin_review':
        return gettext('Match wartet auf Admin-Prüfung.')
    if action == 'result_confirmation_timed_out':
        return gettext(
            'Bestätigungsfrist abgelaufen, Match wartet auf Admin-Prüfung.'
        )

    return action.replace('_', ' ')
