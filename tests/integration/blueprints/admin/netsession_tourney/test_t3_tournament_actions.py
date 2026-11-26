"""Admin tournament actions: status changes, deletion, notifications and
the Discord settings."""

import httpx
import pytest
import respx

from byceps.services.netsession_tourney import (
    browser_push_service,
    discord_forum_threads,
    result_service,
    stage_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import TournamentStatus
from byceps.util.result import Ok

from tests.helpers import generate_token


pytest_plugins = [
    'tests.integration.blueprints.admin.netsession_tourney.conftest_t3'
]

CHANNEL_ID = '123456789012345678'
TAG_ID = '223456789012345678'


def _post(client, url, data=None):
    response = client.post(url, data=data or {})
    assert response.status_code == 302
    return response


def test_publish_and_unpublish(t3_client, t3_assert_flash, t3_make_tourney):
    tourney = t3_make_tourney(count=2, publish=False, generate=False)

    response = _post(t3_client, tourney.url + '/publish')
    assert response.location.endswith(
        f'/tournaments/{tourney.tournament.id}?tab=overview'
    )
    t3_assert_flash(t3_client, 'success', 'Turnier wurde veröffentlicht.')
    assert tourney.reload().status == TournamentStatus.live

    _post(t3_client, tourney.url + '/unpublish')
    t3_assert_flash(t3_client, 'success', 'Turnier ist wieder ein Entwurf.')
    assert tourney.reload().status == TournamentStatus.draft

    _post(t3_client, tourney.url + '/unpublish')
    t3_assert_flash(
        t3_client,
        'danger',
        'Nur laufende Turniere können zurück in den Entwurf.',
    )


def test_publish_without_stage_fails(
    t3_client, t3_flashes, t3_make_tourney, t3_manager
):
    tourney = t3_make_tourney(count=2, publish=False, generate=False)
    stage_service.delete_stage(
        tourney.party.id, tourney.tournament.id, tourney.stage.id, t3_manager
    ).unwrap()

    _post(t3_client, tourney.url + '/publish')

    (flash,) = t3_flashes(t3_client)
    assert flash[0] == 'danger'
    assert tourney.reload().status == TournamentStatus.draft


def test_close_needs_all_results(
    t3_client, t3_assert_flash, t3_make_tourney, t3_manager
):
    tourney = t3_make_tourney(count=2)
    (match,) = tourney.matches()

    _post(t3_client, tourney.url + '/close')
    t3_assert_flash(
        t3_client,
        'danger',
        'Es sind noch 1 Matches offen. Bitte erst alle Ergebnisse eintragen '
        '(oder die Matches als Walkover werten).',
    )

    result_service.report_result(
        tourney.party.id,
        tourney.tournament.id,
        match.id,
        t3_manager.id,
        idempotency_key='t3-close-' + generate_token(),
        winner_slot=1,
        actor_is_admin_or_referee=True,
    ).unwrap()

    _post(t3_client, tourney.url + '/close')
    t3_assert_flash(t3_client, 'success', 'Turnier wurde abgeschlossen.')
    assert tourney.reload().status == TournamentStatus.closed

    _post(t3_client, tourney.url + '/cancel')
    t3_assert_flash(
        t3_client,
        'danger',
        'Abgeschlossene Turniere können nicht abgesagt werden.',
    )


def test_cancel_and_delete(t3_client, t3_assert_flash, t3_make_tourney):
    tourney = t3_make_tourney(count=2)

    _post(t3_client, tourney.url + '/delete')
    t3_assert_flash(
        t3_client,
        'danger',
        'Nur Entwürfe und abgesagte Turniere können gelöscht werden. '
        'Sage das Turnier zuerst ab.',
    )

    _post(t3_client, tourney.url + '/cancel')
    t3_assert_flash(t3_client, 'success', 'Turnier wurde abgesagt.')
    assert tourney.reload().status == TournamentStatus.canceled

    _post(t3_client, tourney.url + '/cancel')
    t3_assert_flash(t3_client, 'danger', 'Das Turnier ist bereits abgesagt.')

    response = _post(t3_client, tourney.url + '/delete')
    assert response.location.endswith(f'/for_party/{tourney.party.id}')
    t3_assert_flash(t3_client, 'success', 'Turnier wurde gelöscht.')
    assert tourney.reload() is None
    assert t3_client.get(tourney.url).status_code == 404


@pytest.fixture(scope='module')
def notify_tourney(t3_make_tourney, make_party, brand):
    return t3_make_tourney(count=2, generate=False, party=make_party(brand))


def test_notification_needs_title_and_body(
    t3_client, t3_assert_flash, notify_tourney
):
    response = _post(
        t3_client,
        notify_tourney.url + '/notifications/send',
        {'title': '', 'body': ''},
    )

    assert response.location.endswith('?tab=notifications')
    t3_assert_flash(
        t3_client, 'danger', 'Benachrichtigung konnte nicht gesendet werden.'
    )


def test_notification_needs_browser_push(
    t3_client, t3_assert_flash, notify_tourney
):
    _post(
        t3_client,
        notify_tourney.url + '/notifications/send',
        {'title': 'Achtung', 'body': 'Gleich geht es los.'},
    )

    t3_assert_flash(
        t3_client, 'danger', 'Browser-Benachrichtigungen sind ausgeschaltet.'
    )


def test_notification_is_sent(t3_client, t3_assert_flash, notify_tourney):
    browser_push_service.configure_browser_push(
        notify_tourney.party.id, enabled=True
    ).unwrap()

    response = _post(
        t3_client,
        notify_tourney.url + '/notifications/send',
        {'title': 'Achtung', 'body': 'Gleich geht es los.', 'target_url': ''},
    )

    assert response.location.endswith('?tab=notifications')
    t3_assert_flash(
        t3_client,
        'success',
        'Benachrichtigung wurde an 0 Teilnehmer mit 0 aktiven '
        'Browser-Subscriptions gesendet.',
    )


@pytest.fixture(scope='module')
def discord_tourney(t3_make_tourney):
    return t3_make_tourney(count=2, publish=False, generate=False)


def _discord_data(**overrides):
    data = {
        'discord_enabled': 'y',
        'forum_channel_id': CHANNEL_ID,
        'discord_forum_image_url': '',
        'applied_tag_ids': f'{TAG_ID}, ',
        'event_mask': ['tournament_live', 'match_completed'],
        'discord_dm_enabled': 'y',
        'discord_dm_event_mask': ['match_ready'],
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def test_discord_settings_are_saved(
    t3_client, t3_assert_flash, discord_tourney
):
    response = _post(
        t3_client, discord_tourney.url + '/discord', _discord_data()
    )

    assert response.location.endswith('?tab=discord')
    t3_assert_flash(
        t3_client, 'success', 'Discord-Konfiguration wurde aktualisiert.'
    )
    tournament = discord_tourney.reload()
    assert tournament.discord_enabled
    assert tournament.discord_forum_channel_id == CHANNEL_ID
    assert tournament.discord_applied_tag_ids == [TAG_ID]
    assert tournament.discord_event_mask == [
        'match_completed',
        'tournament_live',
    ]
    assert tournament.discord_dm_enabled
    assert tournament.discord_dm_event_mask == ['match_ready']

    body = t3_client.get(discord_tourney.url + '?tab=discord').get_data(
        as_text=True
    )
    assert f'value="{CHANNEL_ID}"' in body


@pytest.mark.parametrize(
    ('overrides', 'message'),
    [
        (
            {'event_mask': ['no_such_event']},
            'Discord-Konfiguration ist ungültig.',
        ),
        (
            {'discord_forum_image_url': '/unknown.png'},
            'Discord-Konfiguration ist ungültig.',
        ),
        (
            {'forum_channel_id': None},
            'Eine Discord-Forum-Channel-ID ist erforderlich.',
        ),
        (
            {'applied_tag_ids': 'abc'},
            'Discord-Tag-IDs müssen aus 17 bis 20 Ziffern bestehen.',
        ),
        (
            {'discord_dm_event_mask': None},
            'Mindestens ein Discord-DM-Event muss ausgewählt werden.',
        ),
    ],
)
def test_invalid_discord_settings_are_rejected(
    t3_client, t3_assert_flash, t3_make_tourney, overrides, message
):
    tourney = t3_make_tourney(count=0, publish=False, generate=False)

    _post(t3_client, tourney.url + '/discord', _discord_data(**overrides))

    t3_assert_flash(t3_client, 'danger', message)
    assert not tourney.reload().discord_enabled


def test_discord_forum_thread_is_created(
    t3_client, t3_assert_flash, t3_make_tourney, monkeypatch
):
    tourney = t3_make_tourney(count=0, publish=False, generate=False)
    monkeypatch.setattr(
        discord_forum_threads,
        'get_configured_discord_bot_credentials',
        lambda: Ok(('323456789012345678', 'test-bot-token')),
    )

    with respx.mock(assert_all_called=True) as discord_api:
        route = discord_api.post(
            f'https://discord.com/api/v10/channels/{CHANNEL_ID}/threads'
        ).mock(return_value=httpx.Response(201, json={'id': '9' * 18}))
        _post(t3_client, tourney.url + '/discord', _discord_data())

    t3_assert_flash(
        t3_client, 'success', 'Discord-Konfiguration wurde aktualisiert.'
    )
    assert route.call_count == 1
    assert 'Bot test-bot-token' in route.calls[0].request.headers.get(
        'Authorization', ''
    )
    tournament = tournament_service.find_tournament_for_party(
        tourney.party.id, tourney.tournament.id
    )
    assert tournament.discord_thread_id == '9' * 18
