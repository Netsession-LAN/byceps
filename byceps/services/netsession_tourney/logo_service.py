"""
byceps.services.netsession_tourney.logo_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select

from byceps.byceps_app import get_current_byceps_app
from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util import upload
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyLogoAsset,
)
from .logo_common import (
    _determine_logo_label,
    _label_from_filename,
    _normalize_label,
    ALLOWED_IMAGE_TYPES as ALLOWED_IMAGE_TYPES,
    ALLOWED_SUFFIXES,
    MAXIMUM_DIMENSIONS,
)
from .logo_discord_forum_images import (
    delete_discord_forum_image_asset as delete_discord_forum_image_asset,
    find_discord_forum_image_asset as find_discord_forum_image_asset,
    get_discord_forum_image_assets as get_discord_forum_image_assets,
    get_discord_forum_image_choices as get_discord_forum_image_choices,
    is_known_discord_forum_image_url as is_known_discord_forum_image_url,
    set_discord_forum_image_label as set_discord_forum_image_label,
    upload_discord_forum_image as upload_discord_forum_image,
)
from .logo_image_preparation import prepare_logo_image
from .logo_sponsor_assets import (
    delete_sponsor_logo_asset as delete_sponsor_logo_asset,
    find_sponsor_logo_asset as find_sponsor_logo_asset,
    get_sponsor_logo_assets as get_sponsor_logo_assets,
    get_sponsor_logo_choices as get_sponsor_logo_choices,
    is_known_sponsor_logo_url as is_known_sponsor_logo_url,
    set_sponsor_logo_label as set_sponsor_logo_label,
    upload_sponsor_logo_image as upload_sponsor_logo_image,
)
from .logo_tournament_assets import (
    delete_tournament_logo_asset as delete_tournament_logo_asset,
    find_tournament_logo_asset as find_tournament_logo_asset,
    get_tournament_logo_assets as get_tournament_logo_assets,
    get_tournament_logo_choices as get_tournament_logo_choices,
    is_known_tournament_logo_url as is_known_tournament_logo_url,
    set_tournament_logo_label as set_tournament_logo_label,
    upload_tournament_logo_image as upload_tournament_logo_image,
)
from .models import (
    LogoAssetID,
)


def upload_logo_image(
    party_id: PartyID,
    uploaded_by: User,
    stream: BinaryIO,
    *,
    label: str | None = None,
    original_filename: str | None = None,
) -> Result[str, str]:
    match prepare_logo_image(
        stream, ALLOWED_IMAGE_TYPES, MAXIMUM_DIMENSIONS, force_square=True
    ):
        case Ok((image_type, stream)):
            pass
        case Err(error):
            return Err(error)

    logo_asset_id = LogoAssetID(generate_uuid7())
    filename = f'{logo_asset_id}.{image_type.name}'
    path = _get_logo_directory_path(party_id) / filename

    try:
        upload.store(stream, path, create_parent_path_if_nonexistent=True)
    except FileExistsError:
        return Err('Diese Logo-Datei gibt es bereits.')

    db_logo_asset = DbNetsessionTourneyLogoAsset(
        logo_asset_id,
        party_id,
        filename,
        _determine_logo_label(label, original_filename, filename),
        uploaded_by.id,
        datetime.utcnow(),
    )
    db.session.add(db_logo_asset)
    db.session.commit()

    return Ok(_to_logo_url_path(party_id, filename))


def get_existing_logo_choices(party_id: PartyID) -> list[tuple[str, str]]:
    choices_by_url: dict[str, str] = {}

    db_assets = db.session.scalars(
        select(DbNetsessionTourneyLogoAsset).filter_by(party_id=party_id)
    ).all()
    for db_asset in db_assets:
        url_path = _to_logo_url_path(party_id, db_asset.filename)
        choices_by_url[url_path] = db_asset.label

    for path in _iter_logo_files(party_id):
        url_path = _to_logo_url_path(party_id, path.name)
        choices_by_url.setdefault(url_path, _label_from_filename(path.stem))

    return sorted(choices_by_url.items(), key=lambda item: item[1].lower())


def get_existing_logo_url_paths(party_id: PartyID) -> list[str]:
    return [url_path for url_path, _ in get_existing_logo_choices(party_id)]


def set_logo_label_for_url(
    party_id: PartyID,
    actor: User,
    logo_url_path: str,
    label: str,
) -> Result[None, str]:
    normalized_label = _normalize_label(label)
    if normalized_label is None:
        return Err('Der Logo-Name darf nicht leer sein.')

    filename = _get_filename_from_logo_url_path(party_id, logo_url_path)
    if filename is None:
        return Err('Ungültige Logo-Adresse.')

    db_logo_asset = db.session.scalars(
        select(DbNetsessionTourneyLogoAsset).filter_by(
            party_id=party_id, filename=filename
        )
    ).one_or_none()

    if db_logo_asset is None:
        file_path = _get_logo_directory_path(party_id) / filename
        if not file_path.exists() or not file_path.is_file():
            return Err('Unbekannte Logo-Datei.')

        db_logo_asset = DbNetsessionTourneyLogoAsset(
            LogoAssetID(generate_uuid7()),
            party_id,
            filename,
            normalized_label,
            actor.id,
            datetime.utcnow(),
        )
        db.session.add(db_logo_asset)
    else:
        db_logo_asset.label = normalized_label

    db.session.commit()
    return Ok(None)


def _iter_logo_files(party_id: PartyID) -> list[Path]:
    directory = _get_logo_directory_path(party_id)
    if not directory.exists() or not directory.is_dir():
        return []

    paths: list[Path] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        paths.append(path)

    return paths


def _get_filename_from_logo_url_path(
    party_id: PartyID, logo_url_path: str
) -> str | None:
    expected_prefix = f'/data/parties/{party_id}/netsession_tourney/logos/'
    if not logo_url_path.startswith(expected_prefix):
        return None

    filename = logo_url_path.removeprefix(expected_prefix).strip()
    if not filename or '/' in filename or '\\' in filename:
        return None

    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        return None

    return filename


def _get_logo_directory_path(party_id: PartyID) -> Path:
    return (
        get_current_byceps_app().byceps_config.data_path
        / 'parties'
        / party_id
        / 'netsession_tourney'
        / 'logos'
    )


def _to_logo_url_path(party_id: PartyID, filename: str) -> str:
    return f'/data/parties/{party_id}/netsession_tourney/logos/{filename}'
