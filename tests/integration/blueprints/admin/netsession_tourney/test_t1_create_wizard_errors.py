"""Tournament creation wizard: missing steps, invalid input and
permissions.
"""

import pytest

from byceps.services.netsession_tourney import (
    logo_service,
    tournament_rule_template_service,
)
from byceps.services.netsession_tourney.models import RuleTemplateBodyFormat

from .t1_wizard_steps import (
    ADMIN_BASE_URL,
    create_wizard_party,
    png,
    post_details,
    post_format,
    post_schedule,
)


STEP_REQUESTS = [
    ('GET', 'format'),
    ('POST', 'format'),
    ('GET', 'details'),
    ('POST', 'details'),
    ('GET', 'schedule'),
    ('POST', 'schedule'),
    ('GET', 'review'),
    ('POST', 'review'),
]


@pytest.fixture
def wizard_party(make_party, brand):
    return create_wizard_party(make_party, brand)


def _request(client, method: str, url: str):
    return client.open(url, method=method, data={})


@pytest.mark.parametrize(('method', 'step'), STEP_REQUESTS)
def test_party_without_categories_is_sent_to_categories(
    tourney_admin_client, make_party, brand, pop_flashes, method, step
):
    party = make_party(brand)
    url = f'{ADMIN_BASE_URL}/for_party/{party.id}/create/{step}'

    response = _request(tourney_admin_client, method, url)

    assert response.status_code == 302
    assert response.location.endswith(f'/for_party/{party.id}/categories')
    assert pop_flashes(tourney_admin_client) == [
        'Es existieren noch keine Kategorien. Bitte zuerst eine Kategorie anlegen.'
    ]


@pytest.mark.parametrize(('method', 'step'), STEP_REQUESTS[2:])
def test_steps_without_format_are_sent_to_format(
    tourney_admin_client, wizard_party, method, step
):
    response = _request(
        tourney_admin_client, method, wizard_party.step_url(step)
    )

    assert response.status_code == 302
    assert response.location.endswith('/create/format')


@pytest.mark.parametrize(('method', 'step'), STEP_REQUESTS[4:])
def test_steps_without_details_are_sent_to_details(
    tourney_admin_client, wizard_party, method, step
):
    post_format(tourney_admin_client, wizard_party)

    response = _request(
        tourney_admin_client, method, wizard_party.step_url(step)
    )

    assert response.status_code == 302
    assert response.location.endswith('/create/details')


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_review_without_schedule_is_sent_to_schedule(
    tourney_admin_client, wizard_party, method
):
    post_format(tourney_admin_client, wizard_party)
    post_details(tourney_admin_client, wizard_party)

    response = _request(
        tourney_admin_client, method, wizard_party.step_url('review')
    )

    assert response.status_code == 302
    assert response.location.endswith('/create/schedule')


@pytest.mark.parametrize(('method', 'step'), STEP_REQUESTS)
def test_steps_need_manage_permission(
    tourney_viewer_client, wizard_party, method, step
):
    url = wizard_party.step_url(step)

    response = _request(tourney_viewer_client, method, url)

    assert response.status_code == 403


def test_steps_of_unknown_party_return_404(tourney_admin_client):
    url = f'{ADMIN_BASE_URL}/for_party/no-such-party/create/format'

    assert tourney_admin_client.get(url).status_code == 404


def test_format_with_invalid_values_shows_form_again(
    tourney_admin_client, wizard_party
):
    response = post_format(
        tourney_admin_client, wizard_party, mode='chess', coin_cost='-1'
    )

    assert response.status_code == 200
    follow_up = tourney_admin_client.get(wizard_party.step_url('details'))
    assert follow_up.location.endswith('/create/format')


def test_details_with_invalid_slug_shows_form_again(
    tourney_admin_client, wizard_party
):
    post_format(tourney_admin_client, wizard_party)

    response = post_details(tourney_admin_client, wizard_party, slug='Bad Slug')

    assert response.status_code == 200
    assert (
        'Erlaubt sind Kleinbuchstaben, Ziffern und Bindestrich.'
        in response.get_data(as_text=True)
    )


@pytest.mark.parametrize(
    ('overrides', 'expected_message'),
    [
        ({'is_sponsored': 'y'}, 'Bitte ein Sponsor-Logo auswählen.'),
        (
            {'discord_enabled': 'y'},
            'Bitte eine Discord-Forum-Channel-ID angeben.',
        ),
        (
            {'discord_enabled': 'y', 'forum_channel_id': '123456789012345678'},
            'Bitte mindestens ein Discord-Forum-Event auswählen.',
        ),
    ],
)
def test_details_with_incomplete_choice_is_refused(
    tourney_admin_client, wizard_party, overrides, expected_message
):
    post_format(tourney_admin_client, wizard_party)

    response = post_details(tourney_admin_client, wizard_party, **overrides)

    assert response.status_code == 200
    assert expected_message in response.get_data(as_text=True)
    follow_up = tourney_admin_client.get(wizard_party.step_url('schedule'))
    assert follow_up.location.endswith('/create/details')


def test_details_with_deleted_logo_is_refused(
    tourney_admin_client, wizard_party, tourney_admin
):
    logo_url = logo_service.upload_tournament_logo_image(
        wizard_party.party.id, tourney_admin, png(), label='T1 Soon Gone'
    ).unwrap()
    (asset,) = [
        asset
        for asset in logo_service.get_tournament_logo_assets(
            wizard_party.party.id
        )
        if asset.url_path == logo_url
    ]
    post_format(tourney_admin_client, wizard_party)
    post_details(
        tourney_admin_client, wizard_party, tournament_logo_url=logo_url
    )
    logo_service.delete_tournament_logo_asset(asset.id).unwrap()

    page = tourney_admin_client.get(wizard_party.step_url('details'))
    response = post_details(
        tourney_admin_client, wizard_party, tournament_logo_url=logo_url
    )

    assert f'{logo_url} (nicht gefunden)' in page.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Ungültiges Turnierlogo ausgewählt.' in response.get_data(
        as_text=True
    )


def test_details_with_deleted_sponsor_logo_is_refused(
    tourney_admin_client, wizard_party, tourney_admin
):
    logo_url = logo_service.upload_sponsor_logo_image(
        wizard_party.party.id, tourney_admin, png(), label='T1 Sponsor Gone'
    ).unwrap()
    (asset,) = [
        asset
        for asset in logo_service.get_sponsor_logo_assets(wizard_party.party.id)
        if asset.url_path == logo_url
    ]
    details = {'is_sponsored': 'y', 'sponsor_logo_url': logo_url}
    post_format(tourney_admin_client, wizard_party)
    post_details(tourney_admin_client, wizard_party, **details)
    logo_service.delete_sponsor_logo_asset(asset.id).unwrap()

    response = post_details(tourney_admin_client, wizard_party, **details)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'{logo_url} (nicht gefunden)' in body
    assert 'Ungültiges Sponsor-Logo ausgewählt.' in body


def test_details_keep_renamed_rule_template_selectable(
    tourney_admin_client, wizard_party
):
    template = tournament_rule_template_service.create_tournament_rule_template(
        wizard_party.party.id,
        't1-old-rules',
        'T1 Old Rules',
        RuleTemplateBodyFormat.markdown,
        'text',
    ).unwrap()
    post_format(tourney_admin_client, wizard_party)
    post_details(
        tourney_admin_client, wizard_party, rules_template_slug='t1-old-rules'
    )
    tournament_rule_template_service.update_tournament_rule_template(
        template.id,
        't1-new-rules',
        'T1 Old Rules',
        RuleTemplateBodyFormat.markdown,
        'text',
    ).unwrap()

    response = tourney_admin_client.get(wizard_party.step_url('details'))

    assert response.status_code == 200
    assert 't1-old-rules (nicht gefunden)' in response.get_data(as_text=True)


def test_schedule_with_invalid_date_shows_form_again(
    tourney_admin_client, wizard_party
):
    post_format(tourney_admin_client, wizard_party)
    post_details(tourney_admin_client, wizard_party)

    response = post_schedule(
        tourney_admin_client, wizard_party, starts_at='next friday'
    )

    assert response.status_code == 200
    follow_up = tourney_admin_client.get(wizard_party.step_url('review'))
    assert follow_up.location.endswith('/create/schedule')
