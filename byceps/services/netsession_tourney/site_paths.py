"""
byceps.services.netsession_tourney.site_paths
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Paths of public tournament pages (for notifications and links).
"""

from __future__ import annotations

from uuid import UUID

from .models import (
    MatchID,
)


def build_site_tournament_overview_path(slug: str) -> str:
    return f'/ns-tourneys/{slug}'


def build_site_match_path(slug: str, match_id: MatchID | UUID) -> str:
    return f'/ns-tourneys/{slug}/matches/{match_id}'
