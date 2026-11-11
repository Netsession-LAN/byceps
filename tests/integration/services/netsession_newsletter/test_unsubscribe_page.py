"""One-click unsubscribe from the newsletter mail, without login: the link
shows a confirmation, only the POST unsubscribes (link scanners)."""

from byceps.services.netsession_newsletter import unsubscribe_token

from byceps.services.newsletter import newsletter_service

from tests.helpers import http_client


BASE = 'http://www.acmecon.test/ns-newsletter/unsubscribe'


def test_get_only_asks_and_post_unsubscribes(
    site_app, newsletter_list, subscribe, make_user
):
    user = make_user(email_address_verified=True)
    subscribe(user, newsletter_list)
    token = unsubscribe_token.create(user.id, newsletter_list.id)

    with http_client(site_app) as client:
        shown = client.get(f'{BASE}/{token}')
        assert shown.status_code == 200
        assert 'Newsletter abmelden?' in shown.get_data(as_text=True)
        assert newsletter_service.is_user_subscribed_to_list(
            user.id, newsletter_list.id
        )

        done = client.post(f'{BASE}/{token}')

    assert done.status_code == 200
    assert 'abgemeldet' in done.get_data(as_text=True)
    assert not newsletter_service.is_user_subscribed_to_list(
        user.id, newsletter_list.id
    )


def test_invalid_token_shows_a_friendly_page(site_app):
    with http_client(site_app) as client:
        response = client.get(f'{BASE}/kaputt')
        posted = client.post(f'{BASE}/kaputt')

    assert response.status_code == 404
    assert 'Kontoeinstellungen' in response.get_data(as_text=True)
    assert posted.status_code == 404


def test_token_round_trip_and_tampering(site_app, newsletter_list, make_user):
    user = make_user()
    with site_app.app_context():
        token = unsubscribe_token.create(user.id, newsletter_list.id)
        assert unsubscribe_token.parse(token) == (user.id, newsletter_list.id)
        assert unsubscribe_token.parse(token[:-2] + 'xx') is None
