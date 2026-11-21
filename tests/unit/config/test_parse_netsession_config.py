"""Netsession: config sections of our own (Steam, Turnstile, tourney flag)."""

from textwrap import dedent

from byceps.config.models import CloudflareTurnstileConfig, SteamConfig
from byceps.config.parser import parse_config


BASE_TOML = """\
locale = "de"
secret_key = "<RANDOM-BYTES>"
timezone = "Europe/Berlin"

[apps]
admin = { server_name = "admin.test" }

[database]
username = "db-user"
password = "db-password"
database = "db-database"

[redis]
url = "redis://127.0.0.1:6379/0"

[smtp]
"""


def test_netsession_sections_are_read():
    toml = dedent("""\
    netsession_tourney_enabled = true
    """) + BASE_TOML + dedent("""\

    [steam]
    enabled = true
    api_key = "steam-key"

    [cloudflare_turnstile]
    enabled = true
    sitekey = "site-key"
    secret_key = "secret"
    """)

    byceps_config, _ = parse_config(toml).unwrap()

    assert byceps_config.netsession_tourney_enabled is True
    assert byceps_config.steam == SteamConfig(enabled=True, api_key='steam-key')
    assert byceps_config.cloudflare_turnstile == CloudflareTurnstileConfig(
        enabled=True, sitekey='site-key', secret_key='secret'
    )


def test_netsession_sections_are_optional():
    byceps_config, _ = parse_config(BASE_TOML).unwrap()

    assert byceps_config.netsession_tourney_enabled is False
    assert byceps_config.steam is None
    assert byceps_config.cloudflare_turnstile == CloudflareTurnstileConfig()
