"""
byceps.services.netsession_tourney.blueprints.site.routes_index
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournament index, open matches, timetable and notification subscriptions.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from flask import (
    abort,
    current_app,
    g,
    jsonify,
    render_template,
    request,
    url_for,
)
from flask_babel import format_datetime, gettext

from byceps.services.external_accounts import external_accounts_service
from byceps.services.netsession_tourney.browser_push_service import (
    disable_browser_push_subscription,
    get_browser_push_public_key_for_party,
    has_active_browser_push_subscription_for_user,
    is_browser_push_enabled_for_party,
    upsert_browser_push_subscription,
)
from byceps.services.netsession_tourney.discord_dm_service import (
    disable_discord_dm_subscription,
    has_active_discord_dm_subscription_for_user,
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
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
    get_user_active_participation_tournament_ids,
)
from byceps.services.netsession_tourney.tournament_service import (
    get_tournaments_for_party,
)
from byceps.util.framework.templating import templated
from byceps.util.views import login_required

from .blueprint import blueprint
from .common import (
    build_public_tournament_status,
    find_netsession_tourney_subnav_menu_id,
    get_categories_with_tournaments,
    get_main_nav_current_page_id,
    get_participants_for_tournament_indexed_by_id,
)
from .match_helpers import (
    build_match_labels,
)
from .match_state_labels import open_class_name, open_label
from .timetable_helpers import build_party_timetable
from .user_state_helpers import (
    build_registration_state,
    format_open_match_participant_name,
    get_party_coin_settings,
    get_user_registered_tournament_ids,
    is_match_involving_user,
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
    registration_states_by_tournament_id = {
        tournament.id: build_registration_state(
            tournament,
            active_participant_counts.get(tournament.id, 0),
            tournament.id in user_registered_tournament_ids,
        )
        for tournament in tournaments
    }
    public_statuses_by_tournament_id = {
        tournament.id: build_public_tournament_status(tournament)
        for tournament in tournaments
    }
    coin_settings = get_party_coin_settings()
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
        discord_dm_prompt_enabled = discord_dm_enabled and (
            has_involved_tournaments or discord_dm_has_subscription
        )
        if browser_push_prompt_enabled:
            browser_push_vapid_public_key = (
                get_browser_push_public_key_for_party(g.party.id)
            )
            browser_push_has_subscription = (
                has_active_browser_push_subscription_for_user(
                    g.party.id, g.user.id
                )
            )
    current_page_id = get_main_nav_current_page_id()
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

    connected_account = external_accounts_service.find_connected_external_account_for_user_and_service(
        g.user.id, 'discord'
    )
    if connected_account is None or not connected_account.external_id:
        return jsonify({'error': 'discord_not_connected'}), 400

    tournament_ids = [
        tournament.id for tournament in get_tournaments_for_party(g.party.id)
    ]
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
    members_by_participant_id = get_team_members_for_participants(
        participant_ids
    )
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
            build_match_labels(
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
        slots = sorted(
            slots_by_match_id.get(match.id, []), key=lambda slot: slot.slot_no
        )
        participant_names = [
            format_open_match_participant_name(
                slot, participants_by_id=participants
            )
            for slot in slots
        ]
        is_my_match = current_user_id is not None and is_match_involving_user(
            current_user_id,
            slots,
            participants_by_id=participants,
            members_by_participant_id=members_by_participant_id,
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
                'stage_name': stage.name
                if stage is not None
                else gettext('Phase'),
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
