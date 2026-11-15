"""Party list for Screens."""

from byceps.services.authn.api import authn_api_service
from byceps.services.authz.models import PermissionID


URL = 'http://api.acmecon.test/v1/ns-parties'


def test_parties_need_token_and_mark_the_current_party(
    api_app, admin_user, site, make_party, brand
):
    other = make_party(brand)
    client = api_app.test_client()
    token = authn_api_service.create_api_token(
        admin_user.id, {PermissionID('ns_api.read')}
    )
    headers = {'Authorization': f'Bearer {token.token}'}

    assert client.get(URL).status_code == 401
    response = client.get(f'{URL}?brand_id={brand.id}', headers=headers)
    assert response.status_code == 200
    parties = response.get_json()
    ids = [party['id'] for party in parties]
    assert other.id in ids
    assert all(party['brand_id'] == brand.id for party in parties)
    starts = [party['starts_at'] for party in parties]
    assert starts == sorted(starts, reverse=True)
    assert all(party['starts_at'].endswith('+00:00') for party in parties)
    assert all(party['is_current'] is False for party in parties)
