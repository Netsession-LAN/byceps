"""API for the newsletter sync: subscribers (with the Sendy fields) and
unsubscribing on behalf of a user, guarded by the token permission."""

import pytest
from sqlalchemy import select

from byceps.database import db
from byceps.services.netsession_newsletter import unsubscribe_token
from byceps.services.newsletter import newsletter_service
from byceps.services.newsletter.dbmodels import DbSubscriptionUpdate
from byceps.services.orga_team import orga_team_service

from tests.helpers import generate_token


BASE = 'http://api.acmecon.test/v1/ns-newsletter/lists'


@pytest.fixture()
def current_party_site(monkeypatch, site, party):
    """The site whose party counts as the current party for the orga flag."""
    monkeypatch.setenv('NS_NEWSLETTER_SITE_ID', site.id)
    return site


def _get(api_client, header, list_id, query=''):
    return api_client.get(
        f'{BASE}/{list_id}/subscribers{query}', headers=[header]
    )


def test_token_needs_the_sync_permission(
    api_client, newsletter_list, other_authz_header
):
    assert (
        api_client.get(f'{BASE}/{newsletter_list.id}/subscribers').status_code
        == 401
    )
    assert (
        _get(api_client, other_authz_header, newsletter_list.id).status_code
        == 403
    )


def test_unknown_list_is_404(api_client, sync_authz_header):
    assert (
        _get(api_client, sync_authz_header, 'no-such-list').status_code == 404
    )


def test_subscribers_carry_the_sendy_fields(
    api_client,
    sync_authz_header,
    newsletter_list,
    subscribe,
    make_user,
    current_party_site,
    party,
    make_party,
    brand,
):
    orga = make_user(
        email_address_verified=True, first_name='Max', last_name='Muster'
    )
    player = make_user(
        email_address_verified=True, first_name=None, last_name=None
    )
    former_orga = make_user(email_address_verified=True)
    unverified = make_user(email_address_verified=False)
    for user in (orga, player, former_orga, unverified):
        subscribe(user, newsletter_list)

    team = orga_team_service.create_team(party.id, f'Orga {generate_token(4)}')
    orga_team_service.create_membership(team.id, orga.id, None)
    old_party = make_party(brand)
    old_team = orga_team_service.create_team(
        old_party.id, f'Alt {generate_token(4)}'
    )
    orga_team_service.create_membership(old_team.id, former_orga.id, None)

    response = _get(api_client, sync_authz_header, newsletter_list.id)

    assert response.status_code == 200
    data = response.json
    assert data['list_id'] == newsletter_list.id
    by_id = {s['user_id']: s for s in data['subscribers']}
    assert set(by_id) == {str(orga.id), str(player.id), str(former_orga.id)}

    entry = by_id[str(orga.id)]
    assert entry['screen_name'] == orga.screen_name
    assert entry['first_name'] == 'Max'
    assert entry['last_name'] == 'Muster'
    assert entry['subscribed_at'] == '2026-02-24T10:00:00Z'
    assert entry['is_orga_member'] is True
    assert unsubscribe_token.parse(entry['unsubscribe_token']) == (
        orga.id,
        newsletter_list.id,
    )
    assert by_id[str(player.id)]['first_name'] is None
    assert by_id[str(player.id)]['is_orga_member'] is False
    # only the current party counts
    assert by_id[str(former_orga.id)]['is_orga_member'] is False


def test_without_current_party_nobody_is_orga(
    api_client,
    sync_authz_header,
    newsletter_list,
    subscribe,
    make_user,
    monkeypatch,
    party,
):
    monkeypatch.setenv('NS_NEWSLETTER_SITE_ID', 'no-such-site')
    user = make_user(email_address_verified=True)
    subscribe(user, newsletter_list)
    team = orga_team_service.create_team(party.id, f'Orga {generate_token(4)}')
    orga_team_service.create_membership(team.id, user.id, None)

    data = _get(api_client, sync_authz_header, newsletter_list.id).json

    assert [s['is_orga_member'] for s in data['subscribers']] == [False]


def test_subscribers_can_be_filtered_by_user(
    api_client, sync_authz_header, newsletter_list, subscribe, make_user
):
    first = make_user(email_address_verified=True)
    second = make_user(email_address_verified=True)
    subscribe(first, newsletter_list)
    subscribe(second, newsletter_list)

    data = _get(
        api_client,
        sync_authz_header,
        newsletter_list.id,
        f'?user_id={second.id}',
    ).json

    assert [s['user_id'] for s in data['subscribers']] == [str(second.id)]
    assert (
        _get(
            api_client, sync_authz_header, newsletter_list.id, '?user_id=kaputt'
        ).status_code
        == 400
    )


def test_unsubscribe_is_idempotent_and_logged_as_the_user(
    api_client, sync_authz_header, newsletter_list, subscribe, make_user
):
    user = make_user(email_address_verified=True)
    subscribe(user, newsletter_list)
    url = f'{BASE}/{newsletter_list.id}/unsubscribe'
    body = {
        'user_id': str(user.id),
        'expressed_at': '2026-11-11T08:00:00Z',
        'source': 'sendy',
    }

    first = api_client.post(url, json=body, headers=[sync_authz_header])
    second = api_client.post(url, json=body, headers=[sync_authz_header])

    assert first.status_code == 200
    assert first.json == {'status': 'unsubscribed'}
    assert second.json == {'status': 'already_unsubscribed'}
    assert not newsletter_service.is_user_subscribed_to_list(
        user.id, newsletter_list.id
    )
    update = db.session.scalars(
        select(DbSubscriptionUpdate)
        .filter_by(user_id=user.id, list_id=newsletter_list.id)
        .order_by(DbSubscriptionUpdate.expressed_at.desc())
    ).first()
    assert update.expressed_at.isoformat() == '2026-11-11T08:00:00'


def test_unsubscribe_by_email_and_unknown_user(
    api_client,
    sync_authz_header,
    newsletter_list,
    subscribe,
    make_user,
    other_authz_header,
):
    user = make_user(email_address_verified=True)
    subscribe(user, newsletter_list)
    url = f'{BASE}/{newsletter_list.id}/unsubscribe'

    assert (
        api_client.post(
            url,
            json={'email_address': user.email_address},
            headers=[other_authz_header],
        ).status_code
        == 403
    )
    response = api_client.post(
        url,
        json={'email_address': user.email_address},
        headers=[sync_authz_header],
    )
    assert response.json == {'status': 'unsubscribed'}
    assert (
        api_client.post(
            url,
            json={'email_address': 'nobody@users.test'},
            headers=[sync_authz_header],
        ).status_code
        == 404
    )
    assert (
        api_client.post(url, json={}, headers=[sync_authz_header]).status_code
        == 400
    )
