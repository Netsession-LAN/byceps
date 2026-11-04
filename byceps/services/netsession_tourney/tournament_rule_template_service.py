"""
byceps.services.netsession_tourney.tournament_rule_template_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Rule templates that tournaments link to by slug.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.dbmodels import DbParty
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyTournamentRuleTemplate,
)
from .models import (
    RuleTemplateBodyFormat,
    TournamentRuleTemplate,
    TournamentRuleTemplateID,
)
from .rule_template_links import change_rule_template_slug
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


def create_tournament_rule_template(
    party_id: PartyID,
    slug: str,
    title: str,
    body_format: RuleTemplateBodyFormat,
    body: str,
) -> Result[TournamentRuleTemplate, str]:
    normalized_slug = slug.strip()
    normalized_title = title.strip()
    normalized_body = body.strip()

    if not normalized_slug:
        return Err('Bitte einen Slug für die Regel-Vorlage angeben.')
    if not normalized_title:
        return Err('Bitte einen Titel für die Regel-Vorlage angeben.')
    if not normalized_body:
        return Err('Bitte einen Text für die Regel-Vorlage angeben.')

    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unbekannte Party.')

    existing_db_rule_template = db.session.scalar(
        select(DbNetsessionTourneyTournamentRuleTemplate).filter_by(
            party_id=party_id,
            slug=normalized_slug,
        )
    )
    if existing_db_rule_template is not None:
        return Err('Diesen Slug verwendet bereits eine andere Regel-Vorlage.')

    now = datetime.utcnow()
    db_rule_template = DbNetsessionTourneyTournamentRuleTemplate(
        TournamentRuleTemplateID(generate_uuid7()),
        party_id,
        normalized_slug,
        normalized_title,
        body_format,
        normalized_body,
        now,
    )
    db.session.add(db_rule_template)
    db.session.commit()

    return Ok(_db_tournament_rule_template_to_model(db_rule_template))


def update_tournament_rule_template(
    rule_template_id: TournamentRuleTemplateID,
    slug: str,
    title: str,
    body_format: RuleTemplateBodyFormat,
    body: str,
) -> Result[TournamentRuleTemplate, str]:
    db_rule_template = _find_db_tournament_rule_template(rule_template_id)
    if db_rule_template is None:
        return Err('Unbekannte Regel-Vorlage.')

    normalized_slug = slug.strip()
    normalized_title = title.strip()
    normalized_body = body.strip()

    if not normalized_slug:
        return Err('Bitte einen Slug für die Regel-Vorlage angeben.')
    if not normalized_title:
        return Err('Bitte einen Titel für die Regel-Vorlage angeben.')
    if not normalized_body:
        return Err('Bitte einen Text für die Regel-Vorlage angeben.')

    existing_db_rule_template = db.session.scalar(
        select(DbNetsessionTourneyTournamentRuleTemplate).filter_by(
            party_id=db_rule_template.party_id,
            slug=normalized_slug,
        )
    )
    if (
        existing_db_rule_template is not None
        and existing_db_rule_template.id != db_rule_template.id
    ):
        return Err('Diesen Slug verwendet bereits eine andere Regel-Vorlage.')

    change_rule_template_slug(db_rule_template, normalized_slug)
    db_rule_template.title = normalized_title
    db_rule_template.body_format = body_format.value
    db_rule_template.body = normalized_body
    db_rule_template.updated_at = datetime.utcnow()

    db.session.commit()
    return Ok(_db_tournament_rule_template_to_model(db_rule_template))


def find_tournament_rule_template(
    rule_template_id: TournamentRuleTemplateID,
) -> TournamentRuleTemplate | None:
    db_rule_template = _find_db_tournament_rule_template(rule_template_id)
    if db_rule_template is None:
        return None

    return _db_tournament_rule_template_to_model(db_rule_template)


def find_tournament_rule_template_by_slug_for_party(
    party_id: PartyID,
    slug: str,
) -> TournamentRuleTemplate | None:
    db_rule_template = db.session.scalar(
        select(DbNetsessionTourneyTournamentRuleTemplate).filter_by(
            party_id=party_id,
            slug=slug,
        )
    )
    if db_rule_template is None:
        return None

    return _db_tournament_rule_template_to_model(db_rule_template)


def get_tournament_rule_templates_for_party(
    party_id: PartyID,
) -> list[TournamentRuleTemplate]:
    db_rule_templates = db.session.scalars(
        select(DbNetsessionTourneyTournamentRuleTemplate)
        .filter_by(party_id=party_id)
        .order_by(
            DbNetsessionTourneyTournamentRuleTemplate.title.asc(),
            DbNetsessionTourneyTournamentRuleTemplate.slug.asc(),
        )
    ).all()

    return [
        _db_tournament_rule_template_to_model(item)
        for item in db_rule_templates
    ]


def _find_db_tournament_rule_template(
    rule_template_id: TournamentRuleTemplateID,
) -> DbNetsessionTourneyTournamentRuleTemplate | None:
    return db.session.get(
        DbNetsessionTourneyTournamentRuleTemplate, rule_template_id
    )
