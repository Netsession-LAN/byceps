"""
byceps.services.netsession_tourney.notification_urls
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Absolute URLs for notifications sent outside the site (browser push, Discord): site host, assets, logos.
"""

from __future__ import annotations

from byceps.services.party import party_setting_service
from byceps.services.party.models import PartyID
from byceps.services.site import site_service
from byceps.services.site.models import SiteID

from .dbmodels import (
    DbNetsessionTourneyTournament,
)


def build_absolute_notification_url(
    party_id: PartyID, url_path: str
) -> str | None:
    path = (url_path or '').strip()
    if not path:
        return None

    if path.startswith('http://') or path.startswith('https://'):
        return path

    server_name = find_browser_push_site_server_name(party_id)
    if not server_name:
        return path if path.startswith('/') else f'/{path}'

    normalized_path = path if path.startswith('/') else f'/{path}'
    return f'https://{server_name}{normalized_path}'


def find_browser_push_site_server_name(party_id: PartyID) -> str | None:
    primary_party_site_id = party_setting_service.find_setting_value(
        party_id, 'primary_party_site_id'
    )
    if primary_party_site_id:
        site = site_service.find_site(SiteID(primary_party_site_id))
        if site and site.server_name:
            return site.server_name.strip()

    for site in site_service.get_all_sites():
        if (
            site.party_id == party_id
            and site.enabled
            and not site.archived
            and site.server_name
        ):
            return site.server_name.strip()

    return None


def build_browser_push_logo_urls(
    db_tournament: DbNetsessionTourneyTournament,
) -> tuple[str, str | None]:
    fallback_icon_url = _to_browser_push_asset_url(
        '/static_sites/netsession/icon-192.png'
    )
    return fallback_icon_url, None


def build_browser_push_badge_url() -> str:
    return _to_browser_push_asset_url('/static_sites/netsession/icon-192.png')


def _to_browser_push_asset_url(url_or_path: str) -> str:
    normalized = url_or_path.strip()
    if normalized.startswith(('http://', 'https://')):
        return normalized
    if not normalized.startswith('/'):
        normalized = '/' + normalized
    return normalized
