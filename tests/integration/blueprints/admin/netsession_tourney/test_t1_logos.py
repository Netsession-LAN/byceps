"""Admin logo libraries: tournament logos, sponsor logos and Discord
forum images (upload, rename, delete).
"""

from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4

from PIL import Image
import pytest

from byceps.services.netsession_tourney import (
    discord_service,
    logo_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentMode,
)

from tests.helpers import generate_token


ADMIN_BASE_URL = 'http://admin.acmecon.test/ns-tourneys'


@dataclass(frozen=True)
class Library:
    segment: str
    noun: str
    get_assets: object
    in_use_message_start: str


TOURNAMENT_LOGOS = Library(
    'tournament',
    'Turnierlogo',
    logo_service.get_tournament_logo_assets,
    'Das Logo wird von 1 Turnier(en) verwendet',
)
SPONSOR_LOGOS = Library(
    'sponsor',
    'Sponsor-Logo',
    logo_service.get_sponsor_logo_assets,
    'Das Logo wird von 1 gesponserten Turnier(en) verwendet',
)
FORUM_IMAGES = Library(
    'discord-forum',
    'Discord-Forum-Bild',
    logo_service.get_discord_forum_image_assets,
    'Bild wird von 1 Turnier(en) verwendet',
)
LIBRARIES = [TOURNAMENT_LOGOS, SPONSOR_LOGOS, FORUM_IMAGES]
LIBRARY_IDS = [library.segment for library in LIBRARIES]


def _png() -> BytesIO:
    buffer = BytesIO()
    Image.new('RGB', (8, 8)).save(buffer, 'PNG')
    buffer.seek(0)
    return buffer


def _find_asset(library: Library, party_id, label: str):
    for asset in library.get_assets(party_id):
        if asset.label == label:
            return asset
    return None


def _upload(client, party_id, library: Library, label: str, **extra_data):
    return client.post(
        f'{ADMIN_BASE_URL}/for_party/{party_id}/logos/{library.segment}/upload',
        data={'file': (_png(), 'logo.png'), 'label': label, **extra_data},
        content_type='multipart/form-data',
    )


@pytest.fixture(scope='module')
def uploaded(tourney_admin_client, tourney_party):
    """Upload one asset per library; return them by URL segment."""
    assets = {}
    for library in LIBRARIES:
        label = f'T1 {library.segment} {generate_token()}'
        _upload(tourney_admin_client, tourney_party.id, library, label)
        assets[library.segment] = _find_asset(library, tourney_party.id, label)
    return assets


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_upload_stores_asset(
    tourney_admin_client, tourney_party, pop_flashes, library
):
    label = f'T1 Upload {generate_token()}'

    response = _upload(tourney_admin_client, tourney_party.id, library, label)

    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{tourney_party.id}/logos/{library.segment}'
    )
    assert pop_flashes(tourney_admin_client) == [
        f'{library.noun} wurde hochgeladen.'
    ]
    asset = _find_asset(library, tourney_party.id, label)
    assert asset is not None
    assert asset.party_id == tourney_party.id


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_index_lists_uploaded_asset(
    tourney_admin_client, tourney_party, uploaded, library
):
    response = tourney_admin_client.get(
        f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}/logos/{library.segment}'
    )

    assert response.status_code == 200
    assert uploaded[library.segment].label in response.get_data(as_text=True)


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_index_without_view_permission_is_forbidden(
    plain_admin_client, tourney_party, library
):
    response = plain_admin_client.get(
        f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}/logos/{library.segment}'
    )

    assert response.status_code == 403


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_upload_without_file_is_refused(
    tourney_admin_client, tourney_party, library
):
    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}/logos/{library.segment}/upload',
        data={'label': 'T1 No File'},
        content_type='multipart/form-data',
    )

    assert response.status_code == 200
    assert 'Bitte eine Datei auswählen.' in response.get_data(as_text=True)
    assert _find_asset(library, tourney_party.id, 'T1 No File') is None


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_upload_of_non_image_is_refused(
    tourney_admin_client, tourney_party, library
):
    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}/logos/{library.segment}/upload',
        data={'file': (BytesIO(b'hello'), 'notes.txt'), 'label': 'T1 Text'},
        content_type='multipart/form-data',
    )

    assert response.status_code == 200
    assert 'Dieses Dateiformat wird nicht unterstützt.' in response.get_data(
        as_text=True
    )
    assert _find_asset(library, tourney_party.id, 'T1 Text') is None


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_upload_by_viewer_is_forbidden(
    tourney_viewer_client, tourney_party, library
):
    response = _upload(
        tourney_viewer_client, tourney_party.id, library, 'T1 Viewer'
    )

    assert response.status_code == 403
    assert _find_asset(library, tourney_party.id, 'T1 Viewer') is None


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_update_form_shows_label(tourney_admin_client, uploaded, library):
    asset = uploaded[library.segment]

    response = tourney_admin_client.get(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{asset.id}/update'
    )

    assert response.status_code == 200
    assert asset.label in response.get_data(as_text=True)


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_update_form_of_unknown_asset_returns_404(
    tourney_admin_client, library
):
    response = tourney_admin_client.get(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{uuid4()}/update'
    )

    assert response.status_code == 404


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_rename(
    tourney_admin_client, tourney_party, uploaded, pop_flashes, library
):
    asset = uploaded[library.segment]
    new_label = f'T1 Renamed {generate_token()}'

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{asset.id}',
        data={'label': new_label, 'target_url': 'example.org'},
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{tourney_party.id}/logos/{library.segment}'
    )
    assert pop_flashes(tourney_admin_client) == [
        f'{library.noun} wurde umbenannt.'
    ]
    assert _find_asset(library, tourney_party.id, new_label) is not None


def test_rename_sponsor_logo_normalizes_target_url(
    tourney_admin_client, tourney_party, uploaded
):
    asset = uploaded[SPONSOR_LOGOS.segment]
    label = f'T1 Sponsor Link {generate_token()}'

    tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/logos/sponsor/{asset.id}',
        data={'label': label, 'target_url': 'example.org'},
    )

    renamed = logo_service.find_sponsor_logo_asset(asset.id)
    assert renamed.label == label
    assert renamed.target_url == 'https://example.org'


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_rename_without_label_shows_form_again(
    tourney_admin_client, uploaded, library
):
    asset = uploaded[library.segment]

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{asset.id}',
        data={'label': ''},
    )

    assert response.status_code == 200


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_rename_to_blank_label_is_refused(
    tourney_admin_client, uploaded, library
):
    asset = uploaded[library.segment]

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{asset.id}',
        data={'label': '   '},
    )

    assert response.status_code == 200
    assert 'leer sein' in response.get_data(as_text=True)


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_rename_of_unknown_asset_returns_404(tourney_admin_client, library):
    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{uuid4()}',
        data={'label': 'T1 Ghost'},
    )

    assert response.status_code == 404


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_delete(tourney_admin_client, tourney_party, pop_flashes, library):
    label = f'T1 Doomed {generate_token()}'
    _upload(tourney_admin_client, tourney_party.id, library, label)
    pop_flashes(tourney_admin_client)
    asset = _find_asset(library, tourney_party.id, label)

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{asset.id}/delete'
    )

    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{tourney_party.id}/logos/{library.segment}'
    )
    assert pop_flashes(tourney_admin_client) == [
        f'{library.noun} wurde gelöscht.'
    ]
    assert _find_asset(library, tourney_party.id, label) is None


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_delete_of_unknown_asset_returns_404(tourney_admin_client, library):
    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{uuid4()}/delete'
    )

    assert response.status_code == 404


def _use_in_tournament(library: Library, party_id, admin, url_path: str):
    kwargs = {}
    if library is TOURNAMENT_LOGOS:
        kwargs = {'logo_url': url_path}
    elif library is SPONSOR_LOGOS:
        kwargs = {'is_sponsored': True, 'sponsor_logo_url': url_path}
    tournament = tournament_service.create_tournament(
        party_id,
        f't1-uses-{generate_token().lower()}',
        'T1 Uses Asset',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin,
        **kwargs,
    ).unwrap()
    if library is FORUM_IMAGES:
        discord_service.configure_discord(
            party_id,
            tournament.id,
            admin,
            enabled=True,
            forum_channel_id='123456789012345678',
            discord_forum_image_url=url_path,
            applied_tag_ids=[],
            event_mask=['tournament_live'],
            discord_dm_enabled=False,
            discord_dm_event_mask=[],
        ).unwrap()


@pytest.mark.parametrize('library', LIBRARIES, ids=LIBRARY_IDS)
def test_delete_of_asset_in_use_is_refused(
    tourney_admin_client, tourney_party, tourney_admin, pop_flashes, library
):
    label = f'T1 In Use {generate_token()}'
    _upload(tourney_admin_client, tourney_party.id, library, label)
    pop_flashes(tourney_admin_client)
    asset = _find_asset(library, tourney_party.id, label)
    _use_in_tournament(library, tourney_party.id, tourney_admin, asset.url_path)

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/logos/{library.segment}/{asset.id}/delete'
    )

    assert response.status_code == 302
    (message,) = pop_flashes(tourney_admin_client)
    assert message.startswith(library.in_use_message_start)
    assert _find_asset(library, tourney_party.id, label) is not None
