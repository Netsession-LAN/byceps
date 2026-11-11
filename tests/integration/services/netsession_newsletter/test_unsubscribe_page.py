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
        assert 'Abmelden?' in shown.get_data(as_text=True)
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


RESUB = 'http://www.acmecon.test/ns-newsletter/resubscribe'


def test_done_page_offers_resubscribing_with_the_same_token(
    site_app, newsletter_list, subscribe, make_user
):
    user = make_user(email_address_verified=True)
    subscribe(user, newsletter_list)
    token = unsubscribe_token.create(user.id, newsletter_list.id)

    with http_client(site_app) as client:
        done = client.post(f'{BASE}/{token}')

    assert f'/ns-newsletter/resubscribe/{token}' in done.get_data(as_text=True)


def test_resubscribe_get_only_asks_and_post_subscribes(
    site_app, newsletter_list, make_user, monkeypatch
):
    from byceps.services.newsletter import signals as newsletter_signals

    user = make_user(email_address_verified=True)
    token = unsubscribe_token.create(user.id, newsletter_list.id)
    received = []

    def receiver(sender, *, event=None, **kwargs):
        received.append(event)

    newsletter_signals.newsletter_subscribed.connect(receiver)
    try:
        with http_client(site_app) as client:
            shown = client.get(f'{RESUB}/{token}')
            assert shown.status_code == 200
            assert 'Wieder anmelden?' in shown.get_data(as_text=True)
            assert not newsletter_service.is_user_subscribed_to_list(
                user.id, newsletter_list.id
            )

            done = client.post(f'{RESUB}/{token}')
            again = client.post(f'{RESUB}/{token}')
    finally:
        newsletter_signals.newsletter_subscribed.disconnect(receiver)

    assert done.status_code == 200
    assert again.status_code == 200
    assert newsletter_service.is_user_subscribed_to_list(
        user.id, newsletter_list.id
    )
    # the second click changes nothing and sends no second event
    assert len(received) == 1
    assert received[0].user.id == user.id


def test_resubscribe_with_invalid_token(site_app):
    with http_client(site_app) as client:
        response = client.get(f'{RESUB}/kaputt')
        posted = client.post(f'{RESUB}/kaputt')

    assert response.status_code == 404
    assert 'Kontoeinstellungen' in response.get_data(as_text=True)
    assert posted.status_code == 404
