"""
byceps.services.netsession_tourney.tournament_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournaments: create, update, look up.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyTournament,
    DbNetsessionTourneyTournamentCategory,
)
from .discord_forum_threads import (
    sync_discord_thread_for_tournament,
)
from .models import (
    CoinChargeMode,
    CoinRefundPolicy,
    RegistrationMode,
    Tournament,
    TournamentCategoryID,
    TournamentID,
    TournamentMode,
    TournamentStatus,
)
from .service_helpers import (
    append_audit_log,
    db_tournament_to_model,
)
from .tournament_category_service import (
    resolve_tournament_category_id_for_party,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)
from .tournament_settings import (
    apply_mode_changes,
)
from .tourney_tournament_fields import (
    apply_field_values,
    build_created_audit_payload,
    build_db_tournament,
    build_updated_audit_payload,
    TournamentFieldValues,
)


def create_tournament(
    party_id: PartyID,
    slug: str,
    title: str,
    mode: TournamentMode,
    registration_mode: RegistrationMode,
    initiator: User,
    *,
    subtitle: str | None = None,
    logo_url: str | None = None,
    is_sponsored: bool = False,
    sponsor_logo_url: str | None = None,
    game: str | None = None,
    starts_at: datetime | None = None,
    visible_on_site: bool = True,
    registration_open: bool = True,
    rules_page_slug: str | None = None,
    registration_deadline: datetime | None = None,
    roster_lock_at: datetime | None = None,
    checkin_open_at: datetime | None = None,
    checkin_close_at: datetime | None = None,
    team_size: int | None = None,
    substitute_count: int | None = None,
    participant_limit: int | None = None,
    coin_cost: int = 0,
    coin_refund_policy: CoinRefundPolicy = CoinRefundPolicy.until_tournament_end,
    coin_charge_mode: CoinChargeMode = CoinChargeMode.captain_only,
    category_id: TournamentCategoryID | None = None,
) -> Result[Tournament, str]:
    values = TournamentFieldValues(
        mode=mode,
        registration_mode=registration_mode,
        title=title,
        subtitle=subtitle,
        logo_url=logo_url,
        is_sponsored=is_sponsored,
        sponsor_logo_url=sponsor_logo_url,
        game=game,
        starts_at=starts_at,
        visible_on_site=visible_on_site,
        registration_open=registration_open,
        rules_page_slug=rules_page_slug,
        registration_deadline=registration_deadline,
        roster_lock_at=roster_lock_at,
        checkin_open_at=checkin_open_at,
        checkin_close_at=checkin_close_at,
        team_size=team_size,
        substitute_count=substitute_count,
        participant_limit=participant_limit,
        coin_cost=coin_cost,
        coin_refund_policy=coin_refund_policy,
        coin_charge_mode=coin_charge_mode,
    ).normalized()
    return _create_tournament(party_id, slug, values, initiator, category_id)


def _create_tournament(
    party_id: PartyID,
    slug: str,
    values: TournamentFieldValues,
    initiator: User,
    category_id: TournamentCategoryID | None,
) -> Result[Tournament, str]:
    settings_error = values.settings_error()
    if settings_error is not None:
        return Err(settings_error)

    if find_tournament_by_slug_for_party(party_id, slug) is not None:
        return Err('Dieser Slug wird bereits verwendet.')

    resolved_category_id_result = resolve_tournament_category_id_for_party(
        party_id, category_id
    )
    if resolved_category_id_result.is_err():
        return Err(resolved_category_id_result.unwrap_err())
    resolved_category_id = resolved_category_id_result.unwrap()

    now = datetime.utcnow()
    db_tournament = build_db_tournament(
        party_id, resolved_category_id, slug, values, now
    )
    db.session.add(db_tournament)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=db_tournament.id,
        action='tournament_created',
        payload=build_created_audit_payload(slug, values),
        created_at=now,
    )

    db.session.commit()
    return Ok(db_tournament_to_model(db_tournament))


def update_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
    initiator: User,
    *,
    mode: TournamentMode,
    registration_mode: RegistrationMode,
    title: str,
    subtitle: str | None,
    logo_url: str | None,
    is_sponsored: bool,
    sponsor_logo_url: str | None,
    game: str | None,
    starts_at: datetime | None,
    visible_on_site: bool,
    rules_page_slug: str | None,
    registration_open: bool,
    registration_deadline: datetime | None,
    roster_lock_at: datetime | None,
    checkin_open_at: datetime | None,
    checkin_close_at: datetime | None,
    team_size: int | None = None,
    substitute_count: int | None = None,
    participant_limit: int | None = None,
    coin_cost: int = 0,
    coin_refund_policy: CoinRefundPolicy = CoinRefundPolicy.until_tournament_end,
    coin_charge_mode: CoinChargeMode = CoinChargeMode.captain_only,
    category_id: TournamentCategoryID | None = None,
) -> Result[Tournament, str]:
    values = TournamentFieldValues(
        mode=mode,
        registration_mode=registration_mode,
        title=title,
        subtitle=subtitle,
        logo_url=logo_url,
        is_sponsored=is_sponsored,
        sponsor_logo_url=sponsor_logo_url,
        game=game,
        starts_at=starts_at,
        visible_on_site=visible_on_site,
        registration_open=registration_open,
        rules_page_slug=rules_page_slug,
        registration_deadline=registration_deadline,
        roster_lock_at=roster_lock_at,
        checkin_open_at=checkin_open_at,
        checkin_close_at=checkin_close_at,
        team_size=team_size,
        substitute_count=substitute_count,
        participant_limit=participant_limit,
        coin_cost=coin_cost,
        coin_refund_policy=coin_refund_policy,
        coin_charge_mode=coin_charge_mode,
    ).normalized()
    return _update_tournament(
        party_id, tournament_id, values, initiator, category_id
    )


def _update_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
    values: TournamentFieldValues,
    initiator: User,
    category_id: TournamentCategoryID | None,
) -> Result[Tournament, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    settings_error = values.settings_error()
    if settings_error is not None:
        return Err(settings_error)

    if category_id is None:
        resolved_category_id = db_tournament.category_id
    else:
        resolved_category_id_result = resolve_tournament_category_id_for_party(
            party_id, category_id
        )
        if resolved_category_id_result.is_err():
            return Err(resolved_category_id_result.unwrap_err())
        resolved_category_id = resolved_category_id_result.unwrap()

    mode_changes_result = apply_mode_changes(
        db_tournament, values.mode, values.registration_mode
    )
    if mode_changes_result.is_err():
        return Err(mode_changes_result.unwrap_err())
    mode_changes = mode_changes_result.unwrap()

    apply_field_values(db_tournament, values, resolved_category_id)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_updated',
        payload=build_updated_audit_payload(
            values, mode_changes, resolved_category_id
        ),
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    if db_tournament.discord_enabled:
        sync_discord_thread_for_tournament(db_tournament)
    return Ok(db_tournament_to_model(db_tournament))


def get_tournaments_for_party(
    party_id: PartyID,
    *,
    status: TournamentStatus | None = None,
    mode: TournamentMode | None = None,
    game: str | None = None,
    visible_on_site: bool | None = None,
) -> list[Tournament]:
    stmt = select(DbNetsessionTourneyTournament).filter_by(party_id=party_id)
    if status is not None:
        stmt = stmt.filter_by(status=status.value)
    if mode is not None:
        stmt = stmt.filter_by(mode=mode.value)
    if game:
        stmt = stmt.filter_by(game=game)
    if visible_on_site is not None:
        stmt = stmt.filter_by(visible_on_site=visible_on_site)

    db_tournaments = db.session.scalars(stmt).all()
    category_positions_by_id = {
        db_category.id: db_category.position
        for db_category in db.session.scalars(
            select(DbNetsessionTourneyTournamentCategory).filter_by(
                party_id=party_id
            )
        ).all()
    }

    return sorted(
        (db_tournament_to_model(item) for item in db_tournaments),
        key=lambda item: (
            category_positions_by_id.get(item.category_id, 2**31),
            item.starts_at or datetime.max,
            item.title.lower(),
        ),
    )


def find_tournament_by_slug_for_party(
    party_id: PartyID, slug: str, *, visible_on_site: bool | None = None
) -> Tournament | None:
    stmt = select(DbNetsessionTourneyTournament).filter_by(
        party_id=party_id, slug=slug
    )
    if visible_on_site is not None:
        stmt = stmt.filter_by(visible_on_site=visible_on_site)

    db_tournament = db.session.scalar(stmt)
    if db_tournament is None:
        return None
    return db_tournament_to_model(db_tournament)


def find_tournament_for_party(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    visible_on_site: bool | None = None,
) -> Tournament | None:
    stmt = select(DbNetsessionTourneyTournament).filter_by(
        party_id=party_id, id=tournament_id
    )
    if visible_on_site is not None:
        stmt = stmt.filter_by(visible_on_site=visible_on_site)

    db_tournament = db.session.scalar(stmt)
    if db_tournament is None:
        return None
    return db_tournament_to_model(db_tournament)
