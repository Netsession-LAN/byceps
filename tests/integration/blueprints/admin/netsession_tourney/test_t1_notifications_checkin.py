"""Admin notification settings (browser push, Discord DMs) and manual
check-in of participants.
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from byceps.services.netsession_tourney import (
    browser_push_service,
    discord_dm_service,
    registration_service,
    tournament_queries,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    CheckinState,
    RegistrationMode,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


ADMIN_BASE_URL = 'http://admin.acmecon.test/ns-tourneys'
APPLICATION_ID = '123456789012345678'


@pytest.fixture(scope='module')
def party_url(tourney_party):
    return f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}'


# notifications


def test_notifications_index_renders(
    tourney_viewer_client, party_url, tourney_party, tourney_admin
):
    tournament_service.create_tournament(
        tourney_party.id,
        't1-notify-cup',
        'T1 Notify Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        tourney_admin,
    ).unwrap()

    response = tourney_viewer_client.get(f'{party_url}/notifications')

    assert response.status_code == 200
    assert 'T1 Notify Cup' in response.get_data(as_text=True)


def test_notifications_index_without_view_permission_is_forbidden(
    plain_admin_client, party_url
):
    response = plain_admin_client.get(f'{party_url}/notifications')

    assert response.status_code == 403


def test_browser_push_enable_and_disable(
    tourney_admin_client, party_url, tourney_party, pop_flashes
):
    response = tourney_admin_client.post(
        f'{party_url}/notifications', data={'enabled': 'y'}
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{tourney_party.id}/notifications'
    )
    assert pop_flashes(tourney_admin_client) == [
        'Browser-Benachrichtigungen wurden gespeichert.'
    ]
    assert browser_push_service.get_browser_push_config(
        tourney_party.id
    ).enabled

    tourney_admin_client.post(f'{party_url}/notifications', data={})

    assert pop_flashes(tourney_admin_client) == [
        'Browser-Benachrichtigungen wurden gespeichert.'
    ]
    config = browser_push_service.get_browser_push_config(tourney_party.id)
    assert not config.enabled


def test_browser_push_update_by_viewer_is_forbidden(
    tourney_viewer_client, party_url
):
    response = tourney_viewer_client.post(
        f'{party_url}/notifications', data={'enabled': 'y'}
    )

    assert response.status_code == 403


def test_discord_dm_configure(
    tourney_admin_client, party_url, tourney_party, pop_flashes
):
    response = tourney_admin_client.post(
        f'{party_url}/notifications/discord-dm',
        data={
            'enabled': 'y',
            'application_id': APPLICATION_ID,
            'bot_token': 'secret-bot-token-1234',
            'default_event_mask': 'match_ready, unknown_kind',
        },
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{tourney_party.id}/notifications'
    )
    assert pop_flashes(tourney_admin_client) == [
        'Discord-Privatbenachrichtigungen wurden gespeichert.'
    ]
    config = discord_dm_service.get_discord_dm_config(tourney_party.id)
    assert config.enabled
    assert config.application_id == APPLICATION_ID
    assert config.default_event_mask == ['match_ready']

    page = tourney_admin_client.get(f'{party_url}/notifications')
    assert 'secret-bot-token-1234' not in page.get_data(as_text=True)


@pytest.mark.parametrize(
    ('data', 'expected_message'),
    [
        ({'enabled': 'y'}, 'Eine Application ID ist erforderlich.'),
        (
            {'application_id': '42'},
            'Die Application ID muss aus 17 bis 20 Ziffern bestehen.',
        ),
    ],
)
def test_discord_dm_configure_with_invalid_values_is_refused(
    tourney_admin_client, make_party, brand, pop_flashes, data, expected_message
):
    party = make_party(brand)

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/for_party/{party.id}/notifications/discord-dm',
        data=data,
    )

    assert response.status_code == 302
    assert pop_flashes(tourney_admin_client) == [expected_message]
    assert not discord_dm_service.get_discord_dm_config(party.id).enabled


def test_discord_dm_configure_without_bot_token_is_refused(
    tourney_admin_client, make_party, brand, pop_flashes
):
    party = make_party(brand)

    tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/for_party/{party.id}/notifications/discord-dm',
        data={'enabled': 'y', 'application_id': APPLICATION_ID},
    )

    assert pop_flashes(tourney_admin_client) == [
        'Ein Bot-Token ist erforderlich.'
    ]


def test_discord_dm_configure_with_too_long_value_shows_form_again(
    tourney_admin_client, party_url
):
    response = tourney_admin_client.post(
        f'{party_url}/notifications/discord-dm',
        data={'application_id': '1' * 121},
    )

    assert response.status_code == 200
    assert (
        'Discord-Privatbenachrichtigungen konnten nicht gespeichert werden.'
        in response.get_data(as_text=True)
    )


def test_discord_dm_test_message_needs_enabled_config(
    tourney_admin_client, make_party, brand, pop_flashes
):
    party = make_party(brand)

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/for_party/{party.id}/notifications/discord-dm/test'
    )

    assert response.status_code == 302
    assert response.location.endswith(f'/for_party/{party.id}/notifications')
    assert pop_flashes(tourney_admin_client) == [
        'Discord-Privatbenachrichtigungen sind nicht aktiviert.'
    ]


def test_discord_dm_test_message_by_viewer_is_forbidden(
    tourney_viewer_client, party_url
):
    response = tourney_viewer_client.post(
        f'{party_url}/notifications/discord-dm/test'
    )

    assert response.status_code == 403


# check-in


@pytest.fixture(scope='module')
def checkin_tournament(tourney_party, tourney_admin):
    now = datetime.utcnow()
    return tournament_service.create_tournament(
        tourney_party.id,
        f't1-checkin-{generate_token().lower()}',
        'T1 Checkin Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        tourney_admin,
        checkin_open_at=now - timedelta(hours=1),
        checkin_close_at=now + timedelta(hours=1),
    ).unwrap()


@pytest.fixture(scope='module')
def participant(
    tourney_party, checkin_tournament, make_user, make_ticket_category
):
    player = make_user(f'T1Checkin{generate_token(4)}')
    category = make_ticket_category(tourney_party.id, 'T1 Checkin Ticket')
    ticket = ticket_creation_service.create_ticket(category, player)
    ticket_user_management_service.appoint_user(ticket.id, player, player)
    registration_service.register_user(
        tourney_party.id, checkin_tournament.id, player
    ).unwrap()
    (participant,) = tournament_queries.get_participants_for_tournament(
        tourney_party.id, checkin_tournament.id
    )
    return participant


def _checkin_state(party_id, tournament_id):
    (participant,) = tournament_queries.get_participants_for_tournament(
        party_id, tournament_id
    )
    return participant.checkin_state


def test_check_in_and_revoke_participant(
    tourney_admin_client,
    party_url,
    tourney_party,
    checkin_tournament,
    participant,
    pop_flashes,
):
    url = (
        f'{party_url}/tournaments/{checkin_tournament.id}'
        f'/participants/{participant.id}/checkin'
    )

    response = tourney_admin_client.post(url, data={'checked_in': '1'})

    assert response.status_code == 302
    assert response.location.endswith(
        f'/tournaments/{checkin_tournament.id}?tab=participants'
    )
    assert pop_flashes(tourney_admin_client) == [
        f'{participant.name} ist eingecheckt.'
    ]
    state = _checkin_state(tourney_party.id, checkin_tournament.id)
    assert state == CheckinState.checked_in

    tourney_admin_client.post(url, data={'checked_in': '0'})

    assert pop_flashes(tourney_admin_client) == [
        f'Check-in von {participant.name} zurückgenommen.'
    ]
    state = _checkin_state(tourney_party.id, checkin_tournament.id)
    assert state == CheckinState.pending


def test_check_in_of_unknown_participant_is_refused(
    tourney_admin_client, party_url, checkin_tournament, pop_flashes
):
    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{checkin_tournament.id}'
        f'/participants/{uuid4()}/checkin',
        data={'checked_in': '1'},
    )

    assert response.status_code == 302
    assert pop_flashes(tourney_admin_client) == ['Unbekannter Teilnehmer.']


def test_check_in_in_unknown_tournament_returns_404(
    tourney_admin_client, party_url, participant
):
    response = tourney_admin_client.post(
        f'{party_url}/tournaments/{uuid4()}'
        f'/participants/{participant.id}/checkin',
        data={'checked_in': '1'},
    )

    assert response.status_code == 404


def test_check_in_by_viewer_is_forbidden(
    tourney_viewer_client,
    party_url,
    tourney_party,
    checkin_tournament,
    participant,
):
    response = tourney_viewer_client.post(
        f'{party_url}/tournaments/{checkin_tournament.id}'
        f'/participants/{participant.id}/checkin',
        data={'checked_in': '1'},
    )

    assert response.status_code == 403
    state = _checkin_state(tourney_party.id, checkin_tournament.id)
    assert state == CheckinState.pending
