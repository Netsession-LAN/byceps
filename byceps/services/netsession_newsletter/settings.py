"""
byceps.services.netsession_newsletter.settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Per-server settings from the environment (set in the server's `.env`,
passed through `compose.yaml`):

- `NS_NEWSLETTER_SYNC_URL`: where change events are posted; empty = off.
- `NS_NEWSLETTER_SYNC_SECRET`: HMAC secret shared with the sync service.
- `NS_NEWSLETTER_SITE_ID`: site whose party counts as the current party
  for the orga flag (default `netsession`).
"""

from __future__ import annotations

import os

from byceps.services.party.models import PartyID
from byceps.services.site import site_service
from byceps.services.site.models import SiteID


def get_sync_url() -> str | None:
    return os.environ.get('NS_NEWSLETTER_SYNC_URL', '').strip() or None


def get_sync_secret() -> str:
    """Trimmed: a stray CR from a Windows-edited `.env` survives
    `deploy.sh` (which sources the file) and would break the HMAC."""
    return os.environ.get('NS_NEWSLETTER_SYNC_SECRET', '').strip()


def find_current_party_id() -> PartyID | None:
    """The party of the configured site, or None without one."""
    site_id = (
        os.environ.get('NS_NEWSLETTER_SITE_ID', '').strip() or 'netsession'
    )
    site = site_service.find_site(SiteID(site_id))
    return site.party_id if site is not None else None
