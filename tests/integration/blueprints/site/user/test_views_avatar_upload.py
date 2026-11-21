"""Netsession: readable answers to unusable or too large avatar uploads."""

from io import BytesIO

from PIL import Image
import pytest

from byceps.services.site import site_service
from byceps.services.site.models import SiteID

from tests.helpers import create_site, http_client, log_in_user


BASE = 'http://www.acmecon.test'
FORM_PATH = '/users/me/avatar/update'


def _post_avatar(app, user, data: bytes, *, headers=None):
    log_in_user(user.id)
    with http_client(app, user_id=user.id) as client:
        return client.post(
            f'{BASE}/users/me/avatar',
            data={'image': (BytesIO(data), 'avatar.png')},
            content_type='multipart/form-data',
            headers=headers or {},
        )


def _png_bytes() -> bytes:
    stream = BytesIO()
    Image.new('RGB', (2000, 2000)).save(stream, format='PNG')
    return stream.getvalue()


@pytest.fixture(scope='module')
def netsession_site_app(make_site_app, party, board):
    """A site with ID `netsession`, so that its template overrides apply."""
    site_id = SiteID('netsession')
    if site_service.find_site(site_id) is None:
        create_site(
            site_id,
            party.brand_id,
            title='Netsession',
            server_name='ns-avatar.test',
            party_id=party.id,
            board_id=board.id,
        )
    return make_site_app('ns-avatar.test', site_id)


def test_form_shows_the_real_size_limit(netsession_site_app, user):
    log_in_user(user.id)
    with http_client(netsession_site_app, user_id=user.id) as client:
        response = client.get('http://ns-avatar.test' + FORM_PATH)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '10 MB' in html
    assert '150 KB' not in html
    assert f'data-ns-max-bytes="{10 * 1024 * 1024}"' in html


def test_unsupported_file_goes_back_to_the_form(site_app, user):
    response = _post_avatar(site_app, user, b'this is no image')
    assert response.status_code == 302
    assert response.headers['Location'].endswith(FORM_PATH)


def test_broken_image_goes_back_to_the_form(site_app, user):
    response = _post_avatar(site_app, user, _png_bytes()[:60])
    assert response.status_code == 302
    assert response.headers['Location'].endswith(FORM_PATH)


def test_too_large_upload_goes_back_to_the_form(site_app, user, monkeypatch):
    monkeypatch.setitem(site_app.config, 'MAX_CONTENT_LENGTH', 1000)
    response = _post_avatar(
        site_app, user, b'x' * 5000, headers={'Referer': BASE + FORM_PATH}
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith(FORM_PATH)


def test_too_large_upload_without_origin_page_gets_message(
    site_app, user, monkeypatch
):
    monkeypatch.setitem(site_app.config, 'MAX_CONTENT_LENGTH', 1000)
    response = _post_avatar(site_app, user, b'x' * 5000)
    assert response.status_code == 413
    assert 'zu groß' in response.get_data(as_text=True)
