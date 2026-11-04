"""
byceps.services.netsession_tourney.rule_template_links
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournaments refer to their rule template by slug, so renaming a template's
slug has to move those references along (or the tournaments silently lose
their rules).
"""

from sqlalchemy import update

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyTournament,
    DbNetsessionTourneyTournamentRuleTemplate,
)


def change_rule_template_slug(
    db_rule_template: DbNetsessionTourneyTournamentRuleTemplate, new_slug: str
) -> None:
    old_slug = db_rule_template.slug
    if new_slug == old_slug:
        return

    db.session.execute(
        update(DbNetsessionTourneyTournament)
        .where(
            DbNetsessionTourneyTournament.party_id == db_rule_template.party_id
        )
        .where(DbNetsessionTourneyTournament.rules_page_slug == old_slug)
        .values(rules_page_slug=new_slug)
    )
    db_rule_template.slug = new_slug
