"""Seat statistics for Screens."""

from byceps.services.authn.api import authn_api_service
from byceps.services.authz.models import PermissionID


def test_seat_stats_need_token(api_app, admin_user, party):
    client = api_app.test_client()
    url = f'http://api.acmecon.test/v1/ns-seating/{party.id}/stats'
    token = authn_api_service.create_api_token(
        admin_user.id, {PermissionID('ns_api.read')}
    )
    headers = {'Authorization': f'Bearer {token.token}'}

    assert client.get(url).status_code == 401
    response = client.get(url, headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert set(data) == {'seats_total', 'seats_occupied'}
    assert data['seats_occupied'] <= data['seats_total']

    assert (
        client.get(
            'http://api.acmecon.test/v1/ns-seating/no-such-party/stats',
            headers=headers,
        ).status_code
        == 404
    )
