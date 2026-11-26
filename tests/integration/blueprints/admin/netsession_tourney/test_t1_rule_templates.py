"""Admin rule templates of a party."""

from uuid import uuid4

import pytest

from byceps.services.netsession_tourney import tournament_rule_template_service
from byceps.services.netsession_tourney.models import RuleTemplateBodyFormat


ADMIN_BASE_URL = 'http://admin.acmecon.test/ns-tourneys'


@pytest.fixture(scope='module')
def party_url(tourney_party):
    return f'{ADMIN_BASE_URL}/for_party/{tourney_party.id}'


def _create_rule_template(party_id, slug: str, title: str = 'T1 Rules'):
    return tournament_rule_template_service.create_tournament_rule_template(
        party_id, slug, title, RuleTemplateBodyFormat.markdown, '# Rules'
    ).unwrap()


def _rule_template_slugs(party_id) -> set[str]:
    return {
        template.slug
        for template in tournament_rule_template_service.get_tournament_rule_templates_for_party(
            party_id
        )
    }


def test_rule_template_index_lists_templates(
    tourney_viewer_client, party_url, tourney_party
):
    _create_rule_template(tourney_party.id, 't1-listed', 'T1 Listed Rules')

    response = tourney_viewer_client.get(f'{party_url}/rules')

    assert response.status_code == 200
    assert 'T1 Listed Rules' in response.get_data(as_text=True)


def test_rule_template_index_with_unknown_party_returns_404(
    tourney_admin_client,
):
    response = tourney_admin_client.get(f'{ADMIN_BASE_URL}/for_party/x/rules')

    assert response.status_code == 404


def test_rule_template_create_form_renders(tourney_admin_client, party_url):
    response = tourney_admin_client.get(f'{party_url}/rules/create')

    assert response.status_code == 200


def test_rule_template_create_form_needs_manage_permission(
    tourney_viewer_client, party_url
):
    response = tourney_viewer_client.get(f'{party_url}/rules/create')

    assert response.status_code == 403


def test_rule_template_create(
    tourney_admin_client, party_url, tourney_party, pop_flashes
):
    response = tourney_admin_client.post(
        f'{party_url}/rules',
        data={
            'slug': 't1-cs2-rules',
            'title': 'T1 CS2 Rules',
            'body_format': 'html',
            'body': '<p>Play fair.</p>',
        },
    )

    assert response.status_code == 302
    assert response.location.endswith(f'/for_party/{tourney_party.id}/rules')
    assert pop_flashes(tourney_admin_client) == [
        'Regeltemplate "T1 CS2 Rules" wurde erstellt.'
    ]
    template = tournament_rule_template_service.find_tournament_rule_template_by_slug_for_party(
        tourney_party.id, 't1-cs2-rules'
    )
    assert template.title == 'T1 CS2 Rules'
    assert template.body_format == RuleTemplateBodyFormat.html
    assert template.body == '<p>Play fair.</p>'


def test_rule_template_create_with_invalid_slug_shows_form_again(
    tourney_admin_client, party_url, tourney_party
):
    response = tourney_admin_client.post(
        f'{party_url}/rules',
        data={
            'slug': 'Not A Slug',
            'title': 'T1 Bad Slug',
            'body_format': 'markdown',
            'body': 'text',
        },
    )

    assert response.status_code == 200
    assert (
        'Erlaubt sind Kleinbuchstaben, Ziffern und Bindestrich.'
        in response.get_data(as_text=True)
    )
    assert 'Not A Slug' not in _rule_template_slugs(tourney_party.id)


def test_rule_template_create_with_taken_slug_is_refused(
    tourney_admin_client, party_url, tourney_party
):
    _create_rule_template(tourney_party.id, 't1-taken')

    response = tourney_admin_client.post(
        f'{party_url}/rules',
        data={
            'slug': 't1-taken',
            'title': 'T1 Second',
            'body_format': 'markdown',
            'body': 'text',
        },
    )

    assert response.status_code == 200
    assert (
        'Diesen Slug verwendet bereits eine andere Regel-Vorlage.'
        in response.get_data(as_text=True)
    )


def test_rule_template_update_form_shows_values(
    tourney_admin_client, tourney_party
):
    template = _create_rule_template(
        tourney_party.id, 't1-edit-form', 'T1 Edit Form'
    )

    response = tourney_admin_client.get(
        f'{ADMIN_BASE_URL}/rules/{template.id}/update'
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 't1-edit-form' in body
    assert 'T1 Edit Form' in body


def test_rule_template_update_form_of_unknown_template_returns_404(
    tourney_admin_client,
):
    response = tourney_admin_client.get(
        f'{ADMIN_BASE_URL}/rules/{uuid4()}/update'
    )

    assert response.status_code == 404


def test_rule_template_update(tourney_admin_client, tourney_party, pop_flashes):
    template = _create_rule_template(tourney_party.id, 't1-update-me')

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/rules/{template.id}',
        data={
            'slug': 't1-updated',
            'title': 'T1 Updated Rules',
            'body_format': 'markdown',
            'body': '## New',
        },
    )

    assert response.status_code == 302
    assert response.location.endswith(f'/for_party/{tourney_party.id}/rules')
    assert pop_flashes(tourney_admin_client) == [
        'Regeltemplate "T1 Updated Rules" wurde aktualisiert.'
    ]
    updated = tournament_rule_template_service.find_tournament_rule_template(
        template.id
    )
    assert updated.slug == 't1-updated'
    assert updated.body == '## New'


def test_rule_template_update_with_invalid_form_shows_form_again(
    tourney_admin_client, tourney_party
):
    template = _create_rule_template(tourney_party.id, 't1-keep-slug')

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/rules/{template.id}',
        data={'slug': 't1-keep-slug', 'title': '', 'body_format': 'html'},
    )

    assert response.status_code == 200
    unchanged = tournament_rule_template_service.find_tournament_rule_template(
        template.id
    )
    assert unchanged.title == 'T1 Rules'


def test_rule_template_update_to_taken_slug_is_refused(
    tourney_admin_client, tourney_party
):
    _create_rule_template(tourney_party.id, 't1-occupied')
    template = _create_rule_template(tourney_party.id, 't1-wants-occupied')

    response = tourney_admin_client.post(
        f'{ADMIN_BASE_URL}/rules/{template.id}',
        data={
            'slug': 't1-occupied',
            'title': 'T1 Rules',
            'body_format': 'markdown',
            'body': 'text',
        },
    )

    assert response.status_code == 200
    assert (
        'Diesen Slug verwendet bereits eine andere Regel-Vorlage.'
        in response.get_data(as_text=True)
    )


def test_rule_template_update_by_viewer_is_forbidden(
    tourney_viewer_client, tourney_party
):
    template = _create_rule_template(tourney_party.id, 't1-viewer-target')

    response = tourney_viewer_client.post(
        f'{ADMIN_BASE_URL}/rules/{template.id}',
        data={'slug': 't1-hacked', 'title': 'x', 'body_format': 'html'},
    )

    assert response.status_code == 403
