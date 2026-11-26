"""
byceps.services.netsession_tourney.browser_push_keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

VAPID keys for browser push: generation and encrypted storage.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer

from .dbmodels import (
    DbNetsessionTourneyBrowserPushConfig,
)


def _ensure_browser_push_vapid_keys(
    db_config: DbNetsessionTourneyBrowserPushConfig,
) -> None:
    if db_config.vapid_public_key and db_config.vapid_private_key_encrypted:
        return

    private_key_pem = _generate_browser_push_private_key_pem()
    db_config.vapid_public_key = _derive_browser_push_public_key(
        private_key_pem
    )
    db_config.vapid_private_key_encrypted = _encrypt_browser_push_private_key(
        private_key_pem
    )


def _get_browser_push_fernet() -> Fernet:
    secret_key = current_app.config['SECRET_KEY']
    if isinstance(secret_key, str):
        raw = secret_key.encode('utf-8')
    else:
        raw = bytes(secret_key)

    key = urlsafe_b64encode(sha256(raw + b'browser-push').digest())
    return Fernet(key)


def _get_browser_push_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(
        current_app.config['SECRET_KEY'], salt='netsession_tourney.browser_push'
    )


def _generate_browser_push_private_key_pem() -> str:
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode('ascii')


def _derive_browser_push_public_key(private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode('ascii'), password=None
    )
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return urlsafe_b64encode(public_key_bytes).decode('ascii').rstrip('=')


def _encrypt_browser_push_private_key(private_key_pem: str) -> str:
    token = _get_browser_push_fernet().encrypt(private_key_pem.encode('utf-8'))
    return token.decode('ascii')


def decrypt_browser_push_private_key(token: str) -> str | None:
    try:
        decrypted = _get_browser_push_fernet().decrypt(token.encode('ascii'))
        return decrypted.decode('utf-8')
    except InvalidToken, UnicodeDecodeError:
        try:
            data = _get_browser_push_serializer().loads(token)
        except BadSignature:
            return None

        private_key_pem = data.get('private_key_pem')
        return private_key_pem if isinstance(private_key_pem, str) else None
