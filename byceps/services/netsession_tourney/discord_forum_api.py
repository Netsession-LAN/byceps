"""
byceps.services.netsession_tourney.discord_forum_api
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Calls to the Discord API for forum threads (create, read, update, post).
"""

from __future__ import annotations

from typing import Any

import httpx


DISCORD_FORUM_TIMEOUT_SECONDS = 10


def is_discord_resource_missing(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code == 404


def _build_discord_bot_headers(
    *, application_id: str, bot_token: str
) -> dict[str, str]:
    return {
        'Authorization': f'Bot {bot_token}',
        'Content-Type': 'application/json',
        'User-Agent': f'BYCEPS Netsession/{application_id}',
    }


def create_discord_forum_thread(
    *,
    application_id: str,
    bot_token: str,
    forum_channel_id: str,
    payload: dict[str, Any],
) -> str:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.post(
            f'/channels/{forum_channel_id}/threads',
            json=payload,
        )
        response.raise_for_status()
        response_data = response.json()
        thread_id = str(response_data.get('id') or '').strip()
        if not thread_id:
            raise ValueError(
                'Discord-Forum-Thread konnte nicht erstellt werden.'
            )
        return thread_id


def get_discord_channel(
    *,
    application_id: str,
    bot_token: str,
    channel_id: str,
) -> dict[str, Any]:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.get(f'/channels/{channel_id}')
        response.raise_for_status()
        return response.json()


def patch_discord_channel(
    *,
    application_id: str,
    bot_token: str,
    channel_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.patch(f'/channels/{channel_id}', json=payload)
        response.raise_for_status()


def patch_discord_forum_starter_message(
    *,
    application_id: str,
    bot_token: str,
    thread_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.patch(
            f'/channels/{thread_id}/messages/{thread_id}',
            json=payload,
        )
        response.raise_for_status()


def post_discord_forum_message(
    *,
    application_id: str,
    bot_token: str,
    thread_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.post(
            f'/channels/{thread_id}/messages',
            json=payload,
        )
        response.raise_for_status()
