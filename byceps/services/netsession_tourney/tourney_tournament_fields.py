"""
byceps.services.netsession_tourney.tourney_tournament_fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The editable field values of a tournament, shared by creating and updating
a tournament: validation, applying them to the database object, audit payload.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from byceps.services.party.models import PartyID
from byceps.util.uuid import generate_uuid7

from .dbmodels import DbNetsessionTourneyTournament
from .models import (
    CoinChargeMode,
    CoinRefundPolicy,
    RegistrationMode,
    TournamentCategoryID,
    TournamentID,
    TournamentMode,
    TournamentStatus,
)
from .tournament_settings import (
    clean_text,
    ModeChanges,
    sponsor_logo_url_if_sponsored,
    validate_tournament_settings,
)


@dataclass(frozen=True)
class TournamentFieldValues:
    mode: TournamentMode
    registration_mode: RegistrationMode
    title: str
    subtitle: str | None
    logo_url: str | None
    is_sponsored: bool
    sponsor_logo_url: str | None
    game: str | None
    starts_at: datetime | None
    visible_on_site: bool
    registration_open: bool
    rules_page_slug: str | None
    registration_deadline: datetime | None
    roster_lock_at: datetime | None
    checkin_open_at: datetime | None
    checkin_close_at: datetime | None
    team_size: int | None
    substitute_count: int | None
    participant_limit: int | None
    coin_cost: int
    coin_refund_policy: CoinRefundPolicy
    coin_charge_mode: CoinChargeMode

    def normalized(self) -> TournamentFieldValues:
        """Solo registration forces a team size of 1, no substitutes and
        charging the captain only."""
        if self.registration_mode == RegistrationMode.solo:
            return replace(
                self,
                team_size=1,
                substitute_count=0,
                coin_charge_mode=CoinChargeMode.captain_only,
            )
        return self

    def settings_error(self) -> str | None:
        """Return an error message, or `None` if the settings are fine."""
        return validate_tournament_settings(
            mode=self.mode,
            registration_mode=self.registration_mode,
            team_size=self.team_size,
            substitute_count=self.substitute_count,
            participant_limit=self.participant_limit,
            coin_cost=self.coin_cost,
        )


def build_db_tournament(
    party_id: PartyID,
    category_id: TournamentCategoryID,
    slug: str,
    values: TournamentFieldValues,
    now: datetime,
) -> DbNetsessionTourneyTournament:
    return DbNetsessionTourneyTournament(
        TournamentID(generate_uuid7()),
        party_id,
        category_id,
        slug.strip(),
        values.title.strip(),
        values.mode,
        TournamentStatus.draft,
        values.registration_mode,
        now,
        subtitle=values.subtitle.strip() if values.subtitle else None,
        logo_url=values.logo_url.strip() if values.logo_url else None,
        is_sponsored=values.is_sponsored,
        sponsor_logo_url=(
            values.sponsor_logo_url.strip()
            if values.is_sponsored and values.sponsor_logo_url
            else None
        ),
        game=values.game.strip() if values.game else None,
        starts_at=values.starts_at,
        visible_on_site=values.visible_on_site,
        registration_open=values.registration_open,
        rules_page_slug=(
            values.rules_page_slug.strip() if values.rules_page_slug else None
        ),
        registration_deadline=values.registration_deadline,
        roster_lock_at=values.roster_lock_at,
        checkin_open_at=values.checkin_open_at,
        checkin_close_at=values.checkin_close_at,
        team_size=values.team_size,
        substitute_count=values.substitute_count,
        participant_limit=values.participant_limit,
        coin_cost=values.coin_cost,
        coin_refund_policy=values.coin_refund_policy,
        coin_charge_mode=values.coin_charge_mode,
    )


def build_created_audit_payload(
    slug: str, values: TournamentFieldValues
) -> dict[str, Any]:
    return {
        'slug': slug,
        'title': values.title,
        'mode': values.mode.value,
        'logo_url': clean_text(values.logo_url),
        'is_sponsored': values.is_sponsored,
        'sponsor_logo_url': sponsor_logo_url_if_sponsored(
            values.is_sponsored, values.sponsor_logo_url
        ),
        'visible_on_site': values.visible_on_site,
        'registration_open': values.registration_open,
        'coin_cost': values.coin_cost,
        'coin_refund_policy': values.coin_refund_policy.value,
        'coin_charge_mode': values.coin_charge_mode.value,
    }


def apply_field_values(
    db_tournament: DbNetsessionTourneyTournament,
    values: TournamentFieldValues,
    category_id: TournamentCategoryID,
) -> None:
    """Write the field values (except mode and registration mode) to the
    tournament."""
    db_tournament.title = values.title.strip()
    db_tournament.subtitle = clean_text(values.subtitle)
    db_tournament.logo_url = clean_text(values.logo_url)
    db_tournament.is_sponsored = values.is_sponsored
    db_tournament.sponsor_logo_url = sponsor_logo_url_if_sponsored(
        values.is_sponsored, values.sponsor_logo_url
    )
    db_tournament.game = clean_text(values.game)
    db_tournament.starts_at = values.starts_at
    db_tournament.visible_on_site = values.visible_on_site
    db_tournament.rules_page_slug = clean_text(values.rules_page_slug)
    db_tournament.registration_open = values.registration_open
    db_tournament.registration_deadline = values.registration_deadline
    db_tournament.roster_lock_at = values.roster_lock_at
    db_tournament.checkin_open_at = values.checkin_open_at
    db_tournament.checkin_close_at = values.checkin_close_at
    db_tournament.team_size = values.team_size
    db_tournament.substitute_count = values.substitute_count
    db_tournament.participant_limit = values.participant_limit
    db_tournament.coin_cost = values.coin_cost
    db_tournament.coin_refund_policy = values.coin_refund_policy.value
    db_tournament.coin_charge_mode = values.coin_charge_mode.value
    db_tournament.category_id = category_id
    db_tournament.updated_at = datetime.utcnow()


def build_updated_audit_payload(
    values: TournamentFieldValues,
    mode_changes: ModeChanges,
    category_id: TournamentCategoryID,
) -> dict[str, Any]:
    return {
        'title': values.title,
        'mode': values.mode.value,
        'mode_changed': mode_changes.mode_changed,
        'registration_mode': values.registration_mode.value,
        'registration_mode_changed': mode_changes.registration_mode_changed,
        'deleted_stage_count': mode_changes.deleted_stage_count,
        'category_id': str(category_id),
        'visible_on_site': values.visible_on_site,
        'registration_open': values.registration_open,
        'coin_cost': values.coin_cost,
        'coin_refund_policy': values.coin_refund_policy.value,
        'coin_charge_mode': values.coin_charge_mode.value,
        'logo_url': clean_text(values.logo_url),
        'is_sponsored': values.is_sponsored,
        'sponsor_logo_url': sponsor_logo_url_if_sponsored(
            values.is_sponsored, values.sponsor_logo_url
        ),
    }
