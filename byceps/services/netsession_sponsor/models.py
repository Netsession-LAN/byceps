"""
byceps.services.netsession_sponsor.models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NewType
from uuid import UUID

from byceps.services.party.models import PartyID


SponsorID = NewType('SponsorID', UUID)


@dataclass(frozen=True, kw_only=True)
class Sponsor:
    id: SponsorID
    party_id: PartyID
    name: str
    logo_path: str
    logo_dark_path: str | None
    target_url: str | None
    position: int
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @property
    def logo_url(self) -> str:
        """Paths are relative to the data directory, served at `/data/`."""
        return '/data/' + self.logo_path

    @property
    def logo_url_dark(self) -> str | None:
        return '/data/' + self.logo_dark_path if self.logo_dark_path else None
