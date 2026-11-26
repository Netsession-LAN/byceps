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
from byceps.util.image.dimensions import Dimensions
from byceps.util.image.image_type import ImageType
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyDiscordForumImageAsset,
    DbNetsessionTourneyLogoAsset,
    DbNetsessionTourneySponsorLogoAsset,
    DbNetsessionTourneyTournament,
    DbNetsessionTourneyTournamentLogoAsset,
)
from .logo_image_preparation import prepare_logo_image
from .models import (
    DiscordForumImageAsset,
    DiscordForumImageAssetID,
    LogoAssetID,
    SponsorLogoAsset,
    SponsorLogoAssetID,
    TournamentLogoAsset,
    TournamentLogoAssetID,
)
from .sponsor_link import normalize_target_url


# Uploads: no SVG (may contain scripts); existing SVG files stay usable.
ALLOWED_IMAGE_TYPES = frozenset(
    [
        ImageType.jpeg,
        ImageType.png,
        ImageType.webp,
    ]
)

MAXIMUM_DIMENSIONS = Dimensions(512, 512)
MAXIMUM_BANNER_DIMENSIONS = Dimensions(1200, 300)
ALLOWED_SUFFIXES = {'.jpeg', '.jpg', '.png', '.svg', '.webp'}


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


def upload_discord_forum_image(
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
        db_class=DbNetsessionTourneyDiscordForumImageAsset,
        asset_id_factory=lambda: DiscordForumImageAssetID(generate_uuid7()),
        to_url_path=_to_discord_forum_image_url_path,
        get_directory_path=_get_discord_forum_image_directory_path,
        max_dimensions=Dimensions(1600, 900),
        force_square=False,
        label=label,
        original_filename=original_filename,
    )


def get_tournament_logo_choices(party_id: PartyID) -> list[tuple[str, str]]:
    return _get_asset_choices(
        db_class=DbNetsessionTourneyTournamentLogoAsset,
        to_url_path=_to_tournament_logo_url_path,
        asset_directory_name='tournament_logos',
    )


def get_sponsor_logo_choices(party_id: PartyID) -> list[tuple[str, str]]:
    return _get_asset_choices(
        db_class=DbNetsessionTourneySponsorLogoAsset,
        to_url_path=_to_sponsor_logo_url_path,
        asset_directory_name='sponsor_logos',
    )


def get_discord_forum_image_choices(
    party_id: PartyID,
) -> list[tuple[str, str]]:
    return _get_asset_choices(
        db_class=DbNetsessionTourneyDiscordForumImageAsset,
        to_url_path=_to_discord_forum_image_url_path,
        asset_directory_name='discord_forum_images',
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


def get_discord_forum_image_assets(
    party_id: PartyID,
) -> list[DiscordForumImageAsset]:
    db_assets = db.session.scalars(
        select(DbNetsessionTourneyDiscordForumImageAsset).order_by(
            DbNetsessionTourneyDiscordForumImageAsset.label.asc()
        )
    ).all()

    return [
        DiscordForumImageAsset(
            id=db_asset.id,
            party_id=db_asset.party_id,
            filename=db_asset.filename,
            label=db_asset.label,
            url_path=_to_discord_forum_image_url_path(
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


def find_discord_forum_image_asset(
    image_asset_id: DiscordForumImageAssetID,
) -> DiscordForumImageAsset | None:
    db_asset = db.session.get(
        DbNetsessionTourneyDiscordForumImageAsset, image_asset_id
    )
    if db_asset is None:
        return None

    return DiscordForumImageAsset(
        id=db_asset.id,
        party_id=db_asset.party_id,
        filename=db_asset.filename,
        label=db_asset.label,
        url_path=_to_discord_forum_image_url_path(
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


def set_discord_forum_image_label(
    image_asset_id: DiscordForumImageAssetID,
    actor: User,
    label: str,
) -> Result[DiscordForumImageAsset, str]:
    db_asset = db.session.get(
        DbNetsessionTourneyDiscordForumImageAsset, image_asset_id
    )
    if db_asset is None:
        return Err('Unbekanntes Discord-Forum-Bild.')

    normalized_label = _normalize_label(label)
    if normalized_label is None:
        return Err('Bildname darf nicht leer sein.')

    db_asset.label = normalized_label
    db_asset.uploaded_by_user_id = actor.id
    db.session.commit()

    return Ok(
        DiscordForumImageAsset(
            id=db_asset.id,
            party_id=db_asset.party_id,
            filename=db_asset.filename,
            label=db_asset.label,
            url_path=_to_discord_forum_image_url_path(
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


def delete_discord_forum_image_asset(
    image_asset_id: DiscordForumImageAssetID,
) -> Result[None, str]:
    db_asset = db.session.get(
        DbNetsessionTourneyDiscordForumImageAsset, image_asset_id
    )
    if db_asset is None:
        return Err('Unbekanntes Discord-Forum-Bild.')

    image_url = _to_discord_forum_image_url_path(
        db_asset.party_id, db_asset.filename
    )
    usage_count = len(
        db.session.scalars(
            select(DbNetsessionTourneyTournament.id).filter_by(
                discord_forum_image_url=image_url,
            )
        ).all()
    )
    if usage_count > 0:
        return Err(
            f'Bild wird von {usage_count} Turnier(en) verwendet und kann nicht gelöscht werden.'
        )

    file_path = (
        _get_discord_forum_image_directory_path(db_asset.party_id)
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


def is_known_sponsor_logo_url(party_id: PartyID, logo_url_path: str) -> bool:
    return logo_url_path in {
        url_path for url_path, _ in get_sponsor_logo_choices(party_id)
    }


def is_known_discord_forum_image_url(
    party_id: PartyID, image_url_path: str
) -> bool:
    return image_url_path in {
        url_path for url_path, _ in get_discord_forum_image_choices(party_id)
    }


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


def _determine_logo_label(
    raw_label: str | None,
    original_filename: str | None,
    fallback_filename: str,
) -> str:
    normalized = _normalize_label(raw_label)
    if normalized is not None:
        return normalized

    if original_filename:
        filename_stem = Path(original_filename).stem
        normalized_filename_stem = _normalize_label(filename_stem)
        if normalized_filename_stem is not None:
            return normalized_filename_stem

    return _label_from_filename(Path(fallback_filename).stem)


def _normalize_label(raw_label: str | None) -> str | None:
    if raw_label is None:
        return None

    normalized = ' '.join(raw_label.strip().split())
    if not normalized:
        return None

    return normalized[:120]


def _label_from_filename(filename_stem: str) -> str:
    compact = filename_stem.strip()
    if not compact:
        return 'Logo'

    if len(compact) >= 20 and all(
        character in '0123456789abcdef-' for character in compact.lower()
    ):
        return f'Logo {compact[:8]}'

    return compact.replace('_', ' ').replace('-', ' ')[:120]


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


def _get_tournament_logo_directory_path(party_id: PartyID) -> Path:
    return (
        get_current_byceps_app().byceps_config.data_path
        / 'parties'
        / party_id
        / 'netsession_tourney'
        / 'tournament_logos'
    )


def _to_tournament_logo_url_path(party_id: PartyID, filename: str) -> str:
    return f'/data/parties/{party_id}/netsession_tourney/tournament_logos/{filename}'


def _get_sponsor_logo_directory_path(party_id: PartyID) -> Path:
    return (
        get_current_byceps_app().byceps_config.data_path
        / 'parties'
        / party_id
        / 'netsession_tourney'
        / 'sponsor_logos'
    )


def _to_sponsor_logo_url_path(party_id: PartyID, filename: str) -> str:
    return (
        f'/data/parties/{party_id}/netsession_tourney/sponsor_logos/{filename}'
    )


def _get_discord_forum_image_directory_path(party_id: PartyID) -> Path:
    return (
        get_current_byceps_app().byceps_config.data_path
        / 'parties'
        / party_id
        / 'netsession_tourney'
        / 'discord_forum_images'
    )


def _to_discord_forum_image_url_path(party_id: PartyID, filename: str) -> str:
    return f'/data/parties/{party_id}/netsession_tourney/discord_forum_images/{filename}'


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
