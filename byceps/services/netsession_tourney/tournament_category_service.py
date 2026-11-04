"""
byceps.services.netsession_tourney.tournament_category_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournament categories (grouping of tournaments on the site).
"""

from __future__ import annotations

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.dbmodels import DbParty
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyTournamentCategory,
)
from .models import (
    TournamentCategory,
    TournamentCategoryID,
)
from .service_helpers import (
    _db_tournament_category_to_model,
)


DEFAULT_TOURNAMENT_CATEGORY_TITLE = 'Allgemein'


def create_tournament_category(
    party_id: PartyID, title: str
) -> Result[TournamentCategory, str]:
    normalized_title = title.strip()
    if not normalized_title:
        return Err('Bitte einen Titel für die Kategorie angeben.')

    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unbekannte Party.')

    existing_db_category = db.session.scalar(
        select(DbNetsessionTourneyTournamentCategory).filter_by(
            party_id=party_id, title=normalized_title
        )
    )
    if existing_db_category is not None:
        return Err('Diesen Kategorietitel gibt es bereits.')

    db_category = DbNetsessionTourneyTournamentCategory(
        TournamentCategoryID(generate_uuid7()),
        party_id,
        normalized_title,
    )
    db_party.netsession_tourney_tournament_categories.append(db_category)

    db.session.commit()
    return Ok(_db_tournament_category_to_model(db_category))


def update_tournament_category(
    category_id: TournamentCategoryID, title: str
) -> Result[TournamentCategory, str]:
    db_category = _find_db_tournament_category(category_id)
    if db_category is None:
        return Err('Unbekannte Kategorie.')

    normalized_title = title.strip()
    if not normalized_title:
        return Err('Bitte einen Titel für die Kategorie angeben.')

    existing_db_category = db.session.scalar(
        select(DbNetsessionTourneyTournamentCategory).filter_by(
            party_id=db_category.party_id,
            title=normalized_title,
        )
    )
    if existing_db_category is not None and existing_db_category.id != db_category.id:
        return Err('Diesen Kategorietitel gibt es bereits.')

    db_category.title = normalized_title
    db.session.commit()

    return Ok(_db_tournament_category_to_model(db_category))


def move_tournament_category_up(
    category_id: TournamentCategoryID,
) -> Result[None, str]:
    db_category = _find_db_tournament_category(category_id)
    if db_category is None:
        return Err('Unbekannte Kategorie.')

    db_category_list = db_category.party.netsession_tourney_tournament_categories
    if db_category.position == 1:
        return Err('Die Kategorie steht bereits ganz oben.')

    db_popped_category = db_category_list.pop(db_category.position - 1)
    db_category_list.insert(db_popped_category.position - 2, db_popped_category)

    db.session.commit()
    return Ok(None)


def move_tournament_category_down(
    category_id: TournamentCategoryID,
) -> Result[None, str]:
    db_category = _find_db_tournament_category(category_id)
    if db_category is None:
        return Err('Unbekannte Kategorie.')

    db_category_list = db_category.party.netsession_tourney_tournament_categories
    if db_category.position == len(db_category_list):
        return Err('Die Kategorie steht bereits ganz unten.')

    db_popped_category = db_category_list.pop(db_category.position - 1)
    db_category_list.insert(db_popped_category.position, db_popped_category)

    db.session.commit()
    return Ok(None)


def find_tournament_category(
    category_id: TournamentCategoryID,
) -> TournamentCategory | None:
    db_category = _find_db_tournament_category(category_id)
    if db_category is None:
        return None

    return _db_tournament_category_to_model(db_category)


def get_tournament_categories_for_party(
    party_id: PartyID,
) -> list[TournamentCategory]:
    db_categories = db.session.scalars(
        select(DbNetsessionTourneyTournamentCategory)
        .filter_by(party_id=party_id)
        .order_by(DbNetsessionTourneyTournamentCategory.position.asc())
    ).all()

    return [_db_tournament_category_to_model(item) for item in db_categories]


def _resolve_tournament_category_id_for_party(
    party_id: PartyID,
    category_id: TournamentCategoryID | None,
) -> Result[TournamentCategoryID, str]:
    if category_id is not None:
        db_category = db.session.scalar(
            select(DbNetsessionTourneyTournamentCategory).filter_by(
                id=category_id,
                party_id=party_id,
            )
        )
        if db_category is None:
            return Err('Unbekannte Kategorie.')

        return Ok(db_category.id)

    db_category = _ensure_default_tournament_category_for_party(party_id)
    if db_category is None:
        return Err('Unbekannte Party.')

    return Ok(db_category.id)


def _ensure_default_tournament_category_for_party(
    party_id: PartyID,
) -> DbNetsessionTourneyTournamentCategory | None:
    db_category = db.session.scalar(
        select(DbNetsessionTourneyTournamentCategory)
        .filter_by(party_id=party_id)
        .order_by(DbNetsessionTourneyTournamentCategory.position.asc())
    )
    if db_category is not None:
        return db_category

    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return None

    db_category = DbNetsessionTourneyTournamentCategory(
        TournamentCategoryID(generate_uuid7()),
        party_id,
        DEFAULT_TOURNAMENT_CATEGORY_TITLE,
    )
    db_party.netsession_tourney_tournament_categories.append(db_category)

    return db_category


def _find_db_tournament_category(
    category_id: TournamentCategoryID,
) -> DbNetsessionTourneyTournamentCategory | None:
    return db.session.get(DbNetsessionTourneyTournamentCategory, category_id)
