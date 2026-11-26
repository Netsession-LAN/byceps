"""
byceps.services.netsession_tourney.discord_dm_token
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Encrypted storage and masking of the Discord DM bot token.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_discord_dm_fernet() -> Fernet:
    secret_key = current_app.config['SECRET_KEY']
    if isinstance(secret_key, str):
        raw = secret_key.encode('utf-8')
    else:
        raw = bytes(secret_key)

    key = urlsafe_b64encode(sha256(raw + b'discord-dm').digest())
    return Fernet(key)


def _encrypt_discord_dm_bot_token(bot_token: str) -> str:
    token = _get_discord_dm_fernet().encrypt(bot_token.encode('utf-8'))
    return token.decode('ascii')


def decrypt_discord_dm_bot_token(token: str | None) -> str | None:
    if not token:
        return None

    try:
        decrypted = _get_discord_dm_fernet().decrypt(token.encode('ascii'))
    except InvalidToken, ValueError:
        return None

    return decrypted.decode('utf-8')


def _mask_discord_dm_bot_token(bot_token: str | None) -> str:
    if not bot_token:
        return ''
    if len(bot_token) < 10:
        return '***'
    return bot_token[:6] + '***' + bot_token[-4:]
