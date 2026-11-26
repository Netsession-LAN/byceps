"""
byceps.services.netsession_tourney.blueprints.admin.wizard_lookups
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Lookups of party-wide tournament settings (categories, rule
templates, prizes, logos) that abort with 404 if missing.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import abort

from byceps.services.netsession_tourney.logo_service import (
    find_discord_forum_image_asset,
    find_sponsor_logo_asset,
    find_tournament_logo_asset,
)
from byceps.services.netsession_tourney.models import (
    DiscordForumImageAssetID,
    SponsorLogoAssetID,
    TournamentCategoryID,
    TournamentLogoAssetID,
    TournamentPrizeID,
    TournamentRuleTemplateID,
)
from byceps.services.netsession_tourney.tournament_category_service import (
    find_tournament_category,
)
from byceps.services.netsession_tourney.tournament_prize_service import (
    find_tournament_prize,
)
from byceps.services.netsession_tourney.tournament_rule_template_service import (
    find_tournament_rule_template,
)


def get_tournament_category_or_404(category_id):
    category = find_tournament_category(TournamentCategoryID(category_id))
    if category is None:
        abort(404)

    return category


def get_tournament_rule_template_or_404(rule_template_id):
    rule_template = find_tournament_rule_template(
        TournamentRuleTemplateID(rule_template_id)
    )
    if rule_template is None:
        abort(404)

    return rule_template


def get_tournament_prize_or_404(prize_id):
    prize = find_tournament_prize(TournamentPrizeID(prize_id))
    if prize is None:
        abort(404)

    return prize


def get_tournament_logo_asset_or_404(logo_asset_id):
    logo_asset = find_tournament_logo_asset(
        TournamentLogoAssetID(logo_asset_id)
    )
    if logo_asset is None:
        abort(404)

    return logo_asset


def get_sponsor_logo_asset_or_404(logo_asset_id):
    logo_asset = find_sponsor_logo_asset(SponsorLogoAssetID(logo_asset_id))
    if logo_asset is None:
        abort(404)

    return logo_asset


def get_discord_forum_image_asset_or_404(image_asset_id):
    image_asset = find_discord_forum_image_asset(
        DiscordForumImageAssetID(image_asset_id)
    )
    if image_asset is None:
        abort(404)

    return image_asset
