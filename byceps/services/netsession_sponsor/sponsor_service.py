"""
byceps.services.netsession_sponsor.sponsor_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sponsors of a party, in display order (`position`, 1 = first). Logo
files stay on disk when a sponsor is deleted (they may be referenced
elsewhere, e.g. by tournament sponsor links).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import DbNetsessionSponsor
from .models import Sponsor, SponsorID


def create_sponsor(
    party_id: PartyID,
    name: str,
    logo_path: str,
    *,
    logo_dark_path: str | None = None,
    target_url: str | None = None,
    enabled: bool = True,
) -> Sponsor:
    now = datetime.utcnow()
    last_position = db.session.scalar(
        select(func.max(DbNetsessionSponsor.position)).filter_by(
            party_id=party_id
        )
    )
    db_sponsor = DbNetsessionSponsor(
        id=SponsorID(generate_uuid7()),
        party_id=party_id,
        name=name.strip(),
        logo_path=logo_path,
        logo_dark_path=logo_dark_path,
        target_url=_normalize_url(target_url),
        position=(last_position or 0) + 1,
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )
    db.session.add(db_sponsor)
    db.session.commit()
    return _to_model(db_sponsor)


def update_sponsor(
    sponsor_id: SponsorID,
    name: str,
    *,
    target_url: str | None,
    enabled: bool,
    logo_path: str | None = None,
    logo_dark_path: str | None = None,
    remove_logo_dark: bool = False,
) -> Result[Sponsor, str]:
    """Logo paths are only replaced when given."""
    db_sponsor = db.session.get(DbNetsessionSponsor, sponsor_id)
    if db_sponsor is None:
        return Err('Unbekannter Sponsor.')

    db_sponsor.name = name.strip()
    db_sponsor.target_url = _normalize_url(target_url)
    db_sponsor.enabled = enabled
    if logo_path:
        db_sponsor.logo_path = logo_path
    if remove_logo_dark:
        db_sponsor.logo_dark_path = None
    if logo_dark_path:
        db_sponsor.logo_dark_path = logo_dark_path
    db_sponsor.updated_at = datetime.utcnow()
    db.session.commit()
    return Ok(_to_model(db_sponsor))


def delete_sponsor(sponsor_id: SponsorID) -> None:
    db_sponsor = db.session.get(DbNetsessionSponsor, sponsor_id)
    if db_sponsor is None:
        return
    party_id = db_sponsor.party_id
    db.session.delete(db_sponsor)
    db.session.flush()
    _renumber(party_id)
    db.session.commit()


def move_sponsor(sponsor_id: SponsorID, offset: int) -> Result[None, str]:
    """Swap with the neighbour above (-1) or below (+1)."""
    db_sponsor = db.session.get(DbNetsessionSponsor, sponsor_id)
    if db_sponsor is None:
        return Err('Unbekannter Sponsor.')
    db_sponsors = _get_db_sponsors(db_sponsor.party_id)
    index = db_sponsors.index(db_sponsor)
    other_index = index + offset
    if not 0 <= other_index < len(db_sponsors):
        return Err('Der Sponsor steht schon am Rand.')
    db_sponsors[index], db_sponsors[other_index] = (
        db_sponsors[other_index],
        db_sponsors[index],
    )
    for position, item in enumerate(db_sponsors, start=1):
        item.position = position
    db.session.commit()
    return Ok(None)


def find_sponsor(sponsor_id: SponsorID) -> Sponsor | None:
    db_sponsor = db.session.get(DbNetsessionSponsor, sponsor_id)
    return _to_model(db_sponsor) if db_sponsor is not None else None


def get_sponsors_for_party(
    party_id: PartyID, *, enabled_only: bool = False
) -> list[Sponsor]:
    return [
        _to_model(db_sponsor)
        for db_sponsor in _get_db_sponsors(party_id)
        if db_sponsor.enabled or not enabled_only
    ]


def _get_db_sponsors(party_id: PartyID) -> list[DbNetsessionSponsor]:
    return list(
        db.session.scalars(
            select(DbNetsessionSponsor)
            .filter_by(party_id=party_id)
            .order_by(DbNetsessionSponsor.position, DbNetsessionSponsor.name)
        ).all()
    )


def _renumber(party_id: PartyID) -> None:
    for position, db_sponsor in enumerate(_get_db_sponsors(party_id), start=1):
        db_sponsor.position = position


def _normalize_url(url: str | None) -> str | None:
    url = (url or '').strip()
    return url or None


def _to_model(db_sponsor: DbNetsessionSponsor) -> Sponsor:
    return Sponsor(
        id=db_sponsor.id,
        party_id=db_sponsor.party_id,
        name=db_sponsor.name,
        logo_path=db_sponsor.logo_path,
        logo_dark_path=db_sponsor.logo_dark_path,
        target_url=db_sponsor.target_url,
        position=db_sponsor.position,
        enabled=db_sponsor.enabled,
        created_at=db_sponsor.created_at,
        updated_at=db_sponsor.updated_at,
    )
