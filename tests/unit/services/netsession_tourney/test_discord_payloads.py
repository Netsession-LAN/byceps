"""
:Copyright: 2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from byceps.services.netsession_tourney import discord_payloads


@pytest.fixture(autouse=True)
def _fake_absolute_urls(monkeypatch):
    monkeypatch.setattr(
        discord_payloads,
        'build_absolute_notification_url',
        lambda party_id, path: 'https://example.test' + path,
    )


def _build_payload(event_name, payload_json):
    tournament = SimpleNamespace(
        party_id='party-1', slug='cs2', title='CS2 5on5'
    )
    row = SimpleNamespace(
        event_name=event_name,
        payload_json=payload_json,
        created_at=datetime(2026, 11, 27, 12, 0),
    )
    return discord_payloads.build_discord_message_payload(tournament, row)


def _field_value(embed, name):
    return next(field['value'] for field in embed['fields'] if field['name'] == name)


def test_manual_announcement_uses_its_own_title():
    payload = _build_payload(
        'manual_announcement',
        {'title': ' Pause bis 20 Uhr ', 'body': 'Essen ist da.'},
    )

    embed = payload['embeds'][0]
    assert embed['title'] == 'Pause bis 20 Uhr'
    assert embed['description'] == 'Essen ist da.'
    assert _field_value(embed, 'Ereignis') == 'Turnier-Update'


def test_manual_announcement_without_title_falls_back_to_the_event_name():
    payload = _build_payload('manual_announcement', {'body': 'Essen ist da.'})

    embed = payload['embeds'][0]
    assert embed['title'] == 'Turnier-Update'
    assert _field_value(embed, 'Ereignis') == 'Turnier-Update'
