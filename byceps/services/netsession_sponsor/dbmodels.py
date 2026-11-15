"""
byceps.services.netsession_sponsor.dbmodels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Keep in sync with `migrations/20261115_01_add_netsession_sponsors.sql`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from byceps.database import db
from byceps.services.party.models import PartyID

from .models import SponsorID


class DbNetsessionSponsor(db.Model):
    __tablename__ = 'netsession_sponsors'

    id: Mapped[SponsorID] = mapped_column(db.Uuid, primary_key=True)
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText,
        db.ForeignKey('parties.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str] = mapped_column(db.UnicodeText)
    logo_path: Mapped[str] = mapped_column(db.UnicodeText)
    logo_dark_path: Mapped[str | None] = mapped_column(db.UnicodeText)
    target_url: Mapped[str | None] = mapped_column(db.UnicodeText)
    position: Mapped[int]
    enabled: Mapped[bool] = mapped_column(server_default=db.true())
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
