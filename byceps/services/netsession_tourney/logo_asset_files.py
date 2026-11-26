"""
byceps.services.netsession_tourney.logo_asset_files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Storing, listing and deleting the files of logo and image assets.

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
from byceps.util.image.dimensions import Dimensions
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneySponsorLogoAsset,
)
from .logo_common import (
    _determine_logo_label,
    _label_from_filename,
    ALLOWED_IMAGE_TYPES,
    ALLOWED_SUFFIXES,
)
from .logo_image_preparation import prepare_logo_image
from .sponsor_link import normalize_target_url


def _upload_asset_image(
    party_id: PartyID,
    uploaded_by: User,
    stream: BinaryIO,
    *,
    db_class,
    asset_id_factory,
    to_url_path,
    get_directory_path,
    max_dimensions: Dimensions,
    force_square: bool,
    label: str | None,
    target_url: str | None = None,
    original_filename: str | None,
) -> Result[str, str]:
    match prepare_logo_image(
        stream, ALLOWED_IMAGE_TYPES, max_dimensions, force_square=force_square
    ):
        case Ok((image_type, stream)):
            pass
        case Err(error):
            return Err(error)

    logo_asset_id = asset_id_factory()
    filename = f'{logo_asset_id}.{image_type.name}'
    path = get_directory_path(party_id) / filename

    try:
        upload.store(stream, path, create_parent_path_if_nonexistent=True)
    except FileExistsError:
        return Err('Diese Logo-Datei gibt es bereits.')

    asset_label = _determine_logo_label(label, original_filename, filename)
    asset_target_url = normalize_target_url(target_url)
    if db_class is DbNetsessionTourneySponsorLogoAsset:
        db_asset = db_class(
            logo_asset_id,
            party_id,
            filename,
            asset_label,
            asset_target_url,
            uploaded_by.id,
            datetime.utcnow(),
        )
    else:
        db_asset = db_class(
            logo_asset_id,
            party_id,
            filename,
            asset_label,
            uploaded_by.id,
            datetime.utcnow(),
        )
    db.session.add(db_asset)
    db.session.commit()

    return Ok(to_url_path(party_id, filename))


def _get_asset_choices(
    *,
    db_class,
    to_url_path,
    asset_directory_name: str,
) -> list[tuple[str, str]]:
    choices_by_url: dict[str, str] = {}

    db_assets = db.session.scalars(select(db_class)).all()
    for db_asset in db_assets:
        url_path = to_url_path(db_asset.party_id, db_asset.filename)
        choices_by_url[url_path] = db_asset.label

    for asset_party_id, path in _iter_asset_files_in_all_parties(
        asset_directory_name
    ):
        url_path = to_url_path(asset_party_id, path.name)
        choices_by_url.setdefault(url_path, _label_from_filename(path.stem))

    return sorted(choices_by_url.items(), key=lambda item: item[1].lower())


def _iter_asset_files(directory: Path) -> list[Path]:
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


def _iter_asset_files_in_all_parties(
    asset_directory_name: str,
) -> list[tuple[PartyID, Path]]:
    parties_directory = (
        get_current_byceps_app().byceps_config.data_path / 'parties'
    )
    if not parties_directory.exists() or not parties_directory.is_dir():
        return []

    asset_files: list[tuple[PartyID, Path]] = []
    for party_directory in sorted(
        parties_directory.iterdir(), key=lambda item: item.name.lower()
    ):
        if not party_directory.is_dir():
            continue

        asset_directory = (
            party_directory / 'netsession_tourney' / asset_directory_name
        )
        for path in _iter_asset_files(asset_directory):
            asset_files.append((PartyID(party_directory.name), path))

    return asset_files


def _unlink_file_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _get_tournament_asset_filename_from_logo_url_path(
    party_id: PartyID, logo_url_path: str
) -> str | None:
    expected_prefix = (
        f'/data/parties/{party_id}/netsession_tourney/tournament_logos/'
    )
    if not logo_url_path.startswith(expected_prefix):
        return None

    filename = logo_url_path.removeprefix(expected_prefix).strip()
    if not filename or '/' in filename or '\\' in filename:
        return None

    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        return None

    return filename
