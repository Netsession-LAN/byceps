"""
byceps.services.netsession_tourney.logo_tournament_assets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournament logo assets.

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
    DbNetsessionTourneyTournament,
    DbNetsessionTourneyTournamentLogoAsset,
)
from .logo_asset_files import (
    _get_asset_choices,
    _unlink_file_if_exists,
    _upload_asset_image,
)
from .logo_common import (
    _get_tournament_logo_directory_path,
    _normalize_label,
    _to_tournament_logo_url_path,
    MAXIMUM_DIMENSIONS,
)
from .models import (
    TournamentLogoAsset,
    TournamentLogoAssetID,
)


def upload_tournament_logo_image(
    party_id: PartyID,
    uploaded_by: User,
    stream: BinaryIO,
    *,
    label: str | None = None,
    original_filename: str | None = None,
) -> Result[str, str]:
    return _upload_asset_image(
        party_id,
        uploaded_by,
        stream,
        db_class=DbNetsessionTourneyTournamentLogoAsset,
        asset_id_factory=lambda: TournamentLogoAssetID(generate_uuid7()),
        to_url_path=_to_tournament_logo_url_path,
        get_directory_path=_get_tournament_logo_directory_path,
        max_dimensions=MAXIMUM_DIMENSIONS,
        force_square=True,
        label=label,
        original_filename=original_filename,
    )


def get_tournament_logo_choices(party_id: PartyID) -> list[tuple[str, str]]:
    return _get_asset_choices(
        db_class=DbNetsessionTourneyTournamentLogoAsset,
        to_url_path=_to_tournament_logo_url_path,
        asset_directory_name='tournament_logos',
    )


def get_tournament_logo_assets(
    party_id: PartyID,
) -> list[TournamentLogoAsset]:
    db_assets = db.session.scalars(
        select(DbNetsessionTourneyTournamentLogoAsset).order_by(
            DbNetsessionTourneyTournamentLogoAsset.label.asc()
        )
    ).all()

    return [
        TournamentLogoAsset(
            id=db_asset.id,
            party_id=db_asset.party_id,
            filename=db_asset.filename,
            label=db_asset.label,
            url_path=_to_tournament_logo_url_path(
                db_asset.party_id, db_asset.filename
            ),
            uploaded_by_user_id=db_asset.uploaded_by_user_id,
            created_at=db_asset.created_at,
        )
        for db_asset in db_assets
    ]


def find_tournament_logo_asset(
    logo_asset_id: TournamentLogoAssetID,
) -> TournamentLogoAsset | None:
    db_asset = db.session.get(
        DbNetsessionTourneyTournamentLogoAsset, logo_asset_id
    )
    if db_asset is None:
        return None

    return TournamentLogoAsset(
        id=db_asset.id,
        party_id=db_asset.party_id,
        filename=db_asset.filename,
        label=db_asset.label,
        url_path=_to_tournament_logo_url_path(
            db_asset.party_id, db_asset.filename
        ),
        uploaded_by_user_id=db_asset.uploaded_by_user_id,
        created_at=db_asset.created_at,
    )


def set_tournament_logo_label(
    logo_asset_id: TournamentLogoAssetID,
    actor: User,
    label: str,
) -> Result[TournamentLogoAsset, str]:
    db_asset = db.session.get(
        DbNetsessionTourneyTournamentLogoAsset, logo_asset_id
    )
    if db_asset is None:
        return Err('Unbekanntes Turnierlogo.')

    normalized_label = _normalize_label(label)
    if normalized_label is None:
        return Err('Der Logo-Name darf nicht leer sein.')

    db_asset.label = normalized_label
    db_asset.uploaded_by_user_id = actor.id
    db.session.commit()

    return Ok(
        TournamentLogoAsset(
            id=db_asset.id,
            party_id=db_asset.party_id,
            filename=db_asset.filename,
            label=db_asset.label,
            url_path=_to_tournament_logo_url_path(
                db_asset.party_id, db_asset.filename
            ),
            uploaded_by_user_id=db_asset.uploaded_by_user_id,
            created_at=db_asset.created_at,
        )
    )


def delete_tournament_logo_asset(
    logo_asset_id: TournamentLogoAssetID,
) -> Result[None, str]:
    db_asset = db.session.get(
        DbNetsessionTourneyTournamentLogoAsset, logo_asset_id
    )
    if db_asset is None:
        return Err('Unbekanntes Turnierlogo.')

    logo_url = _to_tournament_logo_url_path(
        db_asset.party_id, db_asset.filename
    )
    usage_count = len(
        db.session.scalars(
            select(DbNetsessionTourneyTournament.id).filter_by(
                logo_url=logo_url
            )
        ).all()
    )
    if usage_count > 0:
        return Err(
            f'Das Logo wird von {usage_count} Turnier(en) verwendet und kann nicht gelöscht werden.'
        )

    file_path = (
        _get_tournament_logo_directory_path(db_asset.party_id)
        / db_asset.filename
    )
    db.session.delete(db_asset)
    db.session.commit()
    _unlink_file_if_exists(file_path)
    return Ok(None)


def is_known_tournament_logo_url(party_id: PartyID, logo_url_path: str) -> bool:
    return logo_url_path in {
        url_path for url_path, _ in get_tournament_logo_choices(party_id)
    }
