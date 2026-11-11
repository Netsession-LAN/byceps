"""BYCEPS tells the sync about newsletter and account changes: JSON with
user and list ID, signed with HMAC over timestamp and body."""

from datetime import datetime
import hashlib
import hmac
import json

from byceps.services.netsession_newsletter import sync_webhook
import pytest

from byceps.services.newsletter import signals as newsletter_signals
from byceps.services.newsletter.events import SubscribedToNewsletterEvent
from byceps.services.orga_team import orga_team_service
from byceps.services.user import signals as user_signals
from byceps.services.user.events import UserAccountSuspendedEvent

from tests.helpers import generate_token


@pytest.fixture()
def sent(monkeypatch):
    calls = []

    def fake_post(url, *, content, headers, timeout):
        calls.append((url, content, headers))

        class Response:
            def raise_for_status(self):
                return None

        return Response()

    monkeypatch.setenv(
        'NS_NEWSLETTER_SYNC_URL', 'https://sync.test/webhooks/byceps'
    )
    monkeypatch.setenv('NS_NEWSLETTER_SYNC_SECRET', 's3cret')
    monkeypatch.setattr(sync_webhook.httpx, 'post', fake_post)
    return calls


def _verify(content, headers):
    timestamp = headers['X-NS-Timestamp']
    expected = hmac.new(
        b's3cret', timestamp.encode() + b'.' + content, hashlib.sha256
    ).hexdigest()
    assert headers['X-NS-Signature'] == f'sha256={expected}'
    return json.loads(content)


def test_newsletter_signal_sends_signed_json(admin_app, sent, make_user):
    user = make_user()
    event = SubscribedToNewsletterEvent(
        occurred_at=datetime(2026, 11, 11, 8, 0),
        initiator=user,
        user=user,
        list_id='netsession',
        list_title='Netsession',
    )

    newsletter_signals.newsletter_subscribed.send(None, event=event)

    assert len(sent) == 1
    url, content, headers = sent[0]
    assert url == 'https://sync.test/webhooks/byceps'
    body = _verify(content, headers)
    assert body['event'] == 'newsletter-subscribed'
    assert body['user_id'] == str(user.id)
    assert body['list_id'] == 'netsession'
    assert body['occurred_at'] == '2026-11-11T08:00:00Z'
    assert body['event_id']


def test_account_suspension_is_user_deactivated(admin_app, sent, make_user):
    user = make_user()
    event = UserAccountSuspendedEvent(
        occurred_at=datetime(2026, 11, 11, 9, 0), initiator=None, user=user
    )

    user_signals.account_suspended.send(None, event=event)

    body = _verify(sent[0][1], sent[0][2])
    assert body['event'] == 'user-deactivated'
    assert body['list_id'] is None


def test_orga_membership_changes_send_user_updated(
    admin_app, sent, make_user, party
):
    user = make_user()
    team = orga_team_service.create_team(party.id, f'Orga {generate_token(4)}')

    membership = orga_team_service.create_membership(team.id, user.id, None)
    orga_team_service.delete_membership(membership.id)

    events = [_verify(content, headers) for _, content, headers in sent]
    assert [e['event'] for e in events] == ['user-updated', 'user-updated']
    assert {e['user_id'] for e in events} == {str(user.id)}


def test_nothing_is_sent_without_configured_url(
    admin_app, monkeypatch, make_user
):
    monkeypatch.delenv('NS_NEWSLETTER_SYNC_URL', raising=False)
    calls = []
    monkeypatch.setattr(
        sync_webhook.httpx, 'post', lambda *a, **k: calls.append(a)
    )
    user = make_user()
    event = UserAccountSuspendedEvent(
        occurred_at=datetime(2026, 11, 11, 9, 0), initiator=None, user=user
    )

    user_signals.account_suspended.send(None, event=event)

    assert calls == []
