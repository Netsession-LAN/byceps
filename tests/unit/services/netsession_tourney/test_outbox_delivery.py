"""Netsession: delivery of queued Discord posts and browser pushes."""

from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from byceps.services.netsession_tourney import (
    browser_push_outbox,
    discord_service,
)


NOW = datetime(2026, 11, 5, 12, 0)


def _http_status_error(status=404):
    request = httpx.Request('POST', 'https://discord.test')
    return httpx.HTTPStatusError(
        'boom',
        request=request,
        response=httpx.Response(status, request=request),
    )


@pytest.fixture
def discord(monkeypatch):
    """Discord delivery with database and API replaced by fakes."""
    calls = SimpleNamespace(posted=[], retries=[], dead=[], warnings=[])
    tournament = SimpleNamespace(
        discord_enabled=True,
        discord_forum_channel_id='forum',
        discord_thread_id='thread-1',
    )
    monkeypatch.setattr(
        discord_service.db,
        'session',
        SimpleNamespace(get=lambda *_: tournament),
    )
    monkeypatch.setattr(
        discord_service,
        'build_discord_message_payload',
        lambda *_: {'content': 'x'},
    )
    monkeypatch.setattr(
        discord_service,
        '_schedule_discord_outbox_retry',
        lambda row, message, now: calls.retries.append(message),
    )
    monkeypatch.setattr(
        discord_service,
        '_mark_discord_outbox_dead_letter',
        lambda row, message, now: calls.dead.append(message),
    )
    monkeypatch.setattr(
        discord_service.log,
        'warning',
        lambda *a, **kw: calls.warnings.append(kw),
    )
    calls.tournament = tournament
    return calls


def _row():
    return SimpleNamespace(
        id='row',
        tournament_id='t',
        event_name='match_completed',
        status='pending',
        next_attempt_at=NOW,
        last_error='old',
    )


def _set_post(monkeypatch, discord, *outcomes):
    """Each post call takes the next outcome: None = ok, or an exception."""
    queue = list(outcomes)

    def post(*, thread_id, **_):
        discord.posted.append(thread_id)
        outcome = queue.pop(0)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(discord_service, 'post_discord_forum_message', post)


def test_discord_post_marks_row_sent(monkeypatch, discord):
    _set_post(monkeypatch, discord, None)
    row = _row()

    discord_service._deliver_discord_outbox_row(
        row, ('app', 'token'), None, NOW
    )

    assert discord.posted == ['thread-1']
    assert (row.status, row.next_attempt_at, row.last_error) == (
        'sent',
        None,
        None,
    )


def test_discord_deleted_thread_is_recreated_and_post_repeated(
    monkeypatch, discord
):
    _set_post(monkeypatch, discord, _http_status_error(404), None)
    monkeypatch.setattr(
        discord_service,
        'recover_deleted_discord_forum_thread',
        lambda **_: 'thread-2',
    )
    row = _row()

    discord_service._deliver_discord_outbox_row(
        row, ('app', 'token'), None, NOW
    )

    assert discord.posted == ['thread-1', 'thread-2']
    assert row.status == 'sent'


def test_discord_http_error_schedules_retry(monkeypatch, discord):
    _set_post(monkeypatch, discord, httpx.ConnectError('down'))
    row = _row()

    discord_service._deliver_discord_outbox_row(
        row, ('app', 'token'), None, NOW
    )

    assert discord.retries == [
        'Discord-Forum-Anfrage fehlgeschlagen: ConnectError'
    ]
    assert discord.warnings[0]['error'] == 'ConnectError'
    assert row.status == 'pending'


def test_discord_unrecoverable_status_error_schedules_retry(
    monkeypatch, discord
):
    _set_post(monkeypatch, discord, _http_status_error(500))
    monkeypatch.setattr(
        discord_service,
        'recover_deleted_discord_forum_thread',
        lambda **_: None,
    )

    discord_service._deliver_discord_outbox_row(
        _row(), ('app', 'token'), None, NOW
    )

    assert discord.retries == [
        'Discord-Forum-Anfrage fehlgeschlagen: HTTPStatusError'
    ]


def test_discord_without_bot_waits_and_disabled_forum_gives_up(discord):
    discord_service._deliver_discord_outbox_row(_row(), None, 'kein Bot', NOW)
    assert discord.retries == ['kein Bot']

    discord.tournament.discord_enabled = False
    discord_service._deliver_discord_outbox_row(
        _row(), ('app', 'token'), None, NOW
    )
    assert discord.dead == [
        'Discord-Forum ist für dieses Turnier nicht aktiviert.'
    ]


def _subscription(endpoint):
    return SimpleNamespace(
        endpoint=endpoint,
        endpoint_p256dh='k',
        endpoint_auth='a',
        enabled=True,
        updated_at=None,
    )


def _push(monkeypatch, outcome_by_endpoint):
    class FakeWebPushException(Exception):
        def __init__(self, status):
            super().__init__(f'status {status}')
            self.response = SimpleNamespace(status_code=status)

    def webpush(*, subscription_info, **_):
        outcome = outcome_by_endpoint[subscription_info['endpoint']]
        if outcome is not None:
            raise FakeWebPushException(outcome)

    monkeypatch.setattr(browser_push_outbox, 'webpush', webpush)
    monkeypatch.setattr(
        browser_push_outbox, 'WebPushException', FakeWebPushException
    )
    monkeypatch.setattr(
        browser_push_outbox,
        '_build_browser_push_vapid_subject',
        lambda *_: 'mailto:x',
    )


def _send(subscriptions):
    return browser_push_outbox._push_to_subscriptions(
        subscriptions,
        SimpleNamespace(party_id='p'),
        message={'title': 'x'},
        vapid_private_key='key',
        now=NOW,
    )


def test_push_delivered_to_one_of_several_browsers(monkeypatch):
    _push(monkeypatch, {'ok': None, 'down': 503})

    assert _send([_subscription('ok'), _subscription('down')]) == (
        True,
        'FakeWebPushException: status 503',
    )


def test_expired_subscription_is_disabled_without_retry(monkeypatch):
    _push(monkeypatch, {'gone': 410})
    subscription = _subscription('gone')

    assert _send([subscription]) == (False, None)
    assert subscription.enabled is False
    assert subscription.updated_at == NOW


def test_temporary_push_error_is_reported(monkeypatch):
    _push(monkeypatch, {'down': 503})

    assert _send([_subscription('down')]) == (
        False,
        'FakeWebPushException: status 503',
    )
