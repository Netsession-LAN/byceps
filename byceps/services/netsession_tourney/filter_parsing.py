"""
byceps.services.netsession_tourney.filter_parsing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournament list filters from query strings (site and API).
"""

from __future__ import annotations

from .models import TournamentMode, TournamentStatus


def parse_tournament_status(value: str | None) -> TournamentStatus | None:
    if not value:
        return None
    try:
        return TournamentStatus(value)
    except ValueError:
        return None


def parse_tournament_mode(value: str | None) -> TournamentMode | None:
    if not value:
        return None
    try:
        return TournamentMode(value)
    except ValueError:
        return None
