"""
byceps.services.netsession_tourney.blueprints.site.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from flask import (
    abort,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import format_datetime, get_locale, gettext
from markupsafe import Markup

from byceps.services.external_accounts import external_accounts_service
from byceps.services.party.models import PartyID
from byceps.services.site_navigation import site_navigation_service
from byceps.services.site_navigation.models import NavItem, NavItemTargetType
from byceps.services.ticketing import ticket_service
from byceps.services.user import user_service
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.l10n import get_default_locale
from byceps.util.views import login_required, redirect_to

from ...browser_push_service import (
    disable_browser_push_subscription,
    get_browser_push_public_key_for_party,
    has_active_browser_push_subscription_for_user,
    is_browser_push_enabled_for_party,
    upsert_browser_push_subscription,
)
from ...discord_dm_service import (
    disable_discord_dm_subscription,
    has_active_discord_dm_subscription_for_user,
    is_discord_dm_enabled_for_party,
    upsert_discord_dm_subscription,
)
from ...double_grand_final import get_match_results
from ...enum_labels import stage_type_display_name
from ...flatout2 import get_flatout2_mode_label
from ...forms import (
    MatchChatMessageForm,
    MatchScoreReportForm,
    TeamCreationForm,
    TeamJoinForm,
    TeamMemberAddForm,
)
from ...match_chat_service import (
    can_user_access_match_chat,
    get_match_chat_messages,
    post_match_chat_message,
)
from ...match_queries import (
    find_match_for_tournament,
    get_match_slots,
    get_match_slots_for_match,
    get_match_timeline_entries,
    get_matches_for_tournament,
    get_open_matches_for_party,
)
from ...models import (
    MatchState,
    ParticipantType,
    RegistrationMode,
    StageType,
    TeamMemberRole,
    TournamentMode,
    TournamentRuleTemplate,
    TournamentStatus,
)
from ...participant_admin_service import (
    get_active_participant_counts_for_tournaments,
    get_participants_by_ids,
)
from ...registration_service import deregister_user, register_user
from ...registration_validation import get_team_members_for_participants
from ...result_report_mode import is_stage_result_reporting_admin_only
from ...result_service import report_result
from ...team_captain_service import (
    create_team_for_captain,
    set_managed_team_ready_state,
    update_managed_team_for_captain,
)
from ...team_invite_service import (
    get_team_invite_code_for_manager,
    join_team_by_invite_code,
    regenerate_team_invite_code_for_manager,
)
from ...team_logo_uploads import (
    upload_logo_for_managed_team,
    upload_logo_for_new_team,
)
from ...team_member_service import (
    add_team_member_by_captain,
    assign_team_captain_by_captain,
    remove_team_member_by_captain,
)
from ...tournament_admin_service import get_tournament_admin_user_ids
from ...tournament_category_service import get_tournament_categories_for_party
from ...tournament_prize_service import get_tournament_prizes_for_tournament
from ...tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
    get_user_active_participation_tournament_ids,
)
from ...tournament_rule_template_service import (
    find_tournament_rule_template_by_slug_for_party,
)
from ...tournament_service import (
    find_tournament_by_slug_for_party,
    get_tournaments_for_party,
)
from . import routes_checkin
from .body_rendering import (
    render_formatted_body_html as _render_formatted_body_html,
)
from .bracket_helpers import _build_bracket_sections, build_bracket_data
from .builder_display_helpers import (
    _build_builder_stage_summary_lines,
    _get_builder_main_display_stages,
    _get_materialized_builder_round_robin_group_stages,
    _select_matches_for_public_bracket,
)
from .builder_helpers import _get_materialized_builder_container_stages
from .elimination_ranking import rank_by_elimination
from .match_helpers import (
    _build_match_labels,
    _build_skipped_double_grand_final_match_ids,
    _build_slot_scores_by_match_id,
    _get_or_create_idempotency_key,
    _parse_slot_scores,
)
from .match_state_labels import open_class_name, open_label, register_filters
from .presentation_helpers import (
    _get_stage_duration_minutes,
    _select_builder_stage_section,
)
from .ranking_helpers import (
    _are_all_rankable_matches_completed,
    _build_ffa_ranking_rows,
    _build_flatout2_ranking_rows,
    _build_ranking_rows,
    _has_rankable_results,
)
from .round_robin_groups_display import add_round_robin_groups
from .stage_filters import (
    _is_ffa_scoring_stage,
    _is_ffa_single_elimination_stage,
    _is_flatout2_stage,
    _uses_only_ffa_scoring_stages,
    _uses_only_ffa_simple_stages,
    _uses_only_ffa_single_elimination_stages,
    _uses_only_flatout2_stages,
    _uses_only_round_based_duel_stages,
    _uses_only_swiss_stages,
)
from .stage_render_helpers import (
    _build_builder_main_stage_bracket_sections,
    _build_builder_main_stage_match_sections,
    _build_builder_preliminary_match_sections,
    _build_ffa_match_detail_rows,
    _build_ffa_match_sections,
    _build_ffa_single_elimination_bracket_sections,
    _build_match_overview_sections,
    _build_team_history_rows,
    _get_ffa_placement_by_slot_no,
)
from .stage_tabs import build_stage_tab_rows
from .swiss_public_rendering import _build_swiss_bracket_sections
from .timetable_helpers import _build_party_timetable
from .user_state_helpers import (
    _build_current_user_overview_match_rows,
    _build_registration_state,
    _can_user_report_match_result,
    _format_open_match_participant_name,
    _format_team_member_role_label,
    _get_captain_team_for_current_user,
    _get_current_user_coin_balance,
    _get_current_user_tournament_membership,
    _get_party_coin_settings,
    _get_registration_state_for_tournament,
    _get_seat_data_by_user_id,
    _get_user_registered_tournament_ids,
    _is_match_involving_user,
)


blueprint = create_blueprint('netsession_tourney', __name__)
register_filters(blueprint)
routes_checkin.register(blueprint, lambda slug: _get_tournament_or_404(slug))


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


def _get_suggested_screen_names_for_party(party_id: PartyID) -> list[str]:
    user_ids = ticket_service.get_ticket_users_for_party(party_id)
    users = user_service.get_users(user_ids)

    return sorted(
        {
            user.screen_name
            for user in users
            if user.screen_name and not getattr(user, 'deleted', False)
        },
        key=str.lower,
    )


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


@blueprint.get('')
@blueprint.get('/')
@templated
def index():
    """List tournaments for this party."""
    if not g.party:
        abort(404)

    status_param = request.args.get('status')
    mode_param = request.args.get('mode')
    game = request.args.get('game')

    status = _parse_status_filter(status_param)
    mode = _parse_mode_filter(mode_param)

    tournaments = get_tournaments_for_party(
        g.party.id,
        status=status,
        mode=mode,
        game=game,
        visible_on_site=True,
    )
    categories = get_tournament_categories_for_party(g.party.id)
    categories_with_tournaments, uncategorized_tournaments = (
        _get_categories_with_tournaments(categories, tournaments)
    )

    tournament_ids = {tournament.id for tournament in tournaments}
    active_participant_counts = get_active_participant_counts_for_tournaments(
        g.party.id, tournament_ids
    )
    user_registered_tournament_ids = _get_user_registered_tournament_ids(
        g.party.id, tournament_ids
    )
    registration_states_by_tournament_id = {
        tournament.id: _build_registration_state(
            tournament,
            active_participant_counts.get(tournament.id, 0),
            tournament.id in user_registered_tournament_ids,
        )
        for tournament in tournaments
    }
    public_statuses_by_tournament_id = {
        tournament.id: _build_public_tournament_status(tournament)
        for tournament in tournaments
    }
    coin_settings = _get_party_coin_settings()
    browser_push_enabled = is_browser_push_enabled_for_party(g.party.id)
    discord_dm_enabled = is_discord_dm_enabled_for_party(g.party.id)
    browser_push_prompt_enabled = False
    browser_push_vapid_public_key = None
    browser_push_has_subscription = False
    discord_dm_prompt_enabled = False
    discord_dm_has_subscription = False
    discord_account_connected = False
    if g.user.authenticated:
        involved_tournament_ids = get_user_active_participation_tournament_ids(
            g.party.id,
            tournament_ids,
            g.user.id,
        )
        has_involved_tournaments = bool(involved_tournament_ids)
        browser_push_prompt_enabled = (
            browser_push_enabled and has_involved_tournaments
        )
        if discord_dm_enabled:
            discord_account_connected = (
                external_accounts_service.find_connected_external_account_for_user_and_service(
                    g.user.id, 'discord'
                )
                is not None
            )
            discord_dm_has_subscription = (
                has_active_discord_dm_subscription_for_user(
                    g.party.id, g.user.id
                )
            )
        discord_dm_prompt_enabled = (
            discord_dm_enabled
            and (
                has_involved_tournaments
                or discord_dm_has_subscription
            )
        )
        if browser_push_prompt_enabled:
            browser_push_vapid_public_key = get_browser_push_public_key_for_party(
                g.party.id
            )
            browser_push_has_subscription = (
                has_active_browser_push_subscription_for_user(
                    g.party.id, g.user.id
                )
            )
    current_page_id = _get_main_nav_current_page_id()
    notification_prompt_enabled = (
        browser_push_prompt_enabled or discord_dm_prompt_enabled
    )

    return {
        'tournaments': tournaments,
        'categories_with_tournaments': categories_with_tournaments,
        'uncategorized_tournaments': uncategorized_tournaments,
        'registration_states_by_tournament_id': registration_states_by_tournament_id,
        'public_statuses_by_tournament_id': public_statuses_by_tournament_id,
        'status_filter': status_param or '',
        'mode_filter': mode_param or '',
        'game_filter': game or '',
        'notification_prompt_enabled': notification_prompt_enabled,
        'browser_push_prompt_enabled': browser_push_prompt_enabled,
        'browser_push_vapid_public_key': browser_push_vapid_public_key,
        'browser_push_has_subscription': browser_push_has_subscription,
        'discord_dm_prompt_enabled': discord_dm_prompt_enabled,
        'discord_dm_has_subscription': discord_dm_has_subscription,
        'discord_account_connected': discord_account_connected,
        'coin_settings': coin_settings,
        'current_page': current_page_id,
        'current_global_subnav_page': 'ns_tourney_index',
        'subnav_menu_id': _find_netsession_tourney_subnav_menu_id(
            'netsession_tourney'
        ),
    }


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


@blueprint.get('/browser-push-sw.js')
def browser_push_service_worker():
    response = current_app.make_response(
        render_template('site/netsession_tourney/browser_push_sw.js')
    )
    response.mimetype = 'application/javascript'
    scope = url_for('netsession_tourney.index')
    if not scope.endswith('/'):
        scope += '/'
    response.headers['Service-Worker-Allowed'] = scope
    return response


@blueprint.post('/browser-push/subscribe')
@login_required
def browser_push_subscribe():
    if not g.party or not is_browser_push_enabled_for_party(g.party.id):
        return jsonify({'error': 'disabled'}), 403

    payload = request.get_json(silent=True) or {}
    endpoint = str(payload.get('endpoint') or '').strip()
    keys = payload.get('keys') or {}
    endpoint_p256dh = str(keys.get('p256dh') or '').strip()
    endpoint_auth = str(keys.get('auth') or '').strip()

    result = upsert_browser_push_subscription(
        g.party.id,
        g.user.id,
        endpoint=endpoint,
        endpoint_p256dh=endpoint_p256dh,
        endpoint_auth=endpoint_auth,
        user_agent=request.headers.get('User-Agent'),
    )
    if result.is_err():
        return jsonify({'error': result.unwrap_err()}), 400

    return jsonify({'ok': True})


@blueprint.post('/browser-push/unsubscribe')
@login_required
def browser_push_unsubscribe():
    if not g.party:
        return jsonify({'error': 'missing_party'}), 404

    payload = request.get_json(silent=True) or {}
    endpoint = str(payload.get('endpoint') or '').strip()
    if not endpoint:
        return jsonify({'error': 'missing_endpoint'}), 400

    disable_browser_push_subscription(
        g.party.id,
        g.user.id,
        endpoint=endpoint,
    )
    return jsonify({'ok': True})


@blueprint.post('/discord-dm/subscribe')
@login_required
def discord_dm_subscribe():
    if not g.party or not is_discord_dm_enabled_for_party(g.party.id):
        return jsonify({'error': 'disabled'}), 403

    connected_account = (
        external_accounts_service.find_connected_external_account_for_user_and_service(
            g.user.id, 'discord'
        )
    )
    if connected_account is None or not connected_account.external_id:
        return jsonify({'error': 'discord_not_connected'}), 400

    tournament_ids = [tournament.id for tournament in get_tournaments_for_party(g.party.id)]
    involved_tournament_ids = get_user_active_participation_tournament_ids(
        g.party.id,
        tournament_ids,
        g.user.id,
    )
    if not involved_tournament_ids:
        return jsonify({'error': 'not_eligible'}), 403

    result = upsert_discord_dm_subscription(g.party.id, g.user.id)
    if result.is_err():
        return (
            jsonify(
                {
                    'error': 'subscribe_failed',
                    'message': result.unwrap_err(),
                }
            ),
            400,
        )

    return jsonify({'ok': True})


@blueprint.post('/discord-dm/unsubscribe')
@login_required
def discord_dm_unsubscribe():
    if not g.party:
        return jsonify({'error': 'missing_party'}), 404

    disable_discord_dm_subscription(g.party.id, g.user.id)
    return jsonify({'ok': True})


@blueprint.get('/open-matches')
@templated
def open_matches():
    """Show open matches."""
    if not g.party:
        abort(404)

    matches = get_open_matches_for_party(g.party.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    tournament_ids = {match.tournament_id for match in matches}
    participant_ids = {
        slot.participant_id
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.participant_id
    }

    participants = get_participants_for_tournament_indexed_by_id(
        g.party.id, participant_ids
    )
    members_by_participant_id = get_team_members_for_participants(participant_ids)
    tournaments_by_id = {
        tournament.id: tournament
        for tournament in get_tournaments_for_party(g.party.id)
        if tournament.id in tournament_ids
    }
    stages_by_tournament_id = {
        tournament_id: {
            stage.id: stage
            for stage in get_stages_for_tournament(g.party.id, tournament_id)
        }
        for tournament_id in tournament_ids
    }

    match_labels_by_id = {}
    matches_by_tournament_id: dict[UUID, list] = defaultdict(list)
    for match in matches:
        matches_by_tournament_id[match.tournament_id].append(match)

    for tournament_id, tournament_matches in matches_by_tournament_id.items():
        match_labels_by_id.update(
            _build_match_labels(
                tournament_matches,
                {
                    match.id: slots_by_match_id.get(match.id, [])
                    for match in tournament_matches
                },
                stages_by_tournament_id.get(tournament_id, {}),
            )
        )

    current_user = getattr(g, 'user', None)
    current_user_id = (
        current_user.id
        if current_user is not None and current_user.authenticated
        else None
    )

    rows = []
    for match in matches:
        tournament = tournaments_by_id.get(match.tournament_id)
        if tournament is None:
            continue

        stage = stages_by_tournament_id.get(match.tournament_id, {}).get(
            match.stage_id
        )
        slots = sorted(slots_by_match_id.get(match.id, []), key=lambda slot: slot.slot_no)
        participant_names = [
            _format_open_match_participant_name(
                slot, participants_by_id=participants
            )
            for slot in slots
        ]
        is_my_match = (
            current_user_id is not None
            and _is_match_involving_user(
                current_user_id,
                slots,
                participants_by_id=participants,
                members_by_participant_id=members_by_participant_id,
            )
        )

        rows.append(
            {
                'match': match,
                'url': url_for(
                    'netsession_tourney.view_match',
                    slug=tournament.slug,
                    match_id=match.id,
                ),
                'match_label': match_labels_by_id.get(
                    match.id, f'{gettext("Match")} #{match.match_no}'
                ),
                'participants_label': ' vs '.join(participant_names),
                'tournament_title': tournament.title,
                'stage_name': stage.name if stage is not None else gettext('Stage'),
                'state_label': open_label(match.state),
                'state_class_name': open_class_name(match.state),
                'scheduled_label': (
                    format_datetime(match.scheduled_at, 'short')
                    if match.scheduled_at is not None
                    else gettext('Nicht geplant')
                ),
                'is_my_match': is_my_match,
                'is_scheduled': match.scheduled_at is not None,
            }
        )

    rows.sort(
        key=lambda row: (
            not row['is_my_match'],
            row['match'].scheduled_at or datetime.max,
            row['tournament_title'].lower(),
            row['stage_name'].lower(),
            row['match'].round_no,
            row['match'].match_no,
        )
    )

    current_page_id = _get_main_nav_current_page_id()

    return {
        'rows': rows,
        'current_page': current_page_id,
        'current_global_subnav_page': 'ns_tourney_open_matches',
        'subnav_menu_id': _find_netsession_tourney_subnav_menu_id(
            'netsession_tourney_open_matches',
            'netsession_tourney',
        ),
    }


@blueprint.get('/timetable')
@templated
def timetable():
    """Show a cross-tournament timetable for this party."""
    if not g.party:
        abort(404)

    current_page_id = _get_main_nav_current_page_id()
    selected_day_iso = (request.args.get('day') or '').strip() or None

    return {
        'timetable': _build_party_timetable(
            g.party, selected_day_iso=selected_day_iso
        ),
        'current_page': current_page_id,
        'current_global_subnav_page': 'ns_tourney_timetable',
        'subnav_menu_id': _find_netsession_tourney_subnav_menu_id(
            'netsession_tourney_timetable',
            'netsession_tourney',
        ),
    }


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


@blueprint.get('/<slug>')
@templated
def view_overview(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    hide_bracket_tab = _uses_only_ffa_simple_stages(stages, [])
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, [])
    stage_type_label = _build_overview_stage_type_label(stages)

    participants = get_participants_for_tournament(g.party.id, tournament.id)
    members_by_participant_id = get_team_members_for_participants(
        {participant.id for participant in participants}
    )
    admin_user_ids = get_tournament_admin_user_ids(tournament.id)
    participant_user_ids = {
        participant.user_id for participant in participants if participant.user_id
    }
    member_user_ids = {
        member.user_id
        for members in members_by_participant_id.values()
        for member in members
    }
    users_by_id = user_service.get_users_indexed_by_id(
        participant_user_ids | member_user_ids | admin_user_ids,
        include_avatars=True,
    )
    admin_users = sorted(
        (users_by_id[user_id] for user_id in admin_user_ids if user_id in users_by_id),
        key=lambda user: user.screen_name.lower(),
    )
    registration_state = _get_registration_state_for_tournament(tournament)
    coin_settings = _get_party_coin_settings()
    current_user_coin_balance = _get_current_user_coin_balance()
    captain_team = _get_captain_team_for_current_user(tournament.id)
    current_user_tournament_membership = _get_current_user_tournament_membership(
        participants,
        members_by_participant_id,
    )
    current_user_team_role_label = None
    current_user_team_role_icon_id = None
    current_user_overview_matches = []
    if current_user_tournament_membership is not None:
        current_user_member = current_user_tournament_membership['member']
        if current_user_member is not None:
            current_user_team_role_label = _format_team_member_role_label(
                current_user_member.role
            )
            current_user_team_role_icon_id = (
                'crown'
                if current_user_member.role == TeamMemberRole.captain
                else 'controller'
            )

        matches = get_matches_for_tournament(g.party.id, tournament.id)
        slots_by_match_id = get_match_slots({match.id for match in matches})
        results_by_match_id = get_match_results({match.id for match in matches})
        match_labels_by_id = _build_match_labels(
            matches,
            slots_by_match_id,
            stages_by_id,
        )
        participants_by_id = {
            participant.id: participant for participant in participants
        }
        current_user_overview_matches = _build_current_user_overview_match_rows(
            tournament,
            matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            stages_by_id,
            match_labels_by_id,
            current_user_tournament_membership['participant'].id,
        )
    starts_at_label = (
        (
            f"{format_datetime(tournament.starts_at, 'EEEE')}, "
            f"{format_datetime(tournament.starts_at, 'd. MMMM y')}, "
            f"{format_datetime(tournament.starts_at, 'HH:mm')} Uhr"
        )
        if tournament.starts_at
        else '-'
    )
    starts_at_mobile_lines = (
        (
            (
                f"{format_datetime(tournament.starts_at, 'EEEE')}, "
                f"{format_datetime(tournament.starts_at, 'd.')}"
            ),
            format_datetime(tournament.starts_at, 'MMMM y'),
            f"{format_datetime(tournament.starts_at, 'HH:mm')} Uhr",
        )
        if tournament.starts_at
        else ('-',)
    )
    rule_template = _find_tournament_rule_template(tournament)
    rules_html = _render_tournament_rule_template_body_html(rule_template)
    public_status = _build_public_tournament_status(tournament)
    prizes = get_tournament_prizes_for_tournament(tournament.id)
    prizes_with_html = [
        {
            'position': prize.position,
            'body_html': _render_formatted_body_html(
                prize.body, prize.body_format
            ),
        }
        for prize in prizes
    ]
    preliminary_link_rows = [
        {
            'title': stage.name,
            'url': url_for(
                'netsession_tourney.view_preliminaries',
                slug=tournament.slug,
                stage=str(stage.id),
            ),
        }
        for stage in _get_materialized_builder_round_robin_group_stages(stages)
    ]
    current_page_id = _get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'stage_type_label': stage_type_label,
        'starts_at_label': starts_at_label,
        'starts_at_mobile_lines': starts_at_mobile_lines,
        'admin_users': admin_users,
        'participants': participants,
        'members_by_participant_id': members_by_participant_id,
        'users_by_id': users_by_id,
        'registration_state': registration_state,
        'public_status': public_status,
        'coin_settings': coin_settings,
        'current_user_coin_balance': current_user_coin_balance,
        'captain_team': captain_team,
        'current_user_tournament_membership': current_user_tournament_membership,
        'current_user_team_role_label': current_user_team_role_label,
        'current_user_team_role_icon_id': current_user_team_role_icon_id,
        'current_user_overview_matches': current_user_overview_matches,
        'prizes': prizes_with_html,
        'preliminary_link_rows': preliminary_link_rows,
        'rule_template': rule_template,
        'rules_html': rules_html,
        'hide_bracket_tab': hide_bracket_tab,
        'show_preliminaries_tab': bool(preliminary_link_rows)
        and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


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
    slot_scores_by_match_id = _build_slot_scores_by_match_id(
        matches, slots_by_match_id, results_by_match_id
    )
    match_labels_by_id = _build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    skipped_double_grand_final_match_ids = _build_skipped_double_grand_final_match_ids(
        matches,
        slots_by_match_id,
        results_by_match_id,
        stages_by_id,
    )
    matches_for_bracket = _select_matches_for_public_bracket(stages, matches)
    bracket = build_bracket_data(
        matches_for_bracket, slots_by_match_id, participants_by_id
    )
    bracket_sections = _build_bracket_sections(bracket, match_labels_by_id)
    is_ffa_scoring_tournament = _uses_only_ffa_scoring_stages(stages, matches)
    is_ffa_single_elimination_tournament = (
        _uses_only_ffa_single_elimination_stages(stages, matches)
    )
    is_ffa_match_overview_tournament = (
        is_ffa_scoring_tournament or is_ffa_single_elimination_tournament
    )
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, matches)
    is_swiss_tournament = _uses_only_swiss_stages(stages, matches)
    is_round_based_duel_tournament = _uses_only_round_based_duel_stages(
        stages, matches
    )
    ffa_match_sections = (
        _build_ffa_match_sections(
            matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            users_by_id,
            match_labels_by_id,
            skipped_double_grand_final_match_ids,
            stages_by_id,
        )
        if is_ffa_scoring_tournament and not is_ffa_single_elimination_tournament
        else []
    )
    ffa_single_elimination_bracket_sections = (
        _build_ffa_single_elimination_bracket_sections(
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
        _build_swiss_bracket_sections(
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
        _build_match_overview_sections(
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
    main_builder_display_stages = _get_builder_main_display_stages(stages)
    builder_stage_bracket_sections = (
        _build_builder_main_stage_bracket_sections(
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
        selected_builder_bracket_section = _select_builder_stage_section(
            builder_stage_bracket_sections,
            request.args.get('stage'),
        )
        builder_bracket_tab_rows = build_stage_tab_rows(
            'netsession_tourney.view_bracket',
            tournament.slug,
            builder_stage_bracket_sections,
            selected_builder_bracket_section,
        )

    current_page_id = _get_main_nav_current_page_id()

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
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
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
    match_labels_by_id = _build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    skipped_double_grand_final_match_ids = _build_skipped_double_grand_final_match_ids(
        matches,
        slots_by_match_id,
        results_by_match_id,
        stages_by_id,
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
    slot_scores_by_match_id = _build_slot_scores_by_match_id(
        matches, slots_by_match_id, results_by_match_id
    )
    bracket = build_bracket_data(matches, slots_by_match_id, participants_by_id)
    bracket_sections = _build_bracket_sections(bracket, match_labels_by_id)
    is_ffa_scoring_tournament = _uses_only_ffa_scoring_stages(stages, matches)
    is_ffa_single_elimination_tournament = (
        _uses_only_ffa_single_elimination_stages(stages, matches)
    )
    is_ffa_match_overview_tournament = (
        is_ffa_scoring_tournament or is_ffa_single_elimination_tournament
    )
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, matches)
    match_sections = (
        _build_ffa_match_sections(
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
        else _build_match_overview_sections(
            bracket_sections,
            stages_by_id,
            results_by_match_id,
            slot_scores_by_match_id,
            match_labels_by_id,
            users_by_id,
            skipped_double_grand_final_match_ids,
        )
    )
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, matches)
    main_builder_display_stages = _get_builder_main_display_stages(stages)
    builder_stage_match_sections = (
        _build_builder_main_stage_match_sections(
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
        if bool(main_builder_display_stages)
        and not is_flatout2_tournament
        else []
    )
    selected_builder_match_section = None
    builder_match_tab_rows = []
    if builder_stage_match_sections:
        match_sections = builder_stage_match_sections

    current_page_id = _get_main_nav_current_page_id()

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
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'matches',
    }


@blueprint.get('/<slug>/preliminaries')
@templated('site/netsession_tourney/view_preliminaries')
def view_preliminaries(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    preliminary_container_stages = _get_materialized_builder_container_stages(
        stages, role='preliminary'
    )
    if not preliminary_container_stages:
        return redirect(url_for('netsession_tourney.view_overview', slug=slug))

    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
    stages_by_id = {stage.id: stage for stage in stages}
    match_labels_by_id = _build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    skipped_double_grand_final_match_ids = _build_skipped_double_grand_final_match_ids(
        matches,
        slots_by_match_id,
        results_by_match_id,
        stages_by_id,
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
    slot_scores_by_match_id = _build_slot_scores_by_match_id(
        matches, slots_by_match_id, results_by_match_id
    )

    preliminary_summary_stage = preliminary_container_stages[0]
    preliminary_sections = _build_builder_preliminary_match_sections(
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
    selected_preliminary_section = _select_builder_stage_section(
        preliminary_sections,
        request.args.get('stage'),
    )
    selected_preliminary_ranking_rows = []
    preliminary_ranking_subject_label = gettext('Teilnehmer')
    selected_stage = None
    if selected_preliminary_section is not None:
        selected_stage_id = UUID(selected_preliminary_section['key'])
        selected_stage = stages_by_id.get(selected_stage_id)
        selected_stage_matches = [
            match for match in matches if match.stage_id == selected_stage_id
        ]
        selected_stage_match_ids = {
            match.id for match in selected_stage_matches
        }
        selected_stage_slots_by_match_id = {
            match_id: slots_by_match_id.get(match_id, [])
            for match_id in selected_stage_match_ids
        }
        selected_stage_results_by_match_id = {
            match_id: results_by_match_id.get(match_id)
            for match_id in selected_stage_match_ids
            if match_id in results_by_match_id
        }
        selected_stage_participants = [
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
        if (
            selected_stage_participants
            and all(
                participant.type.value == 'team'
                for participant in selected_stage_participants
            )
        ):
            preliminary_ranking_subject_label = gettext('Team')
        elif (
            selected_stage_participants
            and all(
                participant.user_id is not None
                for participant in selected_stage_participants
            )
        ):
            preliminary_ranking_subject_label = gettext('Spieler')

        if not _is_ffa_single_elimination_stage(selected_stage):
            selected_preliminary_ranking_rows = _build_ranking_rows(
                selected_stage_participants,
                selected_stage_matches,
                selected_stage_slots_by_match_id,
                selected_stage_results_by_match_id,
                stage_type=selected_stage.type if selected_stage is not None else None,
            )
    preliminary_tab_rows = build_stage_tab_rows(
        'netsession_tourney.view_preliminaries',
        tournament.slug,
        preliminary_sections,
        selected_preliminary_section,
    )
    preliminary_summary_lines = (
        _build_builder_stage_summary_lines(preliminary_summary_stage, stages)
        if preliminary_summary_stage is not None
        else []
    )

    current_page_id = _get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'selected_preliminary_section': selected_preliminary_section,
        'selected_preliminary_stage_type': (
            selected_stage.type if selected_stage is not None else None
        ),
        'selected_preliminary_is_ffa_stage': (
            _is_ffa_single_elimination_stage(selected_stage)
            if selected_stage is not None
            else False
        ),
        'selected_preliminary_ranking_rows': selected_preliminary_ranking_rows,
        'preliminary_ranking_subject_label': preliminary_ranking_subject_label,
        'preliminary_tab_rows': preliminary_tab_rows,
        'preliminary_summary_lines': preliminary_summary_lines,
        'users_by_id': users_by_id,
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': True,
        'current_page': current_page_id,
        'current_tournament_page': 'preliminaries',
    }


@blueprint.get('/<slug>/ranking')
@templated
def view_ranking(slug):
    tournament = _get_tournament_or_404(slug)
    participants = get_participants_for_tournament(g.party.id, tournament.id)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
    user_ids = {
        participant.user_id
        for participant in participants
        if participant.user_id is not None
    }
    users_by_id = user_service.get_users_indexed_by_id(user_ids)
    if participants and all(participant.type.value == 'team' for participant in participants):
        ranking_subject_label = gettext('Team')
    elif participants and all(participant.user_id is not None for participant in participants):
        ranking_subject_label = gettext('Spieler')
    else:
        ranking_subject_label = gettext('Teilnehmer')

    is_ffa_scoring_tournament = _uses_only_ffa_scoring_stages(stages, matches)
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, matches)
    is_swiss_tournament = _uses_only_swiss_stages(stages, matches)
    ranking = (
        _build_ffa_ranking_rows(
            participants,
            matches,
            slots_by_match_id,
            results_by_match_id,
            {stage.id: stage for stage in stages},
        )
        if is_ffa_scoring_tournament
        else _build_flatout2_ranking_rows(
            participants,
            matches,
            slots_by_match_id,
            results_by_match_id,
            _get_ffa_placement_by_slot_no,
        )
        if is_flatout2_tournament
        else _build_ranking_rows(
            participants,
            matches,
            slots_by_match_id,
            results_by_match_id,
            stage_type=StageType.swiss if is_swiss_tournament else None,
        )
    )
    ranking = rank_by_elimination(
        ranking, stages, matches, slots_by_match_id, results_by_match_id
    )
    has_ranking_data = _has_rankable_results(
        matches, slots_by_match_id, results_by_match_id
    )
    is_final_ranking = (
        has_ranking_data
        and _are_all_rankable_matches_completed(matches, slots_by_match_id)
    )

    current_page_id = _get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'ranking_rows': ranking,
        'has_ranking_data': has_ranking_data,
        'is_final_ranking': is_final_ranking,
        'users_by_id': users_by_id,
        'ranking_subject_label': ranking_subject_label,
        'is_ffa_scoring_tournament': is_ffa_scoring_tournament,
        'is_flatout2_tournament': is_flatout2_tournament,
        'is_swiss_tournament': is_swiss_tournament,
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'ranking',
    }


@blueprint.get('/<slug>/participants')
@templated
def view_participants(slug):
    tournament = _get_tournament_or_404(slug)
    participants = get_participants_for_tournament(g.party.id, tournament.id)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, [])
    members_by_participant_id = get_team_members_for_participants(
        {participant.id for participant in participants}
    )
    registration_state = _get_registration_state_for_tournament(tournament)
    member_user_ids = {
        member.user_id
        for members in members_by_participant_id.values()
        for member in members
    }
    users_by_id = user_service.get_users_indexed_by_id(member_user_ids)
    captain_team = _get_captain_team_for_current_user(tournament.id)
    current_page_id = _get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'participants': participants,
        'members_by_participant_id': members_by_participant_id,
        'users_by_id': users_by_id,
        'captain_team': captain_team,
        'registration_state': registration_state,
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'participants',
    }


def _build_team_view_context(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    participants_by_id = get_participants_by_ids(g.party.id, {participant_id})
    team = participants_by_id.get(participant_id)
    if team is None or team.tournament_id != tournament.id:
        abort(404)
    if team.type != ParticipantType.team:
        abort(404)

    members_by_participant_id = get_team_members_for_participants({participant_id})
    members = members_by_participant_id.get(participant_id, [])
    users_by_id = user_service.get_users_indexed_by_id(
        {member.user_id for member in members},
        include_avatars=True,
    )
    role_sort_order = {'captain': 0, 'player': 1, 'substitute': 2}
    members = sorted(
        members,
        key=lambda member: (
            role_sort_order.get(member.role.value, 9),
            (
                users_by_id.get(member.user_id).screen_name.lower()
                if users_by_id.get(member.user_id)
                else str(member.user_id)
            ),
        ),
    )
    seat_data_by_user_id = _get_seat_data_by_user_id(
        g.party.id, {member.user_id for member in members}
    )
    current_user = getattr(g, 'user', None)
    can_manage_team = (
        current_user is not None
        and current_user.authenticated
        and team.manager_user_id == current_user.id
    )
    team_invite_code = None
    if can_manage_team:
        invite_code_result = get_team_invite_code_for_manager(
            g.party.id,
            tournament.id,
            team.id,
            current_user.id,
        )
        if invite_code_result.is_ok():
            team_invite_code = invite_code_result.unwrap()

    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    match_labels_by_id = _build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    participant_ids = {
        slot.participant_id
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.participant_id
    }
    participants_lookup = get_participants_by_ids(g.party.id, participant_ids)
    team_history = _build_team_history_rows(
        team,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_lookup,
        match_labels_by_id,
        stages_by_id,
    )
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, matches)

    current_page_id = _get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'team': team,
        'members': members,
        'users_by_id': users_by_id,
        'seat_data_by_user_id': seat_data_by_user_id,
        'can_manage_team': can_manage_team,
        'team_invite_code': team_invite_code,
        'team_creation_form': TeamCreationForm(data={'name': team.name}),
        'team_member_add_form': TeamMemberAddForm(),
        'suggested_screen_names': _get_suggested_screen_names_for_party(
            g.party.id
        ),
        'team_history': team_history,
        'is_ffa_scoring_tournament': _uses_only_ffa_scoring_stages(
            stages, matches
        ),
        'is_flatout2_tournament': _uses_only_flatout2_stages(stages, matches),
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


def _build_player_view_context(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    participants_by_id = get_participants_by_ids(g.party.id, {participant_id})
    player = participants_by_id.get(participant_id)
    if player is None or player.tournament_id != tournament.id:
        abort(404)
    if player.type != ParticipantType.user:
        abort(404)
    if player.user_id is None:
        abort(404)

    player_user = user_service.get_user(player.user_id, include_avatar=True)
    seat_data_by_user_id = _get_seat_data_by_user_id(
        g.party.id, {player.user_id}
    )
    seat_data = seat_data_by_user_id.get(player.user_id)

    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({match.id for match in matches})
    results_by_match_id = get_match_results({match.id for match in matches})
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    match_labels_by_id = _build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    participant_ids = {
        slot.participant_id
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.participant_id
    }
    participants_lookup = get_participants_by_ids(g.party.id, participant_ids)
    player_history = _build_team_history_rows(
        player,
        matches,
        slots_by_match_id,
        results_by_match_id,
        participants_lookup,
        match_labels_by_id,
        stages_by_id,
    )
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, matches)

    current_page_id = _get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'player': player,
        'player_user': player_user,
        'seat_data': seat_data,
        'player_history': player_history,
        'is_ffa_scoring_tournament': _uses_only_ffa_scoring_stages(
            stages, matches
        ),
        'is_flatout2_tournament': _uses_only_flatout2_stages(stages, matches),
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


@blueprint.get('/<slug>/teams/<uuid:participant_id>')
@templated
def view_team(slug, participant_id):
    context = _build_team_view_context(slug, participant_id)
    context['manage_page'] = False
    return context


@blueprint.get('/<slug>/teams/<uuid:participant_id>/edit')
@login_required
@templated('site/netsession_tourney/view_team')
def edit_team(slug, participant_id):
    context = _build_team_view_context(slug, participant_id)
    is_manageable = (
        context['can_manage_team']
        and context['tournament'].status
        in {TournamentStatus.draft, TournamentStatus.live}
    )
    if not is_manageable:
        flash_error(gettext('Team kann aktuell nicht bearbeitet werden.'))
        return redirect_to(
            '.view_team', slug=slug, participant_id=participant_id
        )

    context['manage_page'] = True
    return context


@blueprint.get('/<slug>/players/<uuid:participant_id>')
@templated('site/netsession_tourney/view_player')
def view_player(slug, participant_id):
    return _build_player_view_context(slug, participant_id)


@blueprint.get('/<slug>/matches/<uuid:match_id>')
@templated
def view_match(slug, match_id):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    match = find_match_for_tournament(g.party.id, tournament.id, match_id)
    if match is None:
        abort(404)

    matches = get_matches_for_tournament(g.party.id, tournament.id)
    slots_by_match_id = get_match_slots({item.id for item in matches})
    results_by_match_id = get_match_results({item.id for item in matches})
    match_labels_by_id = _build_match_labels(
        matches,
        slots_by_match_id,
        stages_by_id,
    )
    skipped_double_grand_final_match_ids = _build_skipped_double_grand_final_match_ids(
        matches,
        slots_by_match_id,
        results_by_match_id,
        stages_by_id,
    )
    slots = sorted(
        get_match_slots_for_match(match.id), key=lambda slot: slot.slot_no
    )

    bye_slot_ids = set()
    for slot in slots:
        is_explicit_bye = (
            slot.participant_id is None
            and slot.source_match_slot_id is None
            and match.state == MatchState.completed
        )
        if is_explicit_bye:
            bye_slot_ids.add(slot.id)

    has_bye_slot = bool(bye_slot_ids)
    participants_by_id = get_participants_for_tournament_indexed_by_id(
        g.party.id,
        {slot.participant_id for slot in slots if slot.participant_id},
    )
    result = results_by_match_id.get(match.id)
    slot_scores = _parse_slot_scores(slots, result)
    timeline_entries = get_match_timeline_entries(
        g.party.id, tournament.id, match.id
    )
    timeline_actor_ids = {
        entry['actor_user_id'] for entry in timeline_entries if entry['actor_user_id']
    }
    chat_messages = get_match_chat_messages(g.party.id, tournament.id, match.id)
    chat_actor_ids = {message.actor_user_id for message in chat_messages}
    members_by_participant_id = get_team_members_for_participants(
        set(participants_by_id.keys())
    )
    chat_team_by_actor_user_id = {}
    for participant in participants_by_id.values():
        if participant.type is not ParticipantType.team:
            continue

        if participant.manager_user_id is not None:
            chat_team_by_actor_user_id.setdefault(
                participant.manager_user_id, participant
            )

        for member in members_by_participant_id.get(participant.id, []):
            chat_team_by_actor_user_id.setdefault(member.user_id, participant)

    users_by_id = user_service.get_users_indexed_by_id(
        timeline_actor_ids | chat_actor_ids, include_avatars=True
    )
    activity_items = [
        {
            'kind': 'event',
            'created_at': entry['created_at'],
            'entry': entry,
        }
        for entry in timeline_entries
    ] + [
        {
            'kind': 'chat',
            'created_at': message.created_at,
            'message': message,
        }
        for message in chat_messages
    ]
    activity_items.sort(key=lambda item: item['created_at'])

    can_report = False
    can_chat = False
    user = getattr(g, 'user', None)
    if user is not None and user.authenticated:
        is_admin_or_referee = user.has_permission(
            'netsession_tourney.manage'
        ) or user.has_permission('netsession_tourney.admin')
        can_report = _can_user_report_match_result(
            user.id,
            tournament,
            match,
            slots,
            participants_by_id,
            is_admin_or_referee=False,
            admin_only=is_stage_result_reporting_admin_only(
                stages_by_id.get(match.stage_id)
            ),
        )
        can_chat = can_user_access_match_chat(
            g.party.id,
            tournament.id,
            match.id,
            user.id,
            is_admin_or_referee=is_admin_or_referee,
        )

    is_skipped_double_grand_final = match.id in skipped_double_grand_final_match_ids
    if is_skipped_double_grand_final:
        can_report = False

    stage = stages_by_id.get(match.stage_id)
    is_ffa_scoring_match = _is_ffa_scoring_stage(stage)
    is_flatout2_match = _is_flatout2_stage(stage)
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, matches)
    ffa_match_rows = []
    current_host_participant_id = ''
    flatout2_round_races = []
    if is_ffa_scoring_match or is_flatout2_match:
        can_report = False
        ffa_match_rows = _build_ffa_match_detail_rows(
            slots,
            participants_by_id,
            users_by_id,
            result,
            slot_scores,
            is_flatout2_match=is_flatout2_match,
        )
    if is_flatout2_match and stage is not None:
        current_host_participant_id = str(
            (match.settings or {}).get('host_participant_id') or ''
        ).strip()
        raw_flatout2_round_races = (match.settings or {}).get(
            'flatout2_races'
        ) or []
        flatout2_round_races = [
            {
                **race,
                'mode_label': get_flatout2_mode_label(
                    str(race.get('mode') or '').strip() or 'single_race'
                ),
            }
            for race in raw_flatout2_round_races
            if isinstance(race, dict)
        ]
    current_host_name = next(
        (
            row['name']
            for row in ffa_match_rows
            if row.get('participant') is not None
            and str(row['participant'].id) == current_host_participant_id
        ),
        None,
    )
    stage_duration_minutes = _get_stage_duration_minutes(stage)
    match_end_at = (
        match.scheduled_at + timedelta(minutes=stage_duration_minutes)
        if match.scheduled_at is not None and stage_duration_minutes is not None
        else None
    )

    current_page_id = _get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'match': match,
        'match_label': match_labels_by_id.get(
            match.id, f'{gettext("Match")} #{match.match_no}'
        ),
        'stage': stage,
        'is_ffa_scoring_match': is_ffa_scoring_match,
        'is_flatout2_match': is_flatout2_match,
        'current_host_participant_id': current_host_participant_id,
        'current_host_name': current_host_name,
        'flatout2_round_races': flatout2_round_races,
        'ffa_match_rows': ffa_match_rows,
        'match_end_at': match_end_at,
        'slots': slots,
        'bye_slot_ids': bye_slot_ids,
        'has_bye_slot': has_bye_slot,
        'slot_scores': slot_scores,
        'participants_by_id': participants_by_id,
        'result': result,
        'timeline_entries': timeline_entries,
        'chat_messages': chat_messages,
        'activity_items': activity_items,
        'users_by_id': users_by_id,
        'chat_team_by_actor_user_id': chat_team_by_actor_user_id,
        'format_timeline_action': format_timeline_action,
        'report_form': MatchScoreReportForm(),
        'chat_form': MatchChatMessageForm(),
        'can_report': can_report,
        'can_chat': can_chat,
        'is_skipped_double_grand_final': is_skipped_double_grand_final,
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'matches',
    }


@blueprint.get('/<slug>/rules')
@templated
def view_rules(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, [])
    rule_template = _find_tournament_rule_template(tournament)
    if rule_template is None:
        return redirect(url_for('netsession_tourney.view_overview', slug=slug))
    rules_html = _render_tournament_rule_template_body_html(rule_template)
    current_page_id = _get_main_nav_current_page_id()
    return {
        'tournament': tournament,
        'rule_template': rule_template,
        'rules_html': rules_html,
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'rules',
    }


@blueprint.post('/<slug>/register')
@login_required
def register(slug):
    tournament = _get_tournament_or_404(slug)

    user = user_service.get_user(g.user.id)
    result = register_user(g.party.id, tournament.id, user)

    if result.is_ok():
        flash_success(gettext('Du wurdest angemeldet.'))
    else:
        flash_error(result.unwrap_err())

    return redirect(url_for('netsession_tourney.view_overview', slug=slug))


@blueprint.post('/<slug>/unregister')
@login_required
def unregister(slug):
    tournament = _get_tournament_or_404(slug)

    user = user_service.get_user(g.user.id)
    result = deregister_user(g.party.id, tournament.id, user)

    if result.is_ok():
        flash_success(gettext('Du wurdest abgemeldet.'))
    else:
        flash_error(result.unwrap_err())

    return redirect(url_for('netsession_tourney.view_overview', slug=slug))


@blueprint.get('/<slug>/teams/create')
@login_required
@templated
def create_team_form(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    is_flatout2_tournament = _uses_only_flatout2_stages(stages, [])
    registration_state = _get_registration_state_for_tournament(tournament)

    if tournament.registration_mode == RegistrationMode.solo:
        flash_error(gettext('Dieses Turnier erlaubt nur Solo-Anmeldungen.'))
        return redirect_to('.view_participants', slug=slug)

    if not registration_state['can_register']:
        captain_team = _get_captain_team_for_current_user(tournament.id)
        if captain_team is not None:
            return redirect_to(
                '.view_team',
                slug=slug,
                participant_id=captain_team.id,
            )
        if registration_state['insufficient_coins']:
            flash_error(gettext('Du hast aktuell nicht genügend Coins für dieses Turnier.'))
        else:
            flash_error(gettext('Team-Anmeldungen sind aktuell nicht verfügbar.'))
        return redirect_to('.view_participants', slug=slug)

    current_page_id = _get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'form': TeamCreationForm(),
        'join_form': TeamJoinForm(),
        'hide_bracket_tab': _uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            _get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


@blueprint.post('/<slug>/teams/create')
@login_required
def create_team(slug):
    tournament = _get_tournament_or_404(slug)
    form_fields = request.form.copy()
    if request.files:
        form_fields.update(request.files)

    form = TeamCreationForm(form_fields)
    if not form.validate():
        flash_error(gettext('Ungültige Teamdaten.'))
        return redirect_to('.create_team_form', slug=slug)

    user = user_service.get_user(g.user.id)
    team_logo_url = None
    logo_file = request.files.get('logo_file')
    if logo_file is not None and logo_file.filename:
        upload_result = upload_logo_for_new_team(
            g.party.id, tournament, user, logo_file.stream,
            label=form.name.data, original_filename=logo_file.filename,
        )
        if upload_result.is_err():
            flash_error(upload_result.unwrap_err())
            return redirect_to('.create_team_form', slug=slug)
        team_logo_url = upload_result.unwrap()

    result = create_team_for_captain(
        g.party.id,
        tournament.id,
        user,
        form.name.data,
        team_logo_url=team_logo_url,
    )
    if result.is_ok():
        flash_success(gettext('Das Team wurde erstellt.'))
        team = result.unwrap()
        return redirect_to(
            '.view_team', slug=slug, participant_id=team.id
        )
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.create_team_form', slug=slug)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/update')
@login_required
def update_team(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    if tournament.status not in {TournamentStatus.draft, TournamentStatus.live}:
        flash_error(gettext('Team kann aktuell nicht bearbeitet werden.'))
        return redirect_to(
            '.view_team', slug=slug, participant_id=participant_id
        )

    form_fields = request.form.copy()
    if request.files:
        form_fields.update(request.files)

    form = TeamCreationForm(form_fields)
    if tournament.status == TournamentStatus.draft and not form.validate():
        flash_error(gettext('Ungültige Teamdaten.'))
        return redirect_to(
            '.view_team', slug=slug, participant_id=participant_id
        )

    user = user_service.get_user(g.user.id)
    logo_file = request.files.get('logo_file')
    replace_logo = bool(logo_file is not None and logo_file.filename)
    team_logo_url = None
    if replace_logo:
        upload_result = upload_logo_for_managed_team(
            g.party.id, tournament.id, participant_id, user, logo_file.stream,
            label=form.name.data, original_filename=logo_file.filename,
        )
        if upload_result.is_err():
            flash_error(upload_result.unwrap_err())
            return redirect_to(
                '.view_team', slug=slug, participant_id=participant_id
            )
        team_logo_url = upload_result.unwrap()

    result = update_managed_team_for_captain(
        g.party.id,
        tournament.id,
        participant_id,
        user,
        (
            form.name.data
            if tournament.status == TournamentStatus.draft
            else request.form.get('name', '')
        ),
        team_logo_url=team_logo_url,
        replace_logo=replace_logo,
    )
    if result.is_ok():
        flash_success(gettext('Das Team wurde aktualisiert.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post('/<slug>/teams/join')
@login_required
def join_team(slug):
    tournament = _get_tournament_or_404(slug)
    form = TeamJoinForm(request.form)
    if not form.validate():
        flash_error(gettext('Ungültiger Invite-Code.'))
        return redirect_to('.create_team_form', slug=slug)

    user = user_service.get_user(g.user.id)
    result = join_team_by_invite_code(
        g.party.id, tournament.id, form.invite_code.data, user
    )
    if result.is_ok():
        flash_success(gettext('Du bist dem Team beigetreten.'))
        team = result.unwrap()
        return redirect_to(
            '.view_team', slug=slug, participant_id=team.id
        )
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.create_team_form', slug=slug)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/invite-code/regenerate')
@login_required
def regenerate_team_invite_code(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    user = user_service.get_user(g.user.id)

    result = regenerate_team_invite_code_for_manager(
        g.party.id,
        tournament.id,
        participant_id,
        user,
    )
    if result.is_ok():
        flash_success(gettext('Invite-Code wurde erneuert.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/members/<uuid:member_user_id>/remove')
@login_required
def remove_team_member(slug, participant_id, member_user_id):
    tournament = _get_tournament_or_404(slug)
    user = user_service.get_user(g.user.id)

    result = remove_team_member_by_captain(
        g.party.id,
        tournament.id,
        participant_id,
        member_user_id,
        user,
    )
    if result.is_ok():
        flash_success(gettext('Teammitglied wurde entfernt.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post(
    '/<slug>/teams/<uuid:participant_id>/members/<uuid:member_user_id>/captain'
)
@login_required
def assign_team_captain(slug, participant_id, member_user_id):
    tournament = _get_tournament_or_404(slug)
    user = user_service.get_user(g.user.id)

    result = assign_team_captain_by_captain(
        g.party.id,
        tournament.id,
        participant_id,
        member_user_id,
        user,
    )
    if result.is_ok():
        flash_success(gettext('Der Teamkapitän wurde geändert.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/members/add')
@login_required
def add_team_member(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    form = TeamMemberAddForm(request.form)
    if not form.validate():
        flash_error(gettext('Ungültige Teammitglied-Daten.'))
        return redirect_to('.view_team', slug=slug, participant_id=participant_id)

    screen_name = form.screen_name.data.strip()
    member_user = user_service.find_user_by_screen_name(screen_name)
    if member_user is None:
        flash_error(gettext('Unbekannter Benutzer.'))
        return redirect_to('.view_team', slug=slug, participant_id=participant_id)

    user = user_service.get_user(g.user.id)
    result = add_team_member_by_captain(
        g.party.id,
        tournament.id,
        participant_id,
        member_user,
        user,
    )
    if result.is_ok():
        flash_success(gettext('Teammitglied wurde hinzugefügt.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post('/<slug>/teams/<uuid:participant_id>/ready')
@login_required
def set_team_ready_state(slug, participant_id):
    tournament = _get_tournament_or_404(slug)
    user = user_service.get_user(g.user.id)
    should_be_ready = request.form.get('ready') == 'true'

    result = set_managed_team_ready_state(
        g.party.id,
        tournament.id,
        participant_id,
        user,
        ready=should_be_ready,
    )
    if result.is_ok():
        flash_success(gettext('Der Teamstatus wurde aktualisiert.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_team', slug=slug, participant_id=participant_id)


@blueprint.post('/<slug>/matches/<uuid:match_id>/report')
@login_required
def report_match_result(slug, match_id):
    tournament = _get_tournament_or_404(slug)
    form = MatchScoreReportForm(request.form)
    if not form.validate():
        flash_error(gettext('Ungültige Ergebnisdaten.'))
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    slots = sorted(
        get_match_slots_for_match(match_id), key=lambda slot: slot.slot_no
    )
    match = find_match_for_tournament(g.party.id, tournament.id, match_id)
    if match is None:
        flash_error(gettext('Unbekanntes Match.'))
        return redirect_to('.view_match', slug=slug, match_id=match_id)
    stages_by_id = {
        stage.id: stage for stage in get_stages_for_tournament(g.party.id, tournament.id)
    }
    stage = stages_by_id.get(match.stage_id)
    if _is_ffa_scoring_stage(stage):
        flash_error(
            gettext(
                'FFA-Ergebnisse werden nur im Admin-Bereich eingetragen.'
            )
        )
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    if len(slots) != 2:
        flash_error(
            gettext(
                'Ergebnisübermittlung mit Punkten wird aktuell nur für Duell-Matches unterstützt.'
            )
        )
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    if any(slot.participant_id is None for slot in slots):
        flash_error(
            gettext(
                'Beide Teilnehmer müssen gesetzt sein, bevor ein Ergebnis gemeldet werden kann.'
            )
        )
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    slot_1_points = form.slot_1_points.data
    slot_2_points = form.slot_2_points.data
    if slot_1_points == slot_2_points:
        flash_error(
            gettext(
                'Ein Unentschieden ist nicht erlaubt. Bitte einen eindeutigen Sieger melden.'
            )
        )
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    winner_slot = (
        slots[0].slot_no if slot_1_points > slot_2_points else slots[1].slot_no
    )
    score = _build_slot_score_payload(
        slots,
        {
            slots[0].slot_no: slot_1_points,
            slots[1].slot_no: slot_2_points,
        },
    )
    ranking = {}
    idempotency_key = _get_or_create_idempotency_key(form.idempotency_key.data)
    comment = form.comment.data.strip() if form.comment.data else None

    result = report_result(
        g.party.id,
        tournament.id,
        match_id,
        g.user.id,
        idempotency_key=idempotency_key,
        winner_slot=winner_slot,
        score=score,
        ranking=ranking,
        actor_is_admin_or_referee=False,
        admin_comment=comment,
    )

    if result.is_ok():
        flash_success(gettext('Ergebnis wurde übermittelt.'))
    else:
        flash_error(result.unwrap_err())

    next_target = request.form.get('next')
    if next_target and next_target.startswith('/') and not next_target.startswith('//'):
        return redirect(next_target)

    return redirect_to('.view_match', slug=slug, match_id=match_id)


@blueprint.post('/<slug>/matches/<uuid:match_id>/chat')
@login_required
def post_match_chat(slug, match_id):
    tournament = _get_tournament_or_404(slug)
    form = MatchChatMessageForm(request.form)
    if not form.validate():
        flash_error(gettext('Ungültige Chat-Nachricht.'))
        return redirect_to('.view_match', slug=slug, match_id=match_id)

    is_admin_or_referee = g.user.has_permission(
        'netsession_tourney.manage'
    ) or g.user.has_permission('netsession_tourney.admin')

    result = post_match_chat_message(
        g.party.id,
        tournament.id,
        match_id,
        g.user.id,
        form.body.data,
        actor_is_admin_or_referee=is_admin_or_referee,
    )
    if result.is_ok():
        flash_success(gettext('Nachricht wurde gesendet.'))
    else:
        flash_error(result.unwrap_err())

    return redirect_to('.view_match', slug=slug, match_id=match_id)


def _get_tournament_or_404(slug):
    if not g.party:
        abort(404)

    tournament = find_tournament_by_slug_for_party(
        g.party.id, slug, visible_on_site=True
    )
    if tournament is None:
        abort(404)

    return tournament


def _parse_status_filter(value: str | None):
    if not value:
        return None
    try:
        return TournamentStatus(value)
    except ValueError:
        return None


def _parse_mode_filter(value: str | None):
    if not value:
        return None
    try:
        return TournamentMode(value)
    except ValueError:
        return None


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



