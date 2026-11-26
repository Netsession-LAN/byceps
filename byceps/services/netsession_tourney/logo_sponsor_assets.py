"""
byceps.services.netsession_tourney.logo_sponsor_assets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sponsor logo assets.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import BinaryIO

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneySponsorLogoAsset,
    DbNetsessionTourneyTournament,
)
from .logo_asset_files import (
    _get_asset_choices,
    _unlink_file_if_exists,
    _upload_asset_image,
)
from .logo_common import (
    _get_sponsor_logo_directory_path,
    _normalize_label,
    _to_sponsor_logo_url_path,
    MAXIMUM_BANNER_DIMENSIONS,
)
from .models import (
    SponsorLogoAsset,
    SponsorLogoAssetID,
)
from .sponsor_link import normalize_target_url


def upload_sponsor_logo_image(
    party_id: PartyID,
    uploaded_by: User,
    stream: BinaryIO,
    *,
    label: str | None = None,
    target_url: str | None = None,
    original_filename: str | None = None,
) -> Result[str, str]:
    return _upload_asset_image(
        party_id,
        uploaded_by,
        stream,
        db_class=DbNetsessionTourneySponsorLogoAsset,
        asset_id_factory=lambda: SponsorLogoAssetID(generate_uuid7()),
        to_url_path=_to_sponsor_logo_url_path,
        get_directory_path=_get_sponsor_logo_directory_path,
        max_dimensions=MAXIMUM_BANNER_DIMENSIONS,
        force_square=False,
        label=label,
        target_url=target_url,
        original_filename=original_filename,
    )


def get_sponsor_logo_choices(party_id: PartyID) -> list[tuple[str, str]]:
    return _get_asset_choices(
        db_class=DbNetsessionTourneySponsorLogoAsset,
        to_url_path=_to_sponsor_logo_url_path,
        asset_directory_name='sponsor_logos',
    )


def get_sponsor_logo_assets(
    party_id: PartyID,
) -> list[SponsorLogoAsset]:
    db_assets = db.session.scalars(
        select(DbNetsessionTourneySponsorLogoAsset).order_by(
            DbNetsessionTourneySponsorLogoAsset.label.asc()
        )
    ).all()

    return [
        SponsorLogoAsset(
            id=db_asset.id,
            party_id=db_asset.party_id,
            filename=db_asset.filename,
            label=db_asset.label,
            url_path=_to_sponsor_logo_url_path(
                db_asset.party_id, db_asset.filename
            ),
            target_url=db_asset.target_url,
            uploaded_by_user_id=db_asset.uploaded_by_user_id,
            created_at=db_asset.created_at,
        )
        for db_asset in db_assets
    ]


def find_sponsor_logo_asset(
    logo_asset_id: SponsorLogoAssetID,
) -> SponsorLogoAsset | None:
    db_asset = db.session.get(
        DbNetsessionTourneySponsorLogoAsset, logo_asset_id
    )
    if db_asset is None:
        return None

    return SponsorLogoAsset(
        id=db_asset.id,
        party_id=db_asset.party_id,
        filename=db_asset.filename,
        label=db_asset.label,
        url_path=_to_sponsor_logo_url_path(
            db_asset.party_id, db_asset.filename
        ),
        target_url=db_asset.target_url,
        uploaded_by_user_id=db_asset.uploaded_by_user_id,
        created_at=db_asset.created_at,
    )


def set_sponsor_logo_label(
    logo_asset_id: SponsorLogoAssetID,
    actor: User,
    label: str,
    target_url: str | None = None,
) -> Result[SponsorLogoAsset, str]:
    db_asset = db.session.get(
        DbNetsessionTourneySponsorLogoAsset, logo_asset_id
    )
    if db_asset is None:
        return Err('Unbekanntes Sponsor-Logo.')

    normalized_label = _normalize_label(label)
    if normalized_label is None:
        return Err('Der Logo-Name darf nicht leer sein.')

    db_asset.label = normalized_label
    db_asset.target_url = normalize_target_url(target_url)
    db_asset.uploaded_by_user_id = actor.id
    db.session.commit()

    return Ok(
        SponsorLogoAsset(
            id=db_asset.id,
            party_id=db_asset.party_id,
            filename=db_asset.filename,
            label=db_asset.label,
            url_path=_to_sponsor_logo_url_path(
                db_asset.party_id, db_asset.filename
            ),
            target_url=db_asset.target_url,
            uploaded_by_user_id=db_asset.uploaded_by_user_id,
            created_at=db_asset.created_at,
        )
    )


def delete_sponsor_logo_asset(
    logo_asset_id: SponsorLogoAssetID,
) -> Result[None, str]:
    db_asset = db.session.get(
        DbNetsessionTourneySponsorLogoAsset, logo_asset_id
    )
    if db_asset is None:
        return Err('Unbekanntes Sponsor-Logo.')

    logo_url = _to_sponsor_logo_url_path(db_asset.party_id, db_asset.filename)
    usage_count = len(
        db.session.scalars(
            select(DbNetsessionTourneyTournament.id).filter_by(
                sponsor_logo_url=logo_url
            )
        ).all()
    )
    if usage_count > 0:
        return Err(
            f'Das Logo wird von {usage_count} gesponserten Turnier(en) verwendet und kann nicht gelöscht werden.'
        )

    file_path = (
        _get_sponsor_logo_directory_path(db_asset.party_id) / db_asset.filename
    )
    db.session.delete(db_asset)
    db.session.commit()
    _unlink_file_if_exists(file_path)
    return Ok(None)


def is_known_sponsor_logo_url(party_id: PartyID, logo_url_path: str) -> bool:
    return logo_url_path in {
        url_path for url_path, _ in get_sponsor_logo_choices(party_id)
    }
