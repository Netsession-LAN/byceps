"""Admin pages of the sponsors module: upload, edit, reorder, delete."""

from io import BytesIO

import pytest

from byceps.services.netsession_sponsor import sponsor_service

from tests.helpers import log_in_user


BASE_URL = 'http://admin.acmecon.test/ns-sponsors'
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'


@pytest.fixture(scope='module')
def admin(make_admin):
    admin = make_admin({'admin.access', 'ns_sponsor.view', 'ns_sponsor.update'})
    log_in_user(admin.id)
    return admin


@pytest.fixture(scope='module')
def admin_client(make_client, admin_app, admin):
    return make_client(admin_app, user_id=admin.id)


@pytest.fixture
def own_party(make_party, brand):
    return make_party(brand)


def test_create_with_logo_upload(admin_client, own_party, data_path):
    response = admin_client.post(
        f'{BASE_URL}/for_party/{own_party.id}',
        data={
            'name': 'Hetzner',
            'target_url': 'https://www.hetzner.com/',
            'enabled': 'y',
            'logo': (BytesIO(SVG), 'hetzner.svg'),
        },
        content_type='multipart/form-data',
    )
    assert response.status_code == 302

    (sponsor,) = sponsor_service.get_sponsors_for_party(own_party.id)
    assert sponsor.name == 'Hetzner'
    assert sponsor.logo_path.startswith(f'parties/{own_party.id}/sponsors/')
    assert sponsor.logo_path.endswith('.svg')
    assert (data_path / sponsor.logo_path).read_bytes() == SVG

    index = admin_client.get(f'{BASE_URL}/for_party/{own_party.id}')
    assert index.status_code == 200
    assert 'Hetzner' in index.get_data(as_text=True)


def test_create_rejects_non_image_and_javascript_link(admin_client, own_party):
    response = admin_client.post(
        f'{BASE_URL}/for_party/{own_party.id}',
        data={
            'name': 'Evil',
            'target_url': 'javascript:alert(1)',
            'logo': (BytesIO(SVG), 'evil.svg'),
        },
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    assert sponsor_service.get_sponsors_for_party(own_party.id) == []

    response = admin_client.post(
        f'{BASE_URL}/for_party/{own_party.id}',
        data={'name': 'Text', 'logo': (BytesIO(b'hello'), 'logo.txt')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    assert sponsor_service.get_sponsors_for_party(own_party.id) == []


def test_update_move_and_delete(admin_client, own_party):
    a = sponsor_service.create_sponsor(own_party.id, 'A', 'parties/x/a.svg')
    b = sponsor_service.create_sponsor(own_party.id, 'B', 'parties/x/b.svg')

    assert (
        admin_client.get(f'{BASE_URL}/sponsors/{a.id}/update').status_code
        == 200
    )
    response = admin_client.post(
        f'{BASE_URL}/sponsors/{a.id}',
        data={'name': 'A neu', 'target_url': ''},
        content_type='multipart/form-data',
    )
    assert response.status_code == 302
    updated = sponsor_service.find_sponsor(a.id)
    assert updated.name == 'A neu'
    assert updated.enabled is False  # checkbox not sent
    assert updated.logo_path == 'parties/x/a.svg'

    assert (
        admin_client.post(f'{BASE_URL}/sponsors/{b.id}/up').status_code == 302
    )
    names = [
        s.name for s in sponsor_service.get_sponsors_for_party(own_party.id)
    ]
    assert names == ['B', 'A neu']

    assert (
        admin_client.post(f'{BASE_URL}/sponsors/{b.id}/delete').status_code
        == 302
    )
    names = [
        s.name for s in sponsor_service.get_sponsors_for_party(own_party.id)
    ]
    assert names == ['A neu']
