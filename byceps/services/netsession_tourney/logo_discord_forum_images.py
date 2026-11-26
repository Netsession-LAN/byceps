"""
byceps.services.netsession_tourney.logo_discord_forum_images
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord forum image assets.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import BinaryIO

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.image.dimensions import Dimensions
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyDiscordForumImageAsset,
    DbNetsessionTourneyTournament,
)
from .logo_asset_files import (
    _get_asset_choices,
    _unlink_file_if_exists,
    _upload_asset_image,
)
from .logo_common import (
    _get_discord_forum_image_directory_path,
    _normalize_label,
    _to_discord_forum_image_url_path,
)
from .models import (
    DiscordForumImageAsset,
    DiscordForumImageAssetID,
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


def get_discord_forum_image_choices(
    party_id: PartyID,
) -> list[tuple[str, str]]:
    return _get_asset_choices(
        db_class=DbNetsessionTourneyDiscordForumImageAsset,
        to_url_path=_to_discord_forum_image_url_path,
        asset_directory_name='discord_forum_images',
    )


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


def is_known_discord_forum_image_url(
    party_id: PartyID, image_url_path: str
) -> bool:
    return image_url_path in {
        url_path for url_path, _ in get_discord_forum_image_choices(party_id)
    }
