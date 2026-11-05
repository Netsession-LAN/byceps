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
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyTournament,
    DbNetsessionTourneyTournamentCategory,
)
from .discord_forum_threads import (
    _sync_discord_thread_for_tournament,
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
    _append_audit_log,
    _db_tournament_to_model,
)
from .tournament_category_service import (
    _resolve_tournament_category_id_for_party,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
)
from .tournament_settings import (
    apply_mode_changes,
    clean_text,
    sponsor_logo_url_if_sponsored,
    validate_tournament_settings,
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
    if registration_mode == RegistrationMode.solo:
        team_size = 1
        substitute_count = 0
        coin_charge_mode = CoinChargeMode.captain_only

    settings_error = validate_tournament_settings(
        mode=mode,
        registration_mode=registration_mode,
        team_size=team_size,
        substitute_count=substitute_count,
        participant_limit=participant_limit,
        coin_cost=coin_cost,
    )
    if settings_error is not None:
        return Err(settings_error)

    if find_tournament_by_slug_for_party(party_id, slug) is not None:
        return Err('Dieser Slug wird bereits verwendet.')

    resolved_category_id_result = _resolve_tournament_category_id_for_party(
        party_id, category_id
    )
    if resolved_category_id_result.is_err():
        return Err(resolved_category_id_result.unwrap_err())
    resolved_category_id = resolved_category_id_result.unwrap()

    now = datetime.utcnow()
    db_tournament = DbNetsessionTourneyTournament(
        TournamentID(generate_uuid7()),
        party_id,
        resolved_category_id,
        slug.strip(),
        title.strip(),
        mode,
        TournamentStatus.draft,
        registration_mode,
        now,
        subtitle=subtitle.strip() if subtitle else None,
        logo_url=logo_url.strip() if logo_url else None,
        is_sponsored=is_sponsored,
        sponsor_logo_url=(
            sponsor_logo_url.strip()
            if is_sponsored and sponsor_logo_url
            else None
        ),
        game=game.strip() if game else None,
        starts_at=starts_at,
        visible_on_site=visible_on_site,
        registration_open=registration_open,
        rules_page_slug=rules_page_slug.strip() if rules_page_slug else None,
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
    )
    db.session.add(db_tournament)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=db_tournament.id,
        action='tournament_created',
        payload={
            'slug': slug,
            'title': title,
            'mode': mode.value,
            'logo_url': clean_text(logo_url),
            'is_sponsored': is_sponsored,
            'sponsor_logo_url': sponsor_logo_url_if_sponsored(
                is_sponsored, sponsor_logo_url
            ),
            'visible_on_site': visible_on_site,
            'registration_open': registration_open,
            'coin_cost': coin_cost,
            'coin_refund_policy': coin_refund_policy.value,
            'coin_charge_mode': coin_charge_mode.value,
        },
        created_at=now,
    )

    db.session.commit()
    return Ok(_db_tournament_to_model(db_tournament))


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
    if registration_mode == RegistrationMode.solo:
        team_size = 1
        substitute_count = 0
        coin_charge_mode = CoinChargeMode.captain_only

    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    settings_error = validate_tournament_settings(
        mode=mode,
        registration_mode=registration_mode,
        team_size=team_size,
        substitute_count=substitute_count,
        participant_limit=participant_limit,
        coin_cost=coin_cost,
    )
    if settings_error is not None:
        return Err(settings_error)

    if category_id is None:
        resolved_category_id = db_tournament.category_id
    else:
        resolved_category_id_result = _resolve_tournament_category_id_for_party(
            party_id, category_id
        )
        if resolved_category_id_result.is_err():
            return Err(resolved_category_id_result.unwrap_err())
        resolved_category_id = resolved_category_id_result.unwrap()

    mode_changes_result = apply_mode_changes(db_tournament, mode, registration_mode)
    if mode_changes_result.is_err():
        return Err(mode_changes_result.unwrap_err())
    mode_changes = mode_changes_result.unwrap()

    db_tournament.title = title.strip()
    db_tournament.subtitle = clean_text(subtitle)
    db_tournament.logo_url = clean_text(logo_url)
    db_tournament.is_sponsored = is_sponsored
    db_tournament.sponsor_logo_url = sponsor_logo_url_if_sponsored(
        is_sponsored, sponsor_logo_url
    )
    db_tournament.game = clean_text(game)
    db_tournament.starts_at = starts_at
    db_tournament.visible_on_site = visible_on_site
    db_tournament.rules_page_slug = clean_text(rules_page_slug)
    db_tournament.registration_open = registration_open
    db_tournament.registration_deadline = registration_deadline
    db_tournament.roster_lock_at = roster_lock_at
    db_tournament.checkin_open_at = checkin_open_at
    db_tournament.checkin_close_at = checkin_close_at
    db_tournament.team_size = team_size
    db_tournament.substitute_count = substitute_count
    db_tournament.participant_limit = participant_limit
    db_tournament.coin_cost = coin_cost
    db_tournament.coin_refund_policy = coin_refund_policy.value
    db_tournament.coin_charge_mode = coin_charge_mode.value
    db_tournament.category_id = resolved_category_id
    db_tournament.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_updated',
        payload={
            'title': title,
            'mode': mode.value,
            'mode_changed': mode_changes.mode_changed,
            'registration_mode': registration_mode.value,
            'registration_mode_changed': mode_changes.registration_mode_changed,
            'deleted_stage_count': mode_changes.deleted_stage_count,
            'category_id': str(resolved_category_id),
            'visible_on_site': visible_on_site,
            'registration_open': registration_open,
            'coin_cost': coin_cost,
            'coin_refund_policy': coin_refund_policy.value,
            'coin_charge_mode': coin_charge_mode.value,
            'logo_url': clean_text(logo_url),
            'is_sponsored': is_sponsored,
            'sponsor_logo_url': sponsor_logo_url_if_sponsored(
                is_sponsored, sponsor_logo_url
            ),
        },
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    if db_tournament.discord_enabled:
        _sync_discord_thread_for_tournament(db_tournament)
    return Ok(_db_tournament_to_model(db_tournament))


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
        (_db_tournament_to_model(item) for item in db_tournaments),
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
    return _db_tournament_to_model(db_tournament)


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
    return _db_tournament_to_model(db_tournament)
