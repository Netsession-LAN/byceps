"""
byceps.services.netsession_tourney.blueprints.site.routes_index
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournament index, open matches, timetable and notification subscriptions.
"""

from __future__ import annotations

from flask import (
    abort,
    current_app,
    g,
    jsonify,
    render_template,
    request,
    url_for,
)

from byceps.services.netsession_tourney.browser_push_service import (
    disable_browser_push_subscription,
    is_browser_push_enabled_for_party,
    upsert_browser_push_subscription,
)
from byceps.services.netsession_tourney.discord_dm_service import (
    disable_discord_dm_subscription,
    is_discord_dm_enabled_for_party,
    upsert_discord_dm_subscription,
)
from byceps.services.netsession_tourney.filter_parsing import (
    parse_tournament_mode,
    parse_tournament_status,
)
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots,
    get_open_matches_for_party,
)
from byceps.services.netsession_tourney.participant_admin_service import (
    get_active_participant_counts_for_tournaments,
)
from byceps.services.netsession_tourney.registration_validation import (
    get_team_members_for_participants,
)
from byceps.services.netsession_tourney.tournament_category_service import (
    get_tournament_categories_for_party,
)
from byceps.services.netsession_tourney.tournament_service import (
    get_tournaments_for_party,
)
from byceps.util.framework.templating import templated
from byceps.util.views import login_required

from .blueprint import blueprint
from .common import (
    find_netsession_tourney_subnav_menu_id,
    get_categories_with_tournaments,
    get_main_nav_current_page_id,
    get_participants_for_tournament_indexed_by_id,
)
from .routes_index_helpers import (
    build_index_filter_values,
    build_index_notification_state,
    build_open_match_labels,
    build_open_match_rows,
    build_public_statuses_by_tournament_id,
    build_registration_states_by_tournament_id,
    build_stages_by_tournament_id,
    build_tournaments_by_id,
    collect_slot_participant_ids,
    get_involved_party_tournament_ids,
    has_connected_discord_account,
    parse_browser_push_subscription_payload,
)
from .timetable_helpers import build_party_timetable
from .user_state_helpers import (
    get_party_coin_settings,
    get_user_registered_tournament_ids,
)


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

    status = parse_tournament_status(status_param)
    mode = parse_tournament_mode(mode_param)

    tournaments = get_tournaments_for_party(
        g.party.id,
        status=status,
        mode=mode,
        game=game,
        visible_on_site=True,
    )
    categories = get_tournament_categories_for_party(g.party.id)
    categories_with_tournaments, uncategorized_tournaments = (
        get_categories_with_tournaments(categories, tournaments)
    )

    tournament_ids = {tournament.id for tournament in tournaments}
    active_participant_counts = get_active_participant_counts_for_tournaments(
        g.party.id, tournament_ids
    )
    user_registered_tournament_ids = get_user_registered_tournament_ids(
        g.party.id, tournament_ids
    )
    registration_states_by_tournament_id = (
        build_registration_states_by_tournament_id(
            tournaments,
            active_participant_counts,
            user_registered_tournament_ids,
        )
    )
    public_statuses_by_tournament_id = build_public_statuses_by_tournament_id(
        tournaments
    )
    coin_settings = get_party_coin_settings()
    browser_push_enabled = is_browser_push_enabled_for_party(g.party.id)
    discord_dm_enabled = is_discord_dm_enabled_for_party(g.party.id)
    notification_state = build_index_notification_state(
        tournament_ids, browser_push_enabled, discord_dm_enabled
    )
    current_page_id = get_main_nav_current_page_id()
    notification_prompt_enabled = (
        notification_state['browser_push_prompt_enabled']
        or notification_state['discord_dm_prompt_enabled']
    )

    return {
        'tournaments': tournaments,
        'categories_with_tournaments': categories_with_tournaments,
        'uncategorized_tournaments': uncategorized_tournaments,
        'registration_states_by_tournament_id': registration_states_by_tournament_id,
        'public_statuses_by_tournament_id': public_statuses_by_tournament_id,
        **build_index_filter_values(status_param, mode_param, game),
        'notification_prompt_enabled': notification_prompt_enabled,
        **notification_state,
        'coin_settings': coin_settings,
        'current_page': current_page_id,
        'current_global_subnav_page': 'ns_tourney_index',
        'subnav_menu_id': find_netsession_tourney_subnav_menu_id(
            'netsession_tourney'
        ),
    }


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
    endpoint, endpoint_p256dh, endpoint_auth = (
        parse_browser_push_subscription_payload(payload)
    )

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

    if not has_connected_discord_account(g.user.id):
        return jsonify({'error': 'discord_not_connected'}), 400

    involved_tournament_ids = get_involved_party_tournament_ids(
        g.party.id, g.user.id
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
    participant_ids = collect_slot_participant_ids(slots_by_match_id)

    participants = get_participants_for_tournament_indexed_by_id(
        g.party.id, participant_ids
    )
    members_by_participant_id = get_team_members_for_participants(
        participant_ids
    )
    tournaments_by_id = build_tournaments_by_id(g.party.id, tournament_ids)
    stages_by_tournament_id = build_stages_by_tournament_id(
        g.party.id, tournament_ids
    )

    match_labels_by_id = build_open_match_labels(
        matches, slots_by_match_id, stages_by_tournament_id
    )

    rows = build_open_match_rows(
        matches,
        slots_by_match_id,
        tournaments_by_id,
        stages_by_tournament_id,
        participants,
        members_by_participant_id,
        match_labels_by_id,
    )

    current_page_id = get_main_nav_current_page_id()

    return {
        'rows': rows,
        'current_page': current_page_id,
        'current_global_subnav_page': 'ns_tourney_open_matches',
        'subnav_menu_id': find_netsession_tourney_subnav_menu_id(
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

    current_page_id = get_main_nav_current_page_id()
    selected_day_iso = (request.args.get('day') or '').strip() or None

    return {
        'timetable': build_party_timetable(
            g.party, selected_day_iso=selected_day_iso
        ),
        'current_page': current_page_id,
        'current_global_subnav_page': 'ns_tourney_timetable',
        'subnav_menu_id': find_netsession_tourney_subnav_menu_id(
            'netsession_tourney_timetable',
            'netsession_tourney',
        ),
    }
