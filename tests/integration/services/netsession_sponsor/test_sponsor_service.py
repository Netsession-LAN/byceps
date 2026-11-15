"""Sponsors of a party: order, reordering, deleting, active filter, API."""

import pytest

from byceps.services.authn.api import authn_api_service
from byceps.services.authz.models import PermissionID
from byceps.services.netsession_sponsor import sponsor_service


API_URL = 'http://api.acmecon.test/v1/ns-sponsors'


@pytest.fixture
def own_party(make_party, brand):
    return make_party(brand)


def _names(party_id, **kwargs):
    return [
        s.name
        for s in sponsor_service.get_sponsors_for_party(party_id, **kwargs)
    ]


def _create(own_party, name, **kwargs):
    return sponsor_service.create_sponsor(
        own_party.id,
        name,
        f'parties/{own_party.id}/sponsors/{name}.svg',
        **kwargs,
    )


def test_order_moving_and_deleting(admin_app, own_party):
    a = _create(own_party, 'A', target_url=' https://a.example/ ')
    b = _create(own_party, 'B')
    c = _create(own_party, 'C')
    assert _names(own_party.id) == ['A', 'B', 'C']
    assert a.target_url == 'https://a.example/'
    assert a.logo_url == f'/data/parties/{own_party.id}/sponsors/A.svg'

    assert sponsor_service.move_sponsor(c.id, -1).is_ok()
    assert _names(own_party.id) == ['A', 'C', 'B']
    assert sponsor_service.move_sponsor(a.id, -1).is_err()

    sponsor_service.delete_sponsor(a.id)
    sponsors = sponsor_service.get_sponsors_for_party(own_party.id)
    assert [(s.name, s.position) for s in sponsors] == [('C', 1), ('B', 2)]
    assert b.id in {s.id for s in sponsors}


def test_inactive_sponsors_are_hidden_when_asked(admin_app, own_party):
    _create(own_party, 'Active')
    hidden = _create(own_party, 'Hidden', enabled=False)
    assert _names(own_party.id, enabled_only=True) == ['Active']

    sponsor_service.update_sponsor(
        hidden.id,
        'Hidden',
        target_url=None,
        enabled=True,
        logo_dark_path='parties/x/dark.svg',
    ).unwrap()
    assert _names(own_party.id, enabled_only=True) == ['Active', 'Hidden']
    updated = sponsor_service.find_sponsor(hidden.id)
    assert updated.logo_url_dark == '/data/parties/x/dark.svg'


def test_api_lists_active_sponsors_with_token(api_app, admin_user, own_party):
    _create(own_party, 'Hetzner', target_url='https://www.hetzner.com/')
    _create(own_party, 'Off', enabled=False)
    client = api_app.test_client()
    read = authn_api_service.create_api_token(
        admin_user.id, {PermissionID('ns_api.read')}
    )
    other = authn_api_service.create_api_token(admin_user.id, set())
    url = f'{API_URL}?party_id={own_party.id}'

    assert client.get(url).status_code == 401
    assert (
        client.get(
            url, headers={'Authorization': f'Bearer {other.token}'}
        ).status_code
        == 403
    )
    response = client.get(
        url, headers={'Authorization': f'Bearer {read.token}'}
    )
    assert response.status_code == 200
    assert response.get_json() == [
        {
            'id': response.get_json()[0]['id'],
            'name': 'Hetzner',
            'logo_url': f'/data/parties/{own_party.id}/sponsors/Hetzner.svg',
            'logo_url_dark': None,
            'target_url': 'https://www.hetzner.com/',
            'weight': 1,
        }
    ]
