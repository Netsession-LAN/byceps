"""
byceps.services.netsession_tourney.tournament_prize_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prizes per tournament and placement.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyTournament,
    DbNetsessionTourneyTournamentPrize,
)
from .models import (
    RuleTemplateBodyFormat,
    TournamentID,
    TournamentPrize,
    TournamentPrizeID,
)
from .service_helpers import (  # noqa: F401
    _append_audit_log,
    _db_browser_push_config_to_model,
    _db_coin_ledger_entry_to_model,
    _db_coin_settings_to_model,
    _db_discord_dm_config_to_model,
    _db_match_chat_message_to_model,
    _db_match_result_to_model,
    _db_match_slot_to_model,
    _db_match_to_model,
    _db_participant_to_model,
    _db_registration_to_model,
    _db_stage_to_model,
    _db_team_member_to_model,
    _db_ticket_category_coin_settings_to_model,
    _db_tournament_category_to_model,
    _db_tournament_prize_to_model,
    _db_tournament_rule_template_to_model,
    _db_tournament_to_model,
    _find_sponsor_logo_target_url,
    _parse_source_outcome,
)
from .tournament_category_service import (  # noqa: F401
    _ensure_default_tournament_category_for_party,
    _find_db_tournament_category,
    _resolve_tournament_category_id_for_party,
    create_tournament_category,
    DEFAULT_TOURNAMENT_CATEGORY_TITLE,
    find_tournament_category,
    get_tournament_categories_for_party,
    move_tournament_category_down,
    move_tournament_category_up,
    update_tournament_category,
)
from .tournament_rule_template_service import (  # noqa: F401
    _find_db_tournament_rule_template,
    create_tournament_rule_template,
    find_tournament_rule_template,
    find_tournament_rule_template_by_slug_for_party,
    get_tournament_rule_templates_for_party,
    update_tournament_rule_template,
)


def create_tournament_prize(
    tournament_id: TournamentID,
    position: int,
    body_format: RuleTemplateBodyFormat,
    body: str,
) -> Result[TournamentPrize, str]:
    db_tournament = db.session.get(DbNetsessionTourneyTournament, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    normalized_body = body.strip()
    if position < 1:
        return Err('Die Platzierung des Preises muss mindestens 1 sein.')
    if not normalized_body:
        return Err('Bitte eine Beschreibung für den Preis angeben.')

    existing_db_prize = db.session.scalar(
        select(DbNetsessionTourneyTournamentPrize).filter_by(
            tournament_id=tournament_id,
            position=position,
        )
    )
    if existing_db_prize is not None:
        return Err('Für diese Platzierung gibt es bereits einen Preis.')

    now = datetime.utcnow()
    db_prize = DbNetsessionTourneyTournamentPrize(
        TournamentPrizeID(generate_uuid7()),
        tournament_id,
        position,
        body_format,
        normalized_body,
        now,
    )
    db.session.add(db_prize)
    db.session.commit()

    return Ok(_db_tournament_prize_to_model(db_prize))


def update_tournament_prize(
    prize_id: TournamentPrizeID,
    position: int,
    body_format: RuleTemplateBodyFormat,
    body: str,
) -> Result[TournamentPrize, str]:
    db_prize = _find_db_tournament_prize(prize_id)
    if db_prize is None:
        return Err('Unbekannter Preis.')

    normalized_body = body.strip()
    if position < 1:
        return Err('Die Platzierung des Preises muss mindestens 1 sein.')
    if not normalized_body:
        return Err('Bitte eine Beschreibung für den Preis angeben.')

    existing_db_prize = db.session.scalar(
        select(DbNetsessionTourneyTournamentPrize).filter_by(
            tournament_id=db_prize.tournament_id,
            position=position,
        )
    )
    if existing_db_prize is not None and existing_db_prize.id != db_prize.id:
        return Err('Für diese Platzierung gibt es bereits einen Preis.')

    db_prize.position = position
    db_prize.body_format = body_format.value
    db_prize.body = normalized_body
    db_prize.updated_at = datetime.utcnow()

    db.session.commit()
    return Ok(_db_tournament_prize_to_model(db_prize))


def delete_tournament_prize(prize_id: TournamentPrizeID) -> Result[None, str]:
    db_prize = _find_db_tournament_prize(prize_id)
    if db_prize is None:
        return Err('Unbekannter Preis.')

    db.session.delete(db_prize)
    db.session.commit()

    return Ok(None)


def find_tournament_prize(
    prize_id: TournamentPrizeID,
) -> TournamentPrize | None:
    db_prize = _find_db_tournament_prize(prize_id)
    if db_prize is None:
        return None

    return _db_tournament_prize_to_model(db_prize)


def get_tournament_prizes_for_tournament(
    tournament_id: TournamentID,
) -> list[TournamentPrize]:
    db_prizes = db.session.scalars(
        select(DbNetsessionTourneyTournamentPrize)
        .filter_by(tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyTournamentPrize.position.asc(),
            DbNetsessionTourneyTournamentPrize.created_at.asc(),
        )
    ).all()

    return [_db_tournament_prize_to_model(item) for item in db_prizes]


def _find_db_tournament_prize(
    prize_id: TournamentPrizeID,
) -> DbNetsessionTourneyTournamentPrize | None:
    return db.session.get(DbNetsessionTourneyTournamentPrize, prize_id)
