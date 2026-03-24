"""
byceps.services.netsession_tourney.service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
import random
import secrets
from typing import Any, Iterable
from uuid import UUID

from flask import current_app, url_for
import httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import DBAPIError
import structlog
try:
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover - optional dependency during rollout
    WebPushException = Exception
    webpush = None

from byceps.database import db
from byceps.services.external_accounts import external_accounts_service
from byceps.services.party.dbmodels import DbParty
from byceps.services.party.models import PartyID
from byceps.services.party import party_setting_service
from byceps.services.site import site_service
from byceps.services.site.models import SiteID
from byceps.services.ticketing import ticket_service
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from . import domain_service
from .dbmodels import (
    DbNetsessionTourneyAuditLog,
    DbNetsessionTourneyBrowserPushConfig,
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyBrowserPushSubscription,
    DbNetsessionTourneyCoinLedgerEntry,
    DbNetsessionTourneyCoinSettings,
    DbNetsessionTourneyDiscordDmConfig,
    DbNetsessionTourneyDiscordDmOutbox,
    DbNetsessionTourneyDiscordDmSubscription,
    DbNetsessionTourneyDiscordOutbox,
    DbNetsessionTourneyMatchChatMessage,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyRegistration,
    DbNetsessionTourneyResultReportReceipt,
    DbNetsessionTourneyStage,
    DbNetsessionTourneySponsorLogoAsset,
    DbNetsessionTourneyTeamMember,
    DbNetsessionTourneyTicketCategoryCoinSettings,
    DbNetsessionTourneyTournamentAdmin,
    DbNetsessionTourneyTournamentCategory,
    DbNetsessionTourneyTournamentPrize,
    DbNetsessionTourneyTournamentRuleTemplate,
    DbNetsessionTourneyTournament,
)
from .engines.base import MatchSpec, SlotSpec, StageEngine
from .engines.registry import (
    find_stage_engine,
    get_stage_type_spec,
    get_stage_type_specs,
)
from .flatout2 import get_flatout2_mode_label
from .models import (
    AuditLogID,
    BrowserPushConfig,
    BrowserPushOutboxID,
    BrowserPushOutboxStatus,
    BrowserPushSubscription,
    BrowserPushSubscriptionID,
    CheckinState,
    CoinChargeMode,
    CoinLedgerEntry,
    CoinLedgerEntryID,
    CoinLedgerEntryKind,
    CoinRefundPolicy,
    CoinSettings,
    DiscordDmConfig,
    DiscordDmOutboxID,
    DiscordDmOutboxStatus,
    DiscordDmSubscription,
    DiscordDmSubscriptionID,
    DiscordOutboxID,
    DiscordOutboxStatus,
    Match,
    MatchChatMessage,
    MatchID,
    MatchResult,
    MatchResultID,
    MatchSlot,
    MatchSlotID,
    MatchState,
    SourceOutcome,
    Participant,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    Registration,
    RegistrationID,
    RegistrationMode,
    RegistrationState,
    StageFamily,
    Stage,
    StageID,
    StageStatus,
    StageType,
    TeamMember,
    TeamMemberID,
    TeamMemberRole,
    TicketCategoryCoinSettings,
    TournamentAdminID,
    TournamentCategory,
    TournamentCategoryID,
    TournamentPrize,
    TournamentPrizeID,
    TournamentRuleTemplate,
    TournamentRuleTemplateID,
    Tournament,
    TournamentID,
    TournamentMode,
    TournamentStatus,
    RuleTemplateBodyFormat,
    UserCoinBalance,
)


log = structlog.get_logger()


@dataclass(frozen=True, kw_only=True)
class _StageRankingData:
    db_stage: DbNetsessionTourneyStage
    db_matches: list[DbNetsessionTourneyMatch]
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]]
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]]
    head_to_head_winner_id_by_pair: dict[frozenset[ParticipantID], ParticipantID]
    opponent_ids_by_participant_id: dict[ParticipantID, list[ParticipantID]]
    is_ffa_scoring_stage: bool


@dataclass(frozen=True, kw_only=True)
class _RoundRobinBuilderPlan:
    group_count: int
    qualifiers_per_group: int
    min_group_size: int
    max_group_size: int
    mode: str = 'standard'

DISCORD_SUPPORTED_EVENTS = {
    'manual_announcement',
    'match_completed',
    'stage_started',
    'tournament_canceled',
    'tournament_finished',
    'tournament_live',
}

DISCORD_MAX_ATTEMPTS = 5
DISCORD_FORUM_TIMEOUT_SECONDS = 10

BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS = {
    'tournament_live',
    'tournament_closed',
    'tournament_canceled',
    'manual_announcement',
    'match_ready',
    'flatout2_host_assigned',
    'result_submitted',
    'schedule_changed',
    'dispute_opened',
    'chat_message_posted',
}

DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS = {
    'tournament_live',
    'tournament_canceled',
    'match_ready',
    'flatout2_host_assigned',
    'result_submitted',
}

STAGE_BUILDER_KIND_V1 = 'stage_builder_v1'
STAGE_BUILDER_MAIN_STAGE_SIZES = {
    8,
    16,
    32,
    64,
    128,
    256,
    512,
    1024,
}
SWISS_THRESHOLDS = {2, 3, 4}

BROWSER_PUSH_MAX_ATTEMPTS = 5
DISCORD_DM_MAX_ATTEMPTS = 5
DISCORD_DM_TIMEOUT_SECONDS = 10

ACTIVE_PARTICIPANT_STATUS_VALUES = {
    ParticipantStatus.forming.value,
    ParticipantStatus.ready.value,
    ParticipantStatus.checked_in.value,
    ParticipantStatus.locked.value,
}
BRACKET_READY_PARTICIPANT_STATUS_VALUES = {
    ParticipantStatus.ready.value,
    ParticipantStatus.checked_in.value,
    ParticipantStatus.locked.value,
}

RESULT_REPORT_MODE_BOTH_MUST_CONFIRM = 'both_must_confirm'
RESULT_REPORT_MODE_WINNER_CAN_REPORT = 'winner_can_report'
RESULT_REPORT_MODE_LOSER_CAN_REPORT = 'loser_can_report'
RESULT_REPORT_MODE_ADMIN_ONLY = 'admin_only'
RESULT_REPORT_MODES = {
    RESULT_REPORT_MODE_BOTH_MUST_CONFIRM,
    RESULT_REPORT_MODE_WINNER_CAN_REPORT,
    RESULT_REPORT_MODE_LOSER_CAN_REPORT,
    RESULT_REPORT_MODE_ADMIN_ONLY,
}
DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG = 'grand_final_reset_skipped'
DEFAULT_TOURNAMENT_CATEGORY_TITLE = 'Allgemein'


@dataclass(frozen=True, kw_only=True)
class StageRoundGenerationPreview:
    round_no: int
    match_count: int
    suggested_starts_at: datetime | None
    display_title: str | None = None


@dataclass(frozen=True, kw_only=True)
class StageMatchGenerationPreviewParticipant:
    participant_id: ParticipantID
    name: str


@dataclass(frozen=True, kw_only=True)
class StageGeneratedMatchPreview:
    round_no: int
    match_no: int
    participants: list[StageMatchGenerationPreviewParticipant]


@dataclass(frozen=True, kw_only=True)
class StageMatchGenerationPreview:
    stage: Stage
    participant_count: int
    match_count: int
    rounds: list[StageRoundGenerationPreview]
    matches_by_round_no: dict[int, list[StageGeneratedMatchPreview]]


@dataclass(frozen=True, kw_only=True)
class _StageGenerationPayload:
    tournament: Tournament
    stage: Stage
    engine: StageEngine
    participants: list[Participant]
    match_specs: list[MatchSpec]
    replace_existing_matches: bool = True


@dataclass(frozen=True, kw_only=True)
class _Flatout2CurrentRoundGenerationContext:
    current_round_no: int
    total_round_count: int
    match_nos: list[int]
    participants: list[Participant]
    replace_existing_matches: bool


@dataclass(frozen=True, kw_only=True)
class _BuilderGroupStageSpec:
    label: str
    participant_ids: list[ParticipantID]
    qualifiers_per_group: int


@dataclass(frozen=True, kw_only=True)
class ManualNotificationDispatchResult:
    recipient_user_count: int
    subscription_count: int


def get_available_stage_type_specs():
    return get_stage_type_specs()


def is_stage_type_compatible_with_registration_mode(
    stage_type: StageType, registration_mode: RegistrationMode
) -> bool:
    return _is_stage_type_compatible_with_registration_mode(
        stage_type, registration_mode
    )


def create_tournament_category(
    party_id: PartyID, title: str
) -> Result[TournamentCategory, str]:
    normalized_title = title.strip()
    if not normalized_title:
        return Err('Category title is required.')

    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unknown party.')

    existing_db_category = db.session.scalar(
        select(DbNetsessionTourneyTournamentCategory).filter_by(
            party_id=party_id, title=normalized_title
        )
    )
    if existing_db_category is not None:
        return Err('Category title is already in use.')

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
        return Err('Unknown category.')

    normalized_title = title.strip()
    if not normalized_title:
        return Err('Category title is required.')

    existing_db_category = db.session.scalar(
        select(DbNetsessionTourneyTournamentCategory).filter_by(
            party_id=db_category.party_id,
            title=normalized_title,
        )
    )
    if existing_db_category is not None and existing_db_category.id != db_category.id:
        return Err('Category title is already in use.')

    db_category.title = normalized_title
    db.session.commit()

    return Ok(_db_tournament_category_to_model(db_category))


def move_tournament_category_up(
    category_id: TournamentCategoryID,
) -> Result[None, str]:
    db_category = _find_db_tournament_category(category_id)
    if db_category is None:
        return Err('Unknown category.')

    db_category_list = db_category.party.netsession_tourney_tournament_categories
    if db_category.position == 1:
        return Err('Category is already at the top.')

    db_popped_category = db_category_list.pop(db_category.position - 1)
    db_category_list.insert(db_popped_category.position - 2, db_popped_category)

    db.session.commit()
    return Ok(None)


def move_tournament_category_down(
    category_id: TournamentCategoryID,
) -> Result[None, str]:
    db_category = _find_db_tournament_category(category_id)
    if db_category is None:
        return Err('Unknown category.')

    db_category_list = db_category.party.netsession_tourney_tournament_categories
    if db_category.position == len(db_category_list):
        return Err('Category is already at the bottom.')

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
        return Err('Rule template slug is required.')
    if not normalized_title:
        return Err('Rule template title is required.')
    if not normalized_body:
        return Err('Rule template body is required.')

    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unknown party.')

    existing_db_rule_template = db.session.scalar(
        select(DbNetsessionTourneyTournamentRuleTemplate).filter_by(
            party_id=party_id,
            slug=normalized_slug,
        )
    )
    if existing_db_rule_template is not None:
        return Err('Rule template slug is already in use.')

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
        return Err('Unknown rule template.')

    normalized_slug = slug.strip()
    normalized_title = title.strip()
    normalized_body = body.strip()

    if not normalized_slug:
        return Err('Rule template slug is required.')
    if not normalized_title:
        return Err('Rule template title is required.')
    if not normalized_body:
        return Err('Rule template body is required.')

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
        return Err('Rule template slug is already in use.')

    db_rule_template.slug = normalized_slug
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
        return Err('Prize position must be at least 1.')
    if not normalized_body:
        return Err('Prize description is required.')

    existing_db_prize = db.session.scalar(
        select(DbNetsessionTourneyTournamentPrize).filter_by(
            tournament_id=tournament_id,
            position=position,
        )
    )
    if existing_db_prize is not None:
        return Err('A prize for this position already exists.')

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
        return Err('Unknown prize.')

    normalized_body = body.strip()
    if position < 1:
        return Err('Prize position must be at least 1.')
    if not normalized_body:
        return Err('Prize description is required.')

    existing_db_prize = db.session.scalar(
        select(DbNetsessionTourneyTournamentPrize).filter_by(
            tournament_id=db_prize.tournament_id,
            position=position,
        )
    )
    if existing_db_prize is not None and existing_db_prize.id != db_prize.id:
        return Err('A prize for this position already exists.')

    db_prize.position = position
    db_prize.body_format = body_format.value
    db_prize.body = normalized_body
    db_prize.updated_at = datetime.utcnow()

    db.session.commit()
    return Ok(_db_tournament_prize_to_model(db_prize))


def delete_tournament_prize(prize_id: TournamentPrizeID) -> Result[None, str]:
    db_prize = _find_db_tournament_prize(prize_id)
    if db_prize is None:
        return Err('Unknown prize.')

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

    mode_validation_result = _validate_mode_for_registration_mode(
        mode=mode,
        registration_mode=registration_mode,
    )
    if mode_validation_result.is_err():
        return Err(mode_validation_result.unwrap_err())

    validation_result = _validate_team_size_for_registration_mode(
        registration_mode=registration_mode,
        team_size=team_size,
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    substitute_validation_result = _validate_substitute_count_for_registration_mode(
        registration_mode=registration_mode,
        substitute_count=substitute_count,
    )
    if substitute_validation_result.is_err():
        return Err(substitute_validation_result.unwrap_err())

    participant_limit_validation_result = _validate_participant_limit(
        participant_limit
    )
    if participant_limit_validation_result.is_err():
        return Err(participant_limit_validation_result.unwrap_err())

    coin_cost_validation_result = _validate_coin_cost(coin_cost)
    if coin_cost_validation_result.is_err():
        return Err(coin_cost_validation_result.unwrap_err())

    if find_tournament_by_slug_for_party(party_id, slug) is not None:
        return Err('Slug is already in use.')

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
            'logo_url': logo_url.strip() if logo_url else None,
            'is_sponsored': is_sponsored,
            'sponsor_logo_url': (
                sponsor_logo_url.strip()
                if is_sponsored and sponsor_logo_url
                else None
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

    mode_validation_result = _validate_mode_for_registration_mode(
        mode=mode,
        registration_mode=registration_mode,
    )
    if mode_validation_result.is_err():
        return Err(mode_validation_result.unwrap_err())

    validation_result = _validate_team_size_for_registration_mode(
        registration_mode=registration_mode,
        team_size=team_size,
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    substitute_validation_result = _validate_substitute_count_for_registration_mode(
        registration_mode=registration_mode,
        substitute_count=substitute_count,
    )
    if substitute_validation_result.is_err():
        return Err(substitute_validation_result.unwrap_err())

    participant_limit_validation_result = _validate_participant_limit(
        participant_limit
    )
    if participant_limit_validation_result.is_err():
        return Err(participant_limit_validation_result.unwrap_err())

    coin_cost_validation_result = _validate_coin_cost(coin_cost)
    if coin_cost_validation_result.is_err():
        return Err(coin_cost_validation_result.unwrap_err())

    if category_id is None:
        resolved_category_id = db_tournament.category_id
    else:
        resolved_category_id_result = _resolve_tournament_category_id_for_party(
            party_id, category_id
        )
        if resolved_category_id_result.is_err():
            return Err(resolved_category_id_result.unwrap_err())
        resolved_category_id = resolved_category_id_result.unwrap()

    mode_changed = db_tournament.mode != mode.value
    registration_mode_changed = (
        db_tournament.registration_mode != registration_mode.value
    )
    deleted_stage_count = 0
    if mode_changed:
        if db_tournament.status != TournamentStatus.draft.value:
            return Err(
                'Tournament mode can only be changed while tournament is in draft.'
            )

        deleted_stage_count = _delete_all_stages_for_tournament(tournament_id)
        db_tournament.mode = mode.value

    if registration_mode_changed:
        if db_tournament.status != TournamentStatus.draft.value:
            return Err(
                'Registration mode can only be changed while tournament is in draft.'
            )

        has_active_participants = bool(
            db.session.scalar(
                select(db.func.count(DbNetsessionTourneyParticipant.id))
                .filter_by(tournament_id=tournament_id)
                .filter(
                    DbNetsessionTourneyParticipant.status.in_(
                        ACTIVE_PARTICIPANT_STATUS_VALUES
                    )
                )
            )
        )
        if has_active_participants:
            return Err(
                'Registration mode can only be changed while no active participants exist.'
            )

        db_tournament.registration_mode = registration_mode.value

    db_tournament.title = title.strip()
    db_tournament.subtitle = subtitle.strip() if subtitle else None
    db_tournament.logo_url = logo_url.strip() if logo_url else None
    db_tournament.is_sponsored = is_sponsored
    db_tournament.sponsor_logo_url = (
        sponsor_logo_url.strip() if is_sponsored and sponsor_logo_url else None
    )
    db_tournament.game = game.strip() if game else None
    db_tournament.starts_at = starts_at
    db_tournament.visible_on_site = visible_on_site
    db_tournament.rules_page_slug = (
        rules_page_slug.strip() if rules_page_slug else None
    )
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
            'mode_changed': mode_changed,
            'registration_mode': registration_mode.value,
            'registration_mode_changed': registration_mode_changed,
            'deleted_stage_count': deleted_stage_count,
            'category_id': str(resolved_category_id),
            'visible_on_site': visible_on_site,
            'registration_open': registration_open,
            'coin_cost': coin_cost,
            'coin_refund_policy': coin_refund_policy.value,
            'coin_charge_mode': coin_charge_mode.value,
            'logo_url': logo_url.strip() if logo_url else None,
            'is_sponsored': is_sponsored,
            'sponsor_logo_url': (
                sponsor_logo_url.strip()
                if is_sponsored and sponsor_logo_url
                else None
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


def get_tournament_admin_user_ids(tournament_id: TournamentID) -> set[UserID]:
    user_ids = db.session.scalars(
        select(DbNetsessionTourneyTournamentAdmin.user_id).filter_by(
            tournament_id=tournament_id
        )
    ).all()

    return set(user_ids)


def set_tournament_admin_user_ids(
    party_id: PartyID,
    tournament_id: TournamentID,
    admin_user_ids: set[UserID],
    initiator: User,
) -> Result[set[UserID], str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    normalized_user_ids = set(admin_user_ids)

    db.session.execute(
        delete(DbNetsessionTourneyTournamentAdmin).where(
            DbNetsessionTourneyTournamentAdmin.tournament_id == tournament_id
        )
    )

    now = datetime.utcnow()
    for user_id in sorted(normalized_user_ids, key=str):
        db.session.add(
            DbNetsessionTourneyTournamentAdmin(
                TournamentAdminID(generate_uuid7()),
                tournament_id,
                user_id,
                now,
            )
        )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_admins_set',
        payload={'admin_user_ids': [str(user_id) for user_id in sorted(normalized_user_ids, key=str)]},
        created_at=now,
    )

    db.session.commit()
    return Ok(normalized_user_ids)


def get_coin_settings(party_id: PartyID) -> CoinSettings:
    db_settings = db.session.get(DbNetsessionTourneyCoinSettings, party_id)
    if db_settings is None:
        return _build_default_coin_settings(party_id)

    return _db_coin_settings_to_model(db_settings)


def get_ticket_category_coin_settings_for_party(
    party_id: PartyID,
) -> list[TicketCategoryCoinSettings]:
    db_rows = db.session.scalars(
        select(DbNetsessionTourneyTicketCategoryCoinSettings)
        .filter_by(party_id=party_id)
        .order_by(
            DbNetsessionTourneyTicketCategoryCoinSettings.ticket_category_id.asc()
        )
    ).all()

    return [
        _db_ticket_category_coin_settings_to_model(db_row) for db_row in db_rows
    ]


def configure_coin_settings(
    party_id: PartyID,
    initiator: User,
    *,
    enabled: bool,
    default_coin_amount: int,
    ticket_category_coin_amounts: dict[Any, int],
) -> Result[CoinSettings, str]:
    _ = initiator

    if default_coin_amount < 0:
        return Err('Default coin amount must not be negative.')

    for amount in ticket_category_coin_amounts.values():
        if amount < 0:
            return Err('Ticket category coin amounts must not be negative.')

    now = datetime.utcnow()
    db_settings = db.session.get(DbNetsessionTourneyCoinSettings, party_id)
    if db_settings is None:
        db_settings = DbNetsessionTourneyCoinSettings(
            party_id,
            now,
            enabled=enabled,
            default_coin_amount=default_coin_amount,
        )
        db.session.add(db_settings)
    else:
        db_settings.enabled = enabled
        db_settings.default_coin_amount = default_coin_amount
        db_settings.updated_at = now

    existing_rows = {
        db_row.ticket_category_id: db_row
        for db_row in db.session.scalars(
            select(DbNetsessionTourneyTicketCategoryCoinSettings).filter_by(
                party_id=party_id
            )
        ).all()
    }

    normalized_ids = set(ticket_category_coin_amounts.keys())

    for ticket_category_id, amount in ticket_category_coin_amounts.items():
        db_row = existing_rows.get(ticket_category_id)
        if db_row is None:
            db.session.add(
                DbNetsessionTourneyTicketCategoryCoinSettings(
                    party_id,
                    ticket_category_id,
                    amount,
                    now,
                )
            )
            continue

        db_row.coin_amount = amount
        db_row.updated_at = now

    for ticket_category_id, db_row in existing_rows.items():
        if ticket_category_id not in normalized_ids:
            db.session.delete(db_row)

    db.session.commit()
    return Ok(get_coin_settings(party_id))


def get_user_coin_balance(party_id: PartyID, user_id: UserID) -> UserCoinBalance:
    ticket_coin_amount = _get_ticket_coin_amount_for_user(party_id, user_id)
    manual_adjustment_amount = _get_manual_coin_adjustment_amount_for_user(
        party_id, user_id
    )
    registration_delta_amount = _get_registration_coin_delta_amount_for_user(
        party_id, user_id
    )

    return UserCoinBalance(
        party_id=party_id,
        user_id=user_id,
        ticket_coin_amount=ticket_coin_amount,
        manual_adjustment_amount=manual_adjustment_amount,
        registration_delta_amount=registration_delta_amount,
        available_coins=(
            ticket_coin_amount
            + manual_adjustment_amount
            + registration_delta_amount
        ),
    )


def get_user_coin_balances(
    party_id: PartyID, user_ids: set[UserID]
) -> dict[UserID, UserCoinBalance]:
    return {
        user_id: get_user_coin_balance(party_id, user_id)
        for user_id in user_ids
    }


def get_recent_coin_ledger_entries_for_user(
    party_id: PartyID, user_id: UserID, *, limit: int = 10
) -> list[CoinLedgerEntry]:
    db_rows = db.session.scalars(
        select(DbNetsessionTourneyCoinLedgerEntry)
        .filter_by(party_id=party_id, user_id=user_id)
        .order_by(DbNetsessionTourneyCoinLedgerEntry.created_at.desc())
        .limit(limit)
    ).all()

    return [_db_coin_ledger_entry_to_model(db_row) for db_row in db_rows]


def adjust_user_coins(
    party_id: PartyID,
    user_id: UserID,
    amount_delta: int,
    note: str,
    initiator: User,
) -> Result[UserCoinBalance, str]:
    if amount_delta == 0:
        return Err('Amount delta must not be zero.')

    note_clean = note.strip() or None
    now = datetime.utcnow()
    db.session.add(
        DbNetsessionTourneyCoinLedgerEntry(
            CoinLedgerEntryID(generate_uuid7()),
            party_id,
            user_id,
            amount_delta,
            CoinLedgerEntryKind.admin_adjustment.value,
            now,
            note=note_clean,
            created_by_user_id=initiator.id,
        )
    )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='user',
        object_id=user_id,
        action='coin_balance_adjusted',
        payload={
            'party_id': party_id,
            'user_id': str(user_id),
            'amount_delta': amount_delta,
            'note': note_clean,
        },
        created_at=now,
    )

    db.session.commit()
    return Ok(get_user_coin_balance(party_id, user_id))


def is_tournament_coin_refund_available(tournament: Tournament) -> bool:
    if tournament.status in {
        TournamentStatus.closed,
        TournamentStatus.canceled,
    }:
        return False

    if (
        tournament.coin_refund_policy
        == CoinRefundPolicy.until_tournament_end
    ):
        return True

    first_stage_id = db.session.scalar(
        select(DbNetsessionTourneyStage.id)
        .filter_by(tournament_id=tournament.id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
        .limit(1)
    )
    if first_stage_id is None:
        return True

    round_one_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            tournament_id=tournament.id,
            stage_id=first_stage_id,
            round_no=1,
        )
    )
    if not round_one_match_count:
        return True

    completed_round_one_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            tournament_id=tournament.id,
            stage_id=first_stage_id,
            round_no=1,
            state=MatchState.completed.value,
        )
    )

    return int(completed_round_one_match_count or 0) < int(
        round_one_match_count or 0
    )


def build_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
    swiss_threshold: int | None,
    match_duration_minutes: int | None,
    max_matches_per_round: int | None,
    break_between_rounds_minutes: int | None,
    initiator: User,
) -> Result[list[Stage], str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.draft.value:
        return Err(
            'Die Stage-Struktur kann nur im Draft-Status aufgebaut werden.'
        )

    existing_stage_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyStage.id)).filter_by(
            tournament_id=tournament_id
        )
    )
    if existing_stage_count:
        return Err(
            'Für den Stage Builder V1 muss das Turnier noch keine Stages haben.'
        )

    tournament_mode = TournamentMode(db_tournament.mode)
    if tournament_mode == TournamentMode.ffa:
        return _build_ffa_stage_builder_plan(
            party_id,
            tournament_id,
            generation_basis=generation_basis,
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            preliminary_type=preliminary_type,
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
            break_between_rounds_minutes=break_between_rounds_minutes,
            initiator=initiator,
        )

    if tournament_mode != TournamentMode.duel:
        return Err('Der Stage Builder V1 unterstützt diesen Turniermodus nicht.')

    if main_stage_type not in {
        StageType.single_elimination,
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return Err('Main Stage type is not supported by the builder.')

    if main_stage_size not in STAGE_BUILDER_MAIN_STAGE_SIZES:
        return Err('Main Stage size is invalid.')

    if generation_basis != 'ready':
        return Err('Generation basis is invalid.')

    if preliminary_type not in {
        None,
        StageType.round_robin_groups,
        StageType.swiss,
    }:
        return Err('Preliminary stage type is not supported by the builder.')

    if preliminary_type == StageType.round_robin_groups:
        if round_robin_builder_mode not in {None, 'standard', 'manual_group_count'}:
            return Err('Round-Robin strategy is invalid.')
        if round_robin_builder_mode == 'manual_group_count':
            if round_robin_group_count is None or round_robin_group_count < 2:
                return Err(
                    'Für die Expertenoption muss eine gültige Gruppenzahl gewählt werden.'
                )

    if preliminary_type == StageType.swiss:
        if swiss_threshold not in SWISS_THRESHOLDS:
            return Err('Swiss preliminaries require a valid threshold.')

    if match_duration_minutes is not None and (
        match_duration_minutes < 1 or match_duration_minutes > 240
    ):
        return Err('Match duration is invalid.')

    if max_matches_per_round is not None and (
        max_matches_per_round < 1 or max_matches_per_round > 256
    ):
        return Err('Maximum matches per round is invalid.')

    if break_between_rounds_minutes is not None and (
        break_between_rounds_minutes < 0
        or break_between_rounds_minutes > 240
    ):
        return Err('Break between rounds is invalid.')

    now = datetime.utcnow()
    created_stages: list[DbNetsessionTourneyStage] = []

    preliminary_stage: DbNetsessionTourneyStage | None = None
    if preliminary_type is not None:
        preliminary_settings = {
            'participant_source_mode': 'tournament',
            'builder_kind': STAGE_BUILDER_KIND_V1,
            'builder_role': 'preliminary',
            'builder_generation_basis': generation_basis,
            'builder_main_stage_size': main_stage_size,
            'builder_auto_skip_if_not_needed': True,
            'result_report_mode': RESULT_REPORT_MODE_ADMIN_ONLY
            if preliminary_type == StageType.swiss
            else 'both_must_confirm',
        }
        if preliminary_type == StageType.swiss:
            preliminary_settings['swiss_threshold'] = swiss_threshold
            preliminary_settings['round_count'] = (
                _get_swiss_round_count_for_threshold(swiss_threshold)
            )
        elif preliminary_type == StageType.round_robin_groups:
            preliminary_settings['builder_round_robin_mode'] = (
                round_robin_builder_mode or 'standard'
            )
            if round_robin_group_count is not None:
                preliminary_settings['builder_round_robin_group_count'] = (
                    round_robin_group_count
                )
        if match_duration_minutes is not None:
            preliminary_settings['match_duration_minutes'] = (
                match_duration_minutes
            )
        if max_matches_per_round is not None:
            preliminary_settings['max_matches_per_round'] = (
                max_matches_per_round
            )
        if break_between_rounds_minutes is not None:
            preliminary_settings['break_between_rounds_minutes'] = (
                break_between_rounds_minutes
            )

        preliminary_stage = DbNetsessionTourneyStage(
            StageID(generate_uuid7()),
            tournament_id,
            1,
            preliminary_type,
            'Vorrunde',
            now,
            settings_json=preliminary_settings,
        )
        db.session.add(preliminary_stage)
        created_stages.append(preliminary_stage)

    main_stage_order_no = 2 if preliminary_stage is not None else 1
    main_stage_settings: dict[str, Any] = {
        'builder_kind': STAGE_BUILDER_KIND_V1,
        'builder_role': 'main',
        'builder_generation_basis': generation_basis,
        'builder_main_stage_size': main_stage_size,
        'result_report_mode': 'both_must_confirm',
    }
    if preliminary_stage is None:
        main_stage_settings['participant_source_mode'] = 'tournament'
    else:
        main_stage_settings['participant_source_mode'] = 'stage_qualifiers'
        main_stage_settings['qualifier_source_stage_ids'] = [
            str(preliminary_stage.id)
        ]
        main_stage_settings['qualifier_selection_mode'] = (
            'per_group'
            if preliminary_type == StageType.round_robin_groups
            else 'per_stage'
        )
        main_stage_settings['qualifier_top_n'] = (
            main_stage_size if preliminary_type == StageType.swiss else 1
        )
        main_stage_settings['builder_auto_qualifier_count'] = True
        main_stage_settings['builder_preliminary_stage_id'] = str(
            preliminary_stage.id
        )
    if match_duration_minutes is not None:
        main_stage_settings['match_duration_minutes'] = match_duration_minutes
    if max_matches_per_round is not None:
        main_stage_settings['max_matches_per_round'] = max_matches_per_round
    if break_between_rounds_minutes is not None:
        main_stage_settings['break_between_rounds_minutes'] = (
            break_between_rounds_minutes
        )

    main_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        main_stage_order_no,
        main_stage_type,
        'Hauptturnier',
        now,
        settings_json=main_stage_settings,
    )
    db.session.add(main_stage)
    created_stages.append(main_stage)

    if preliminary_stage is not None:
        # Ensure the newly created stage row exists before inserting
        # structure-only matches that reference its `stage_id`.
        db.session.flush()

        pending_specs_result = _build_pending_structure_match_specs_for_stage(
            tournament_id=tournament_id,
            stage_type=main_stage_type,
            participant_count=main_stage_size,
        )
        if pending_specs_result.is_err():
            return Err(pending_specs_result.unwrap_err())

        _persist_generated_matches(
            tournament_id=tournament_id,
            stage_id=main_stage.id,
            specs=pending_specs_result.unwrap(),
        )

    for created_stage in created_stages:
        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='stage',
            object_id=created_stage.id,
            action='stage_created',
            payload={
                'type': created_stage.type,
                'name': created_stage.name,
                'settings': dict(created_stage.settings_json or {}),
                'created_by_builder': True,
            },
            created_at=now,
        )

    db.session.commit()

    return Ok([_db_stage_to_model(stage) for stage in created_stages])


def preview_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
    swiss_threshold: int | None,
) -> Result[dict[str, Any], str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament_mode = TournamentMode(db_tournament.mode)
    if tournament_mode == TournamentMode.ffa:
        return _preview_ffa_stage_builder_plan(
            party_id,
            tournament_id,
            generation_basis=generation_basis,
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            preliminary_type=preliminary_type,
        )

    if tournament_mode != TournamentMode.duel:
        return Err('Der Stage Builder V1 unterstützt diesen Turniermodus nicht.')

    if main_stage_type not in {
        StageType.single_elimination,
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return Err('Main Stage type is not supported by the builder.')

    if main_stage_size not in STAGE_BUILDER_MAIN_STAGE_SIZES:
        return Err('Main Stage size is invalid.')

    if generation_basis != 'ready':
        return Err('Generation basis is invalid.')

    if preliminary_type not in {
        None,
        StageType.round_robin_groups,
        StageType.swiss,
    }:
        return Err('Preliminary stage type is not supported by the builder.')

    if preliminary_type == StageType.round_robin_groups:
        if round_robin_builder_mode not in {None, 'standard', 'manual_group_count'}:
            return Err('Round-Robin strategy is invalid.')
        if round_robin_builder_mode == 'manual_group_count':
            if round_robin_group_count is None or round_robin_group_count < 2:
                return Err(
                    'Für die Expertenoption muss eine gültige Gruppenzahl gewählt werden.'
                )

    if preliminary_type == StageType.swiss:
        if swiss_threshold not in SWISS_THRESHOLDS:
            return Err('Swiss preliminaries require a valid threshold.')

    participants = get_participants_for_tournament(party_id, tournament_id)
    ready_participants = domain_service.select_ready_participants(participants)
    participant_count = len(ready_participants)

    preview: dict[str, Any] = {
        'generation_basis': generation_basis,
        'main_stage_type': main_stage_type,
        'main_stage_size': main_stage_size,
        'participant_count': participant_count,
        'preliminary_type': preliminary_type,
        'needs_preliminary': (
            preliminary_type is not None and participant_count > main_stage_size
        ),
    }

    if preliminary_type is None or participant_count <= main_stage_size:
        return Ok(preview)

    if preliminary_type == StageType.round_robin_groups:
        plan_result = _resolve_round_robin_builder_plan(
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            round_robin_builder_mode=round_robin_builder_mode,
            round_robin_group_count=round_robin_group_count,
        )
        if plan_result.is_err():
            return Err(plan_result.unwrap_err())

        plan = plan_result.unwrap()
        group_sizes = _distribute_evenly(participant_count, plan.group_count)
        preview.update(
            {
                'group_count': plan.group_count,
                'qualifiers_per_group': plan.qualifiers_per_group,
                'min_group_size': plan.min_group_size,
                'max_group_size': plan.max_group_size,
                'group_sizes': group_sizes,
                'round_robin_builder_mode': plan.mode,
                'match_count': sum(
                    size * (size - 1) // 2 for size in group_sizes
                ),
            }
        )
        return Ok(preview)

    if preliminary_type == StageType.swiss:
        round_count = _get_swiss_round_count_for_threshold(swiss_threshold)
        preview.update(
            {
                'swiss_threshold': swiss_threshold,
                'round_count': round_count,
                'qualifier_count': main_stage_size,
            }
        )
        return Ok(preview)

    return Ok(preview)


def _build_ffa_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    match_duration_minutes: int | None,
    max_matches_per_round: int | None,
    break_between_rounds_minutes: int | None,
    initiator: User,
) -> Result[list[Stage], str]:
    validation_result = _validate_ffa_stage_builder_settings(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
        preliminary_type=preliminary_type,
        generation_basis=generation_basis,
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    if match_duration_minutes is not None and (
        match_duration_minutes < 1 or match_duration_minutes > 240
    ):
        return Err('Match duration is invalid.')

    if max_matches_per_round is not None and (
        max_matches_per_round < 1 or max_matches_per_round > 256
    ):
        return Err('Maximum matches per round is invalid.')

    if break_between_rounds_minutes is not None and (
        break_between_rounds_minutes < 0
        or break_between_rounds_minutes > 240
    ):
        return Err('Break between rounds is invalid.')

    if max_players_per_match is None:
        return Err('Maximum players per match is required for the FFA builder.')

    participants = get_participants_for_tournament(party_id, tournament_id)
    ready_participants = domain_service.select_ready_participants(participants)
    participant_count = len(ready_participants)
    uses_preliminary = (
        preliminary_type is not None and participant_count > main_stage_size
    )

    now = datetime.utcnow()
    created_stages: list[DbNetsessionTourneyStage] = []
    next_order_no = 1
    preliminary_stage: DbNetsessionTourneyStage | None = None
    last_preliminary_source_stage_id: StageID | None = None

    preliminary_preview: dict[str, Any] | None = None
    if uses_preliminary and preliminary_type is not None:
        preliminary_preview_result = _preview_ffa_stage_builder_stage(
            tournament_id=tournament_id,
            stage_type=preliminary_type,
            participant_count=participant_count,
            max_players_per_match=max_players_per_match,
            stop_when_participants_at_most=(
                main_stage_size
                if preliminary_type == StageType.ffa_flatout2_single_elimination
                else None
            ),
        )
        if preliminary_preview_result.is_err():
            return Err(preliminary_preview_result.unwrap_err())
        preliminary_preview = preliminary_preview_result.unwrap()

    if uses_preliminary and preliminary_type is not None:
        preliminary_settings = _build_ffa_stage_builder_common_settings(
            generation_basis=generation_basis,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
            break_between_rounds_minutes=break_between_rounds_minutes,
        )
        preliminary_settings.update(
            {
                'builder_role': 'preliminary',
                'participant_source_mode': 'tournament',
            }
        )

        if preliminary_type == StageType.ffa_flatout2_single_elimination:
            preliminary_stage, preliminary_round_stages = (
                _create_flatout2_builder_round_stages(
                    tournament_id=tournament_id,
                    order_no_start=next_order_no,
                    container_name='Vorrunden',
                    role='preliminary',
                    stage_type=preliminary_type,
                    round_summaries=(
                        preliminary_preview['round_summaries']
                        if preliminary_preview is not None
                        else []
                    ),
                    common_settings=preliminary_settings,
                    initial_source_mode='tournament',
                    initial_source_stage_ids=None,
                    initial_qualifier_top_n=None,
                    initial_qualifier_top_n_per_match=None,
                    now=now,
                )
            )
            created_stages.append(preliminary_stage)
            created_stages.extend(preliminary_round_stages)
            next_order_no += 1 + len(preliminary_round_stages)
            last_preliminary_source_stage_id = (
                preliminary_round_stages[-1].id if preliminary_round_stages else None
            )
        else:
            preliminary_stage = DbNetsessionTourneyStage(
                StageID(generate_uuid7()),
                tournament_id,
                next_order_no,
                preliminary_type,
                'Vorrunde',
                now,
                settings_json=preliminary_settings,
            )
            db.session.add(preliminary_stage)
            created_stages.append(preliminary_stage)
            last_preliminary_source_stage_id = preliminary_stage.id
            next_order_no += 1

    main_stage_participant_count = (
        main_stage_size if uses_preliminary else participant_count
    )
    main_preview_result = _preview_ffa_stage_builder_stage(
        tournament_id=tournament_id,
        stage_type=main_stage_type,
        participant_count=main_stage_participant_count,
        max_players_per_match=max_players_per_match,
        stop_when_participants_at_most=None,
    )
    if main_preview_result.is_err():
        return Err(main_preview_result.unwrap_err())
    main_preview = main_preview_result.unwrap()

    main_stage_settings = _build_ffa_stage_builder_common_settings(
        generation_basis=generation_basis,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
        match_duration_minutes=match_duration_minutes,
        max_matches_per_round=max_matches_per_round,
        break_between_rounds_minutes=break_between_rounds_minutes,
    )
    main_stage_settings['builder_role'] = 'main'
    if main_stage_type == StageType.ffa_flatout2_single_elimination:
        main_stage_settings['builder_expected_round_summaries'] = (
            main_preview['round_summaries']
        )
        main_stage_settings['round_count'] = len(main_preview['round_summaries'])
    if preliminary_stage is None:
        main_stage_settings['participant_source_mode'] = 'tournament'
    else:
        if preliminary_type == StageType.ffa_flatout2_single_elimination:
            main_stage_settings['participant_source_mode'] = 'stage_match_qualifiers'
            main_stage_settings['qualifier_source_stage_ids'] = [
                str(last_preliminary_source_stage_id)
            ]
            main_stage_settings['qualifier_top_n_per_match'] = 3
        else:
            main_stage_settings['participant_source_mode'] = 'stage_qualifiers'
            main_stage_settings['qualifier_source_stage_ids'] = [
                str(preliminary_stage.id)
            ]
            main_stage_settings['qualifier_selection_mode'] = 'per_stage'
            main_stage_settings['qualifier_top_n'] = main_stage_size
            main_stage_settings['builder_auto_qualifier_count'] = False
        main_stage_settings['builder_preliminary_stage_id'] = str(
            preliminary_stage.id
        )

    main_stage_name = (
        'Finale'
        if main_stage_type == StageType.ffa_flatout2_single_elimination
        else 'Hauptturnier'
    )
    main_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        next_order_no,
        main_stage_type,
        main_stage_name,
        now,
        settings_json=main_stage_settings,
    )
    db.session.add(main_stage)
    created_stages.append(main_stage)

    for created_stage in created_stages:
        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='stage',
            object_id=created_stage.id,
            action='stage_created',
            payload={
                'type': created_stage.type,
                'name': created_stage.name,
                'settings': dict(created_stage.settings_json or {}),
                'created_by_builder': True,
            },
            created_at=now,
        )

    db.session.commit()

    return Ok([_db_stage_to_model(stage) for stage in created_stages])


def _preview_ffa_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
) -> Result[dict[str, Any], str]:
    validation_result = _validate_ffa_stage_builder_settings(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
        preliminary_type=preliminary_type,
        generation_basis=generation_basis,
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    if max_players_per_match is None:
        return Err('Maximum players per match is required for the FFA builder.')

    participants = get_participants_for_tournament(party_id, tournament_id)
    ready_participants = domain_service.select_ready_participants(participants)
    participant_count = len(ready_participants)

    uses_preliminary = (
        preliminary_type is not None and participant_count > main_stage_size
    )
    generation_blocked_without_preliminary = (
        preliminary_type is None and participant_count > main_stage_size
    )
    preliminary_preview: dict[str, Any] | None = None
    if uses_preliminary:
        preliminary_preview_result = _preview_ffa_stage_builder_stage(
            tournament_id=tournament_id,
            stage_type=preliminary_type,
            participant_count=participant_count,
            max_players_per_match=max_players_per_match,
            stop_when_participants_at_most=(
                main_stage_size
                if preliminary_type == StageType.ffa_flatout2_single_elimination
                else None
            ),
        )
        if preliminary_preview_result.is_err():
            return Err(preliminary_preview_result.unwrap_err())
        preliminary_preview = preliminary_preview_result.unwrap()

    main_stage_participant_count = (
        main_stage_size
        if (uses_preliminary or generation_blocked_without_preliminary)
        else participant_count
    )
    main_preview_result = _preview_ffa_stage_builder_stage(
        tournament_id=tournament_id,
        stage_type=main_stage_type,
        participant_count=main_stage_participant_count,
        max_players_per_match=max_players_per_match,
        stop_when_participants_at_most=None,
    )
    if main_preview_result.is_err():
        return Err(main_preview_result.unwrap_err())
    main_preview = main_preview_result.unwrap()

    return Ok(
        {
            'generation_basis': generation_basis,
            'main_stage_type': main_stage_type,
            'participant_count': participant_count,
            'preliminary_type': preliminary_type,
            'needs_preliminary': participant_count > main_stage_size,
            'uses_preliminary': uses_preliminary,
            'generation_blocked_without_preliminary': (
                generation_blocked_without_preliminary
            ),
            'max_players_per_match': max_players_per_match,
            'qualifier_rule': (
                'top_3'
                if main_stage_type
                == StageType.ffa_flatout2_single_elimination
                else 'dynamic'
            ),
            'round_summaries': main_preview['round_summaries'],
            'match_count': main_preview['match_count'],
            'main_round_summaries': main_preview['round_summaries'],
            'main_match_count': main_preview['match_count'],
            'main_stage_participant_count': main_stage_participant_count,
            'expected_final_heat_size': main_preview['expected_final_heat_size'],
            'preliminary_round_summaries': (
                preliminary_preview['round_summaries']
                if preliminary_preview is not None
                else []
            ),
            'preliminary_match_count': (
                preliminary_preview['match_count']
                if preliminary_preview is not None
                else None
            ),
        }
    )


def _validate_ffa_stage_builder_settings(
    *,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    generation_basis: str,
) -> Result[None, str]:
    allowed_ffa_stage_types = {
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }
    if main_stage_type not in allowed_ffa_stage_types:
        return Err('Main Stage type is not supported by the FFA builder.')

    if main_stage_size not in STAGE_BUILDER_MAIN_STAGE_SIZES:
        return Err('Main Stage size is invalid.')

    if generation_basis != 'ready':
        return Err('Generation basis is invalid.')

    if preliminary_type is not None and preliminary_type not in allowed_ffa_stage_types:
        return Err('Preliminary stage type is not supported by the FFA builder.')

    if max_players_per_match is None:
        return Err('Maximum players per match is required for the FFA builder.')

    if max_players_per_match < 2 or max_players_per_match > 64:
        return Err('Maximum players per match is invalid.')

    if main_stage_type == StageType.ffa_flatout2_single_elimination and (
        max_players_per_match < 6 or max_players_per_match > 8
    ):
        return Err('FlatOut 2 requires 6 to 8 players per match.')

    if preliminary_type == StageType.ffa_flatout2_single_elimination and (
        max_players_per_match < 6 or max_players_per_match > 8
    ):
        return Err('FlatOut 2 requires 6 to 8 players per match.')

    return Ok(None)


def _build_ffa_stage_builder_common_settings(
    *,
    generation_basis: str,
    main_stage_size: int,
    max_players_per_match: int,
    match_duration_minutes: int | None,
    max_matches_per_round: int | None,
    break_between_rounds_minutes: int | None,
) -> dict[str, Any]:
    settings: dict[str, Any] = {
        'builder_kind': STAGE_BUILDER_KIND_V1,
        'builder_generation_basis': generation_basis,
        'builder_mode': TournamentMode.ffa.value,
        'builder_main_stage_size': main_stage_size,
        'max_players_per_match': max_players_per_match,
        'result_report_mode': RESULT_REPORT_MODE_ADMIN_ONLY,
    }
    if match_duration_minutes is not None:
        settings['match_duration_minutes'] = match_duration_minutes
    if max_matches_per_round is not None:
        settings['max_matches_per_round'] = max_matches_per_round
    if break_between_rounds_minutes is not None:
        settings['break_between_rounds_minutes'] = (
            break_between_rounds_minutes
        )

    return settings


def _parse_source_stage_ids(raw_source_stage_ids: Any) -> list[StageID]:
    if not isinstance(raw_source_stage_ids, list):
        return []

    source_stage_ids: list[StageID] = []
    for raw_stage_id in raw_source_stage_ids:
        try:
            source_stage_ids.append(StageID(UUID(str(raw_stage_id))))
        except ValueError:
            continue

    return source_stage_ids


def _build_pending_structure_match_specs_for_stage(
    *,
    tournament_id: TournamentID,
    stage_type: StageType,
    participant_count: int,
) -> Result[list[MatchSpec], str]:
    engine = find_stage_engine(stage_type)
    if engine is None:
        return Err('No engine available for this stage type yet.')

    preview_stage = Stage(
        id=StageID(generate_uuid7()),
        tournament_id=tournament_id,
        order_no=1,
        type=stage_type,
        name='Preview',
        settings={},
        status=StageStatus.draft,
    )
    preview_participant_ids = [
        ParticipantID(generate_uuid7()) for _ in range(participant_count)
    ]
    generated_specs_result = engine.generate(
        preview_stage, preview_participant_ids
    )
    if generated_specs_result.is_err():
        return Err(generated_specs_result.unwrap_err())

    pending_specs = [
        MatchSpec(
            round_no=spec.round_no,
            match_no=spec.match_no,
            state='pending',
            slots=[
                SlotSpec(
                    slot_no=slot.slot_no,
                    participant_id=None,
                    source_match_no=slot.source_match_no,
                    source_outcome=slot.source_outcome,
                )
                for slot in spec.slots
            ],
        )
        for spec in generated_specs_result.unwrap()
    ]

    return Ok(pending_specs)


def _preview_ffa_stage_builder_stage(
    *,
    tournament_id: TournamentID,
    stage_type: StageType,
    participant_count: int,
    max_players_per_match: int,
    stop_when_participants_at_most: int | None = None,
) -> Result[dict[str, Any], str]:
    if stage_type == StageType.ffa_flatout2_single_elimination:
        round_summaries = _summarize_flatout2_builder_rounds(
            participant_count=participant_count,
            max_players_per_match=max_players_per_match,
            stop_when_participants_at_most=stop_when_participants_at_most,
        )
        return Ok(
            {
                'round_summaries': round_summaries,
                'match_count': sum(
                    round_summary['match_count']
                    for round_summary in round_summaries
                ),
                'expected_final_heat_size': (
                    round_summaries[-1]['max_heat_size']
                    if round_summaries
                    else 0
                ),
            }
        )

    engine = find_stage_engine(stage_type)
    if engine is None:
        return Err('No engine available for this FFA builder stage type.')

    preview_stage = Stage(
        id=StageID(generate_uuid7()),
        tournament_id=tournament_id,
        order_no=1,
        type=stage_type,
        name='Preview',
        settings={'max_players_per_match': max_players_per_match},
        status=StageStatus.draft,
    )
    preview_participant_ids = [
        ParticipantID(generate_uuid7()) for _ in range(participant_count)
    ]
    generated_specs_result = engine.generate(
        preview_stage, preview_participant_ids
    )
    if generated_specs_result.is_err():
        return Err(generated_specs_result.unwrap_err())

    specs = generated_specs_result.unwrap()
    round_summaries = _summarize_ffa_builder_match_specs(specs)

    return Ok(
        {
            'round_summaries': round_summaries,
            'match_count': len(specs),
            'expected_final_heat_size': (
                round_summaries[-1]['max_heat_size'] if round_summaries else 0
            ),
        }
    )


def _summarize_flatout2_builder_rounds(
    *,
    participant_count: int,
    max_players_per_match: int,
    stop_when_participants_at_most: int | None,
) -> list[dict[str, int]]:
    if participant_count < 2 or max_players_per_match < 2:
        return []

    qualifier_count_per_match = 3
    round_summaries: list[dict[str, int]] = []
    current_participant_count = participant_count
    round_no = 1

    while current_participant_count > 1:
        match_count = math.ceil(current_participant_count / max_players_per_match)
        if match_count < 1:
            break

        heat_sizes = _distribute_evenly(current_participant_count, match_count)
        max_heat_size = max(heat_sizes) if heat_sizes else 0
        round_summaries.append(
            {
                'round_no': round_no,
                'match_count': match_count,
                'max_heat_size': max_heat_size,
            }
        )

        if match_count == 1:
            break

        qualified_participant_count = match_count * qualifier_count_per_match
        if (
            stop_when_participants_at_most is not None
            and qualified_participant_count <= stop_when_participants_at_most
        ):
            break

        current_participant_count = qualified_participant_count
        round_no += 1

    return round_summaries


def _summarize_ffa_builder_match_specs(
    specs: list[MatchSpec],
) -> list[dict[str, int]]:
    round_summaries = []
    for round_no in sorted({spec.round_no for spec in specs}):
        round_specs = [spec for spec in specs if spec.round_no == round_no]
        heat_sizes = [
            len(
                [
                    slot
                    for slot in spec.slots
                    if slot.participant_id is not None
                    or slot.source_match_no is not None
                ]
            )
            for spec in round_specs
        ]
        round_summaries.append(
            {
                'round_no': round_no,
                'match_count': len(round_specs),
                'max_heat_size': max(heat_sizes) if heat_sizes else 0,
            }
        )

    return round_summaries


def _build_flatout2_round_stage_display_title(
    round_no: int, total_round_count: int, role: str
) -> str:
    if role == 'preliminary':
        return f'Vorrunde {round_no}'

    if total_round_count > 0 and round_no == total_round_count:
        return 'Finale'

    return f'Runde {round_no}'


def _create_flatout2_builder_round_stages(
    *,
    tournament_id: TournamentID,
    order_no_start: int,
    container_name: str,
    role: str,
    stage_type: StageType,
    round_summaries: list[dict[str, int]],
    common_settings: dict[str, Any],
    initial_source_mode: str,
    initial_source_stage_ids: list[StageID] | None,
    initial_qualifier_top_n: int | None,
    initial_qualifier_top_n_per_match: int | None,
    now: datetime,
) -> tuple[DbNetsessionTourneyStage, list[DbNetsessionTourneyStage]]:
    container_settings = dict(common_settings)
    container_settings.update(
        {
            'builder_role': role,
            'builder_is_container': True,
            'builder_materialized_stage_ids': [],
        }
    )
    container_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        order_no_start,
        stage_type,
        container_name,
        now,
        settings_json=container_settings,
    )
    db.session.add(container_stage)

    created_round_stages: list[DbNetsessionTourneyStage] = []
    previous_stage_id: StageID | None = None
    total_round_count = len(round_summaries)

    for index, round_summary in enumerate(round_summaries, start=1):
        round_no = int(round_summary.get('round_no') or index)
        display_title = _build_flatout2_round_stage_display_title(
            round_no,
            total_round_count,
            role,
        )
        stage_name = display_title
        round_settings = dict(common_settings)
        round_settings.update(
            {
                'builder_role': f'{role}_round',
                'builder_parent_stage_id': str(container_stage.id),
                'builder_materialized_round_stage': True,
                'builder_display_round_no': round_no,
                'builder_display_title': display_title,
                'builder_round_is_final': round_no == total_round_count,
                'builder_expected_match_count': round_summary.get('match_count'),
                'builder_expected_max_heat_size': round_summary.get(
                    'max_heat_size'
                ),
                'result_report_mode': RESULT_REPORT_MODE_ADMIN_ONLY,
            }
        )

        if previous_stage_id is None:
            round_settings['participant_source_mode'] = initial_source_mode
            if initial_source_mode in {'stage_qualifiers', 'stage_match_qualifiers'}:
                round_settings['qualifier_source_stage_ids'] = [
                    str(stage_id) for stage_id in (initial_source_stage_ids or [])
                ]
            if initial_qualifier_top_n is not None:
                round_settings['qualifier_top_n'] = initial_qualifier_top_n
            if initial_qualifier_top_n_per_match is not None:
                round_settings['qualifier_top_n_per_match'] = (
                    initial_qualifier_top_n_per_match
                )
        else:
            round_settings['participant_source_mode'] = 'stage_match_qualifiers'
            round_settings['qualifier_source_stage_ids'] = [str(previous_stage_id)]
            round_settings['qualifier_top_n_per_match'] = 3

        db_round_stage = DbNetsessionTourneyStage(
            StageID(generate_uuid7()),
            tournament_id,
            order_no_start + index,
            stage_type,
            stage_name,
            now,
            settings_json=round_settings,
        )
        db.session.add(db_round_stage)
        created_round_stages.append(db_round_stage)
        previous_stage_id = db_round_stage.id

    container_settings['builder_materialized_stage_ids'] = [
        str(db_stage.id) for db_stage in created_round_stages
    ]
    container_settings['builder_materialized_stage_count'] = len(
        created_round_stages
    )
    container_stage.settings_json = container_settings

    return container_stage, created_round_stages


def create_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    type_: StageType,
    name: str,
    settings: dict[str, Any],
    initiator: User,
) -> Result[Stage, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    spec = get_stage_type_spec(type_)
    tournament_mode = TournamentMode(db_tournament.mode)
    if not _is_stage_type_compatible_with_tournament_mode(
        spec.family, tournament_mode
    ):
        return Err('Stage type is not compatible with tournament mode.')

    tournament_registration_mode = RegistrationMode(db_tournament.registration_mode)
    if not _is_stage_type_compatible_with_registration_mode(
        type_, tournament_registration_mode
    ):
        return Err('Stage type is not compatible with registration mode.')

    if not spec.enabled:
        return Err('Stage type is currently disabled.')

    max_order_no = db.session.scalar(
        select(db.func.max(DbNetsessionTourneyStage.order_no)).filter_by(
            tournament_id=tournament_id
        )
    )
    order_no = (max_order_no or 0) + 1

    db_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        order_no,
        type_,
        name.strip(),
        datetime.utcnow(),
        settings_json=dict(settings),
    )
    db.session.add(db_stage)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=db_stage.id,
        action='stage_created',
        payload={'type': type_.value, 'name': name, 'settings': settings},
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(_db_stage_to_model(db_stage))


def update_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    type_: StageType,
    name: str,
    settings: dict[str, Any],
    initiator: User,
) -> Result[Stage, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.draft.value:
        return Err('Stages can only be changed while tournament is in draft.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unknown stage.')

    spec = get_stage_type_spec(type_)
    tournament_mode = TournamentMode(db_tournament.mode)
    if not _is_stage_type_compatible_with_tournament_mode(
        spec.family, tournament_mode
    ):
        return Err('Stage type is not compatible with tournament mode.')

    tournament_registration_mode = RegistrationMode(db_tournament.registration_mode)
    if not _is_stage_type_compatible_with_registration_mode(
        type_, tournament_registration_mode
    ):
        return Err('Stage type is not compatible with registration mode.')

    if not spec.enabled:
        return Err('Stage type is currently disabled.')

    # Matches need regeneration after structural stage changes.
    _delete_stage_matches(stage_id)

    db_stage.type = type_.value
    db_stage.name = name.strip()
    db_stage.settings_json = dict(settings)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=stage_id,
        action='stage_updated',
        payload={
            'type': type_.value,
            'name': name,
            'settings': settings,
        },
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(_db_stage_to_model(db_stage))


def delete_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.draft.value:
        return Err('Stages can only be changed while tournament is in draft.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unknown stage.')

    if _is_builder_round_robin_summary_db_stage(db_stage):
        _delete_builder_generated_group_stages(
            tournament_id,
            db_stage.id,
            initiator=initiator,
        )
        _detach_builder_main_stage_from_preliminary_stage(
            tournament_id, db_stage.id
        )
    elif _is_builder_container_db_stage(db_stage):
        _delete_builder_generated_child_stages(
            tournament_id,
            db_stage.id,
            initiator=initiator,
        )

    _delete_stage_matches(stage_id)
    db.session.delete(db_stage)
    # Flush the deletion first so the subsequent renumbering does not
    # temporarily collide with the still-persisted (tournament_id, order_no)
    # unique constraint.
    db.session.flush()
    _renumber_stages_for_tournament(tournament_id)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=stage_id,
        action='stage_deleted',
        payload={'name': db_stage.name, 'type': db_stage.type},
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(None)


def get_stages_for_tournament(
    party_id: PartyID, tournament_id: TournamentID
) -> list[Stage]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return []

    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()
    return [
        _db_stage_to_model_with_effective_status(
            item, tournament_status=db_tournament.status
        )
        for item in db_stages
    ]


def publish_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[Tournament, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    stages = get_stages_for_tournament(party_id, tournament_id)
    participants = get_participants_for_tournament(party_id, tournament_id)
    team_size_validation_result = _validate_bracket_ready_team_sizes(
        tournament, participants
    )
    if team_size_validation_result.is_err():
        return Err(team_size_validation_result.unwrap_err())

    validation_result = domain_service.validate_publishable(
        tournament, stages, participants
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    db_tournament.status = TournamentStatus.live.value
    db_tournament.updated_at = datetime.utcnow()

    first_live_stage_id = _activate_prepared_stages_for_live_tournament(
        tournament_id, stages
    )
    db_ready_matches = _activate_prepared_matches_for_live_tournament(
        tournament_id
    )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_published',
        payload={},
        created_at=datetime.utcnow(),
    )
    _append_notifications_for_tournament(
        tournament_id,
        actor_user_id=initiator.id,
        kind='tournament_live',
        payload={
            'slug': db_tournament.slug,
            'url': _build_site_tournament_overview_path(db_tournament.slug),
        },
    )
    for db_match in db_ready_matches:
        _enqueue_match_ready_notifications(db_match)

    db.session.commit()

    _sync_discord_thread_for_tournament(db_tournament)

    return Ok(_db_tournament_to_model(db_tournament))


def close_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[Tournament, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status == TournamentStatus.closed.value:
        return Err('Tournament is already closed.')

    if db_tournament.status == TournamentStatus.canceled.value:
        return Err('Canceled tournaments cannot be closed.')

    db_tournament.status = TournamentStatus.closed.value
    db_tournament.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_closed',
        payload={},
        created_at=datetime.utcnow(),
    )
    _append_notifications_for_tournament(
        tournament_id,
        actor_user_id=initiator.id,
        kind='tournament_closed',
        payload={
            'slug': db_tournament.slug,
            'url': _build_site_tournament_overview_path(db_tournament.slug),
        },
    )

    db.session.commit()

    enqueue_discord_event(
        party_id,
        tournament_id,
        event_name='tournament_finished',
        payload=_build_discord_tournament_finished_payload(db_tournament),
    )
    return Ok(_db_tournament_to_model(db_tournament))


def cancel_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[Tournament, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status == TournamentStatus.closed.value:
        return Err('Closed tournaments cannot be canceled.')

    if db_tournament.status == TournamentStatus.canceled.value:
        return Err('Tournament is already canceled.')

    db_tournament.status = TournamentStatus.canceled.value
    db_tournament.registration_open = False
    db_tournament.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_canceled',
        payload={},
        created_at=datetime.utcnow(),
    )
    _append_notifications_for_tournament(
        tournament_id,
        actor_user_id=initiator.id,
        kind='tournament_canceled',
        payload={
            'slug': db_tournament.slug,
            'url': _build_site_tournament_overview_path(db_tournament.slug),
        },
    )

    db.session.commit()
    enqueue_discord_event(
        party_id,
        tournament_id,
        event_name='tournament_canceled',
        payload={'slug': db_tournament.slug},
    )

    return Ok(_db_tournament_to_model(db_tournament))


def send_manual_tournament_notification(
    party_id: PartyID,
    tournament_id: TournamentID,
    initiator: User,
    *,
    title: str,
    body: str,
    target_url: str | None = None,
) -> Result[ManualNotificationDispatchResult, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')
    if not is_browser_push_enabled_for_party(party_id):
        return Err('Browser notifications are disabled.')

    title = title.strip()
    body = body.strip()
    target_url = (target_url or '').strip() or None

    if not title:
        return Err('A title is required.')
    if not body:
        return Err('A message is required.')
    if target_url is not None and not target_url.startswith('/'):
        return Err('Target URL must be relative and start with /.')

    recipients, subscription_count = (
        _get_active_browser_push_subscription_recipients_for_tournament(
            party_id, tournament_id
        )
    )

    now = datetime.utcnow()
    for user_id in recipients:
        _append_notification(
            tournament_id=tournament_id,
            user_id=user_id,
            kind='manual_announcement',
            payload={
                'title': title,
                'body': body,
                'url': target_url
                or _build_site_tournament_overview_path(db_tournament.slug),
            },
            created_at=now,
        )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='manual_notification_sent',
        payload={
            'title': title,
            'body': body,
            'target_url': target_url,
            'recipient_user_count': len(recipients),
            'subscription_count': subscription_count,
        },
        created_at=now,
    )

    enqueue_discord_event(
        party_id,
        tournament_id,
        event_name='manual_announcement',
        payload={
            'title': title,
            'body': body,
            'url': target_url
            or _build_site_tournament_overview_path(db_tournament.slug),
        },
    )

    db.session.commit()
    return Ok(
        ManualNotificationDispatchResult(
            recipient_user_count=len(recipients),
            subscription_count=subscription_count,
        )
    )


def unpublish_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[Tournament, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.live.value:
        return Err('Only live tournaments can be moved back to draft.')

    has_reported_results = (
        db.session.scalar(
            select(
                select(DbNetsessionTourneyMatchResult.id)
                .join(
                    DbNetsessionTourneyMatch,
                    DbNetsessionTourneyMatchResult.match_id
                    == DbNetsessionTourneyMatch.id,
                )
                .filter(DbNetsessionTourneyMatch.tournament_id == tournament_id)
                .filter(
                    DbNetsessionTourneyMatchResult.submitted_by_user_id.is_not(
                        None
                    )
                )
                .exists()
            )
        )
        or False
    )
    if has_reported_results:
        return Err(
            'Tournament cannot be moved back to draft after match results have been reported.'
        )

    db_tournament.status = TournamentStatus.draft.value
    db_tournament.updated_at = datetime.utcnow()

    db_live_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyStage.status == StageStatus.live.value)
    ).all()
    for db_stage in db_live_stages:
        db_stage.status = StageStatus.draft.value

    _demote_prepared_matches_for_draft_tournament(tournament_id)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_unpublished',
        payload={'live_stage_count': len(db_live_stages)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(_db_tournament_to_model(db_tournament))


def delete_tournament(
    party_id: PartyID, tournament_id: TournamentID, initiator: User
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    stage_ids = db.session.scalars(
        select(DbNetsessionTourneyStage.id).filter_by(tournament_id=tournament_id)
    ).all()
    for stage_id in stage_ids:
        _delete_stage_matches(stage_id)

    db.session.execute(
        delete(DbNetsessionTourneyStage).filter_by(tournament_id=tournament_id)
    )

    participant_ids = db.session.scalars(
        select(DbNetsessionTourneyParticipant.id).filter_by(
            tournament_id=tournament_id
        )
    ).all()
    if participant_ids:
        db.session.execute(
            delete(DbNetsessionTourneyTeamMember).filter(
                DbNetsessionTourneyTeamMember.participant_id.in_(participant_ids)
            )
        )

    db.session.execute(
        delete(DbNetsessionTourneyParticipant).filter_by(
            tournament_id=tournament_id
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyNotification).filter_by(
            tournament_id=tournament_id
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyDiscordOutbox).filter_by(
            tournament_id=tournament_id
        )
    )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='tournament_deleted',
        payload={'slug': db_tournament.slug, 'title': db_tournament.title},
        created_at=datetime.utcnow(),
    )

    db.session.delete(db_tournament)
    db.session.commit()

    return Ok(None)


def register_user(
    party_id: PartyID, tournament_id: TournamentID, user: User
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.registration_mode in {
        RegistrationMode.team_captain_managed,
        RegistrationMode.team_preformed_only,
    }:
        return Err(
            'Dieses Turnier nutzt Team-Anmeldungen. Bitte erstelle ein Team oder trete einem Team bei.'
        )

    validation_result = domain_service.validate_registration_open(
        tournament, datetime.utcnow()
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    ticket_validation_result = _validate_user_uses_ticket_for_party(
        user.id, party_id
    )
    if ticket_validation_result.is_err():
        return Err(ticket_validation_result.unwrap_err())

    if _is_user_already_active_participant(tournament_id, user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    active_participant_count = count_active_participants_for_tournament(
        party_id, tournament_id
    )
    if _is_tournament_full(tournament, active_participant_count):
        return Err('Das Turnier ist voll.')

    charge_result = _charge_coins_for_tournament_registration(
        party_id,
        tournament,
        user.id,
        created_by_user_id=user.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    registration = db.session.scalar(
        select(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id, user_id=user.id
        )
    )
    if registration is None:
        db.session.add(
            DbNetsessionTourneyRegistration(
                RegistrationID(generate_uuid7()),
                tournament_id,
                user.id,
                RegistrationState.registered,
                now,
            )
        )
    else:
        registration.state = RegistrationState.registered.value

    if tournament.registration_mode in {
        RegistrationMode.solo,
        RegistrationMode.mixed,
    }:
        participant_type = ParticipantType.user
        participant_status = ParticipantStatus.ready
    else:
        participant_type = ParticipantType.team
        participant_status = ParticipantStatus.forming
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        participant_type,
        user.screen_name or str(user.id),
        now,
        user_id=user.id if participant_type == ParticipantType.user else None,
        manager_user_id=user.id,
        status=participant_status,
        invite_code=(
            _generate_unique_invite_code_for_tournament(tournament_id)
            if participant_type == ParticipantType.team
            else None
        ),
    )
    db.session.add(db_participant)

    if participant_type == ParticipantType.team:
        db.session.add(
            DbNetsessionTourneyTeamMember(
                TeamMemberID(generate_uuid7()),
                db_participant.id,
                user.id,
                TeamMemberRole.captain,
                now,
            )
        )

    _append_notification(
        tournament_id=tournament_id,
        user_id=user.id,
        kind='registration_created',
        payload={'participant_id': str(db_participant.id)},
        created_at=now,
    )
    _append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='participant_registered',
        payload={'tournament_id': str(tournament_id)},
        created_at=now,
    )

    db.session.commit()
    return Ok(_db_participant_to_model(db_participant))


def create_team_for_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    user: User,
    team_name: str,
    *,
    team_logo_url: str | None = None,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Dieses Turnier erlaubt nur Solo-Anmeldungen.')

    validation_result = domain_service.validate_registration_open(
        tournament, datetime.utcnow()
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    ticket_validation_result = _validate_user_uses_ticket_for_party(
        user.id, party_id
    )
    if ticket_validation_result.is_err():
        return Err(ticket_validation_result.unwrap_err())

    if _is_user_already_active_participant(tournament_id, user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    active_participant_count = count_active_participants_for_tournament(
        party_id, tournament_id
    )
    if _is_tournament_full(tournament, active_participant_count):
        return Err('Das Turnier ist voll.')

    charge_result = _charge_coins_for_tournament_registration(
        party_id,
        tournament,
        user.id,
        created_by_user_id=user.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    invite_code = _generate_unique_invite_code_for_tournament(tournament_id)
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        ParticipantType.team,
        team_name.strip(),
        now,
        logo_url=team_logo_url.strip() if team_logo_url else None,
        manager_user_id=user.id,
        status=ParticipantStatus.forming,
        invite_code=invite_code,
    )
    db.session.add(db_participant)
    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            db_participant.id,
            user.id,
            TeamMemberRole.captain,
            now,
        )
    )

    _append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_created',
        payload={'invite_code': invite_code},
        created_at=now,
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def update_managed_team_for_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    team_name: str,
    *,
    team_logo_url: str | None = None,
    replace_logo: bool = False,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status not in {TournamentStatus.draft, TournamentStatus.live}:
        return Err('Team management is not available right now.')

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team not found or not manageable by this user.')

    if tournament.status == TournamentStatus.live:
        if not replace_logo:
            return Err(
                'While tournament is live, only the team logo can be updated.'
            )

        db_participant.logo_url = (
            team_logo_url.strip() if team_logo_url else None
        )

        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='participant',
            object_id=participant_id,
            action='team_logo_updated_by_captain_while_live',
            payload={
                'logo_url': db_participant.logo_url,
                'replace_logo': replace_logo,
            },
            created_at=datetime.utcnow(),
        )
        db.session.commit()

        return Ok(_db_participant_to_model(db_participant))

    team_name_clean = team_name.strip()
    if not team_name_clean:
        return Err('Ein Teamname ist erforderlich.')

    db_participant.name = team_name_clean
    if replace_logo:
        db_participant.logo_url = (
            team_logo_url.strip() if team_logo_url else None
        )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_updated_by_captain',
        payload={
            'team_name': team_name_clean,
            'logo_url': db_participant.logo_url,
            'replace_logo': replace_logo,
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def join_team_by_invite_code(
    party_id: PartyID,
    tournament_id: TournamentID,
    invite_code: str,
    user: User,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Dieses Turnier erlaubt nur Solo-Anmeldungen.')

    validation_result = domain_service.validate_registration_open(
        tournament, datetime.utcnow()
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    ticket_validation_result = _validate_user_uses_ticket_for_party(
        user.id, party_id
    )
    if ticket_validation_result.is_err():
        return Err(ticket_validation_result.unwrap_err())

    if _is_user_already_active_participant(tournament_id, user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant).filter_by(
            tournament_id=tournament_id,
            invite_code=invite_code.strip(),
            type=ParticipantType.team.value,
        )
    )
    if db_participant is None:
        return Err('Unbekannter Invite-Code.')
    if db_participant.status not in ACTIVE_PARTICIPANT_STATUS_VALUES:
        return Err('This team is not open for joining.')
    max_team_member_count = _get_max_team_member_count(tournament)
    if max_team_member_count is not None:
        member_count = db.session.scalar(
            select(db.func.count(DbNetsessionTourneyTeamMember.id)).filter_by(
                participant_id=db_participant.id
            )
        )
    if int(member_count or 0) >= max_team_member_count:
        return Err('This team is already full.')

    if tournament.coin_charge_mode == CoinChargeMode.all_members:
        charge_result = _charge_coins_for_tournament_registration(
            party_id,
            tournament,
            user.id,
            created_by_user_id=user.id,
        )
        if charge_result.is_err():
            return Err(charge_result.unwrap_err())

    registration = db.session.scalar(
        select(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id, user_id=user.id
        )
    )
    if registration is None:
        db.session.add(
            DbNetsessionTourneyRegistration(
                RegistrationID(generate_uuid7()),
                tournament_id,
                user.id,
                RegistrationState.registered,
                datetime.utcnow(),
            )
        )
    else:
        registration.state = RegistrationState.registered.value

    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            db_participant.id,
            user.id,
            TeamMemberRole.player,
            datetime.utcnow(),
        )
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def add_user_participant_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_user: User,
    initiator: User,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Participant management is only possible while tournament is in draft.'
        )
    if tournament.registration_mode not in {
        RegistrationMode.solo,
        RegistrationMode.mixed,
    }:
        return Err(
            'Direct user adding is only available for solo or mixed registration mode.'
        )
    if _is_user_already_active_participant(tournament_id, participant_user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    if tournament.participant_limit is not None:
        active_count = count_active_participants_for_tournament(
            party_id, tournament_id
        )
        if active_count >= tournament.participant_limit:
            return Err('Das Turnier ist voll.')

    charge_result = _charge_coins_for_tournament_registration(
        party_id,
        tournament,
        participant_user.id,
        created_by_user_id=initiator.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        ParticipantType.user,
        participant_user.screen_name or str(participant_user.id),
        now,
        user_id=participant_user.id,
        manager_user_id=participant_user.id,
        status=ParticipantStatus.ready,
    )
    db.session.add(db_participant)
    _ensure_registration_is_registered(tournament_id, participant_user.id)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=db_participant.id,
        action='participant_added_by_admin',
        payload={'user_id': str(participant_user.id)},
        created_at=now,
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def create_team_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    team_name: str,
    captain_user: User,
    initiator: User,
    *,
    team_logo_url: str | None = None,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Participant management is only possible while tournament is in draft.'
        )
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Team management is not available for solo registration mode.')
    if _is_user_already_active_participant(tournament_id, captain_user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    if tournament.participant_limit is not None:
        active_count = count_active_participants_for_tournament(
            party_id, tournament_id
        )
        if active_count >= tournament.participant_limit:
            return Err('Das Turnier ist voll.')

    charge_result = _charge_coins_for_tournament_registration(
        party_id,
        tournament,
        captain_user.id,
        created_by_user_id=initiator.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    invite_code = _generate_unique_invite_code_for_tournament(tournament_id)
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        ParticipantType.team,
        team_name.strip(),
        now,
        logo_url=team_logo_url.strip() if team_logo_url else None,
        manager_user_id=captain_user.id,
        status=ParticipantStatus.forming,
        invite_code=invite_code,
    )
    db.session.add(db_participant)
    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            db_participant.id,
            captain_user.id,
            TeamMemberRole.captain,
            now,
        )
    )
    _ensure_registration_is_registered(tournament_id, captain_user.id)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_created_by_admin',
        payload={'captain_user_id': str(captain_user.id)},
        created_at=now,
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def add_team_member_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user: User,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Participant management is only possible while tournament is in draft.'
        )
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Team management is not available for solo registration mode.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            id=participant_id,
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is None:
        return Err('Unknown team.')

    if _is_user_already_active_participant(tournament_id, member_user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    max_team_member_count = _get_max_team_member_count(tournament)
    if max_team_member_count is not None:
        member_count = db.session.scalar(
            select(db.func.count(DbNetsessionTourneyTeamMember.id)).filter_by(
                participant_id=participant_id
            )
        )
        if int(member_count or 0) >= max_team_member_count:
            return Err('This team is already full.')

    if tournament.coin_charge_mode == CoinChargeMode.all_members:
        charge_result = _charge_coins_for_tournament_registration(
            party_id,
            tournament,
            member_user.id,
            created_by_user_id=initiator.id,
        )
        if charge_result.is_err():
            return Err(charge_result.unwrap_err())

    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            participant_id,
            member_user.id,
            TeamMemberRole.player,
            datetime.utcnow(),
        )
    )
    _ensure_registration_is_registered(tournament_id, member_user.id)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_member_added_by_admin',
        payload={'member_user_id': str(member_user.id)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def remove_team_member_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user_id: UserID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Participant management is only possible while tournament is in draft.'
        )

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            id=participant_id,
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is None:
        return Err('Unknown team.')

    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            user_id=member_user_id,
        )
    )
    if db_member is None:
        return Err('Unknown team member.')
    if db_member.role == TeamMemberRole.captain.value:
        return Err('Captain cannot be removed from team.')

    db.session.delete(db_member)
    _set_registration_state_for_user(
        tournament_id, member_user_id, RegistrationState.canceled
    )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_member_removed_by_admin',
        payload={'member_user_id': str(member_user_id)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def assign_team_captain_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user_id: UserID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Participant management is only possible while tournament is in draft.'
        )
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Team management is not available for solo registration mode.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            id=participant_id,
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is None:
        return Err('Unknown team.')

    if db_participant.manager_user_id == member_user_id:
        return Ok(None)

    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            user_id=member_user_id,
        )
    )
    if db_member is None:
        return Err('Unknown team member.')

    db_current_captain_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            role=TeamMemberRole.captain.value,
        )
    )
    if db_current_captain_member is None:
        return Err('Current captain could not be determined.')

    old_captain_user_id = db_participant.manager_user_id
    db_current_captain_member.role = TeamMemberRole.player.value
    db_member.role = TeamMemberRole.captain.value
    db_participant.manager_user_id = member_user_id

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_captain_changed_by_admin',
        payload={
            'old_captain_user_id': (
                str(old_captain_user_id) if old_captain_user_id else None
            ),
            'new_captain_user_id': str(member_user_id),
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def find_managed_team_for_user(
    party_id: PartyID, tournament_id: TournamentID, user_id: UserID
) -> Participant | None:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return None

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
            manager_user_id=user_id,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is None:
        return None

    return _db_participant_to_model(db_participant)


def get_team_invite_code_for_manager(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    manager_user_id: UserID,
) -> Result[str, str]:
    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, manager_user_id
    )
    if db_participant is None:
        return Err('Team not found or not manageable by this user.')

    if not db_participant.invite_code:
        return Err('No invite code available for this team.')

    return Ok(db_participant.invite_code)


def regenerate_team_invite_code_for_manager(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
) -> Result[str, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Team management is only possible while tournament is in draft.'
        )

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team not found or not manageable by this user.')

    invite_code = _generate_unique_invite_code_for_tournament(tournament_id)
    db_participant.invite_code = invite_code

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_invite_code_regenerated',
        payload={},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(invite_code)


def add_team_member_by_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user: User,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Team management is only possible while tournament is in draft.'
        )

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team not found or not manageable by this user.')

    ticket_validation_result = _validate_user_uses_ticket_for_party(
        member_user.id, party_id
    )
    if ticket_validation_result.is_err():
        return Err(ticket_validation_result.unwrap_err())

    if _is_user_already_active_participant(tournament_id, member_user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    max_team_member_count = _get_max_team_member_count(tournament)
    if max_team_member_count is not None:
        member_count = db.session.scalar(
            select(db.func.count(DbNetsessionTourneyTeamMember.id)).filter_by(
                participant_id=participant_id
            )
        )
        if int(member_count or 0) >= max_team_member_count:
            return Err('This team is already full.')

    if tournament.coin_charge_mode == CoinChargeMode.all_members:
        charge_result = _charge_coins_for_tournament_registration(
            party_id,
            tournament,
            member_user.id,
            created_by_user_id=initiator.id,
        )
        if charge_result.is_err():
            return Err(charge_result.unwrap_err())

    registration = db.session.scalar(
        select(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id,
            user_id=member_user.id,
        )
    )
    if registration is None:
        db.session.add(
            DbNetsessionTourneyRegistration(
                RegistrationID(generate_uuid7()),
                tournament_id,
                member_user.id,
                RegistrationState.registered,
                datetime.utcnow(),
            )
        )
    else:
        registration.state = RegistrationState.registered.value

    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            participant_id,
            member_user.id,
            TeamMemberRole.player,
            datetime.utcnow(),
        )
    )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_member_added_by_captain',
        payload={'member_user_id': str(member_user.id)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def set_managed_team_ready_state(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    *,
    ready: bool,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status not in {TournamentStatus.draft, TournamentStatus.live}:
        return Err(
            'Team management is not available right now.'
        )

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team not found or not manageable by this user.')

    if ready and tournament.team_size is not None:
        member_count = db.session.scalar(
            select(db.func.count(DbNetsessionTourneyTeamMember.id)).filter_by(
                participant_id=participant_id
            )
        )
        if int(member_count or 0) != tournament.team_size:
            return Err(
                f'Team is not complete. Required team size: {tournament.team_size}.'
            )

    db_participant.status = (
        ParticipantStatus.ready.value
        if ready
        else ParticipantStatus.forming.value
    )

    _refresh_match_states_for_participant_readiness(
        db_tournament, participant_id
    )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_ready_state_set_by_captain',
        payload={'ready': ready},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def _refresh_match_states_for_participant_readiness(
    db_tournament: DbNetsessionTourneyTournament,
    participant_id: ParticipantID,
) -> None:
    affected_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .join(
            DbNetsessionTourneyMatchSlot,
            DbNetsessionTourneyMatch.id == DbNetsessionTourneyMatchSlot.match_id,
        )
        .filter(DbNetsessionTourneyMatch.tournament_id == db_tournament.id)
        .filter(DbNetsessionTourneyMatchSlot.participant_id == participant_id)
        .filter(
            DbNetsessionTourneyMatch.state.in_(
                [MatchState.pending.value, MatchState.ready.value]
            )
        )
    ).all()
    if not affected_matches:
        return

    match_ids = [db_match.id for db_match in affected_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        _get_participant_status_value_by_participant_id_for_slots(db_slots)
    )
    now = datetime.utcnow()
    for db_match in affected_matches:
        previous_state = MatchState(db_match.state)
        next_state = _calculate_match_state_for_slots(
            tournament_status=db_tournament.status,
            db_match_slots=slots_by_match_id.get(db_match.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        )
        if next_state == previous_state:
            continue

        db_match.state = next_state.value
        db_match.updated_at = now

        if previous_state != MatchState.ready and next_state == MatchState.ready:
            _enqueue_match_ready_notifications(db_match)


def assign_team_captain_by_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user_id: UserID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Team management is only possible while tournament is in draft.'
        )

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team not found or not manageable by this user.')

    if db_participant.manager_user_id == member_user_id:
        return Ok(None)

    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            user_id=member_user_id,
        )
    )
    if db_member is None:
        return Err('Unknown team member.')

    db_current_captain_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            role=TeamMemberRole.captain.value,
        )
    )
    if db_current_captain_member is None:
        return Err('Current captain could not be determined.')

    db_current_captain_member.role = TeamMemberRole.player.value
    db_member.role = TeamMemberRole.captain.value
    db_participant.manager_user_id = member_user_id

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_captain_changed_by_captain',
        payload={
            'old_captain_user_id': str(initiator.id),
            'new_captain_user_id': str(member_user_id),
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def remove_team_member_by_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user_id: UserID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Team management is only possible while tournament is in draft.'
        )

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team not found or not manageable by this user.')

    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            user_id=member_user_id,
        )
    )
    if db_member is None:
        return Err('Unknown team member.')
    if db_member.role == TeamMemberRole.captain.value:
        return Err('Captain cannot be removed from own team.')

    db.session.delete(db_member)
    _set_registration_state_for_user(
        tournament_id, member_user_id, RegistrationState.canceled
    )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_member_removed_by_captain',
        payload={'member_user_id': str(member_user_id)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def deregister_user(
    party_id: PartyID, tournament_id: TournamentID, user: User
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status == TournamentStatus.closed:
        return Err(
            'Eine Abmeldung ist nicht mehr möglich, da das Turnier geschlossen ist.'
        )

    if tournament.status == TournamentStatus.canceled:
        return Err(
            'Eine Abmeldung ist nicht mehr möglich, da das Turnier abgesagt ist.'
        )

    if tournament.status != TournamentStatus.draft:
        return Err(
            'Eine Abmeldung ist nicht mehr möglich, da das Turnier bereits live ist.'
        )

    db_participant = _find_db_active_participant_for_user(
        tournament_id, user.id
    )
    if db_participant is None:
        return Err('Du bist für dieses Turnier nicht angemeldet.')

    now = datetime.utcnow()

    # Solo participant: drop the entry and cancel registration.
    if db_participant.type == ParticipantType.user.value:
        db_participant.status = ParticipantStatus.dropped.value
        _set_registration_state_for_user(
            tournament_id, user.id, RegistrationState.canceled
        )
        _refund_coins_for_tournament_registration_if_available(
            party_id,
            tournament,
            user.id,
            created_by_user_id=user.id,
        )
        _append_audit_log(
            actor_user_id=user.id,
            object_type='participant',
            object_id=db_participant.id,
            action='participant_deregistered',
            payload={'reason_code': 'self_deregister'},
            created_at=now,
        )
        db.session.commit()
        return Ok(None)

    # Team participant.
    if db_participant.manager_user_id == user.id:
        # Captain leaving: drop whole team from this tournament.
        db_participant.status = ParticipantStatus.dropped.value
        member_user_ids = _get_team_member_user_ids_for_participant(
            db_participant.id
        )
        for member_user_id in member_user_ids:
            _set_registration_state_for_user(
                tournament_id, member_user_id, RegistrationState.canceled
            )
            if (
                tournament.coin_charge_mode == CoinChargeMode.all_members
                or member_user_id == user.id
            ):
                _refund_coins_for_tournament_registration_if_available(
                    party_id,
                    tournament,
                    member_user_id,
                    created_by_user_id=user.id,
                )
        _append_audit_log(
            actor_user_id=user.id,
            object_type='participant',
            object_id=db_participant.id,
            action='team_deregistered_by_captain',
            payload={'reason_code': 'captain_deregister'},
            created_at=now,
        )
        db.session.commit()
        return Ok(None)

    # Non-captain team member: remove membership only.
    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=db_participant.id,
            user_id=user.id,
        )
    )
    if db_member is None:
        return Err('Du bist für dieses Turnier nicht angemeldet.')

    db.session.delete(db_member)
    _set_registration_state_for_user(
        tournament_id, user.id, RegistrationState.canceled
    )
    if tournament.coin_charge_mode == CoinChargeMode.all_members:
        _refund_coins_for_tournament_registration_if_available(
            party_id,
            tournament,
            user.id,
            created_by_user_id=user.id,
        )
    _append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_member_left',
        payload={'member_user_id': str(user.id)},
        created_at=now,
    )
    db.session.commit()
    return Ok(None)


def remove_participant_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    *,
    comment: str,
) -> Result[Participant, str]:
    comment = comment.strip()
    if not comment:
        return Err('A comment is required.')

    dq_result = disqualify_participant(
        party_id,
        tournament_id,
        participant_id,
        initiator,
        reason_code='admin_removed',
        comment=comment,
    )
    if dq_result.is_err():
        return Err(dq_result.unwrap_err())

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant).filter_by(
            id=participant_id,
            tournament_id=tournament_id,
        )
    )
    if db_participant is None:
        return Err('Unknown participant.')

    affected_user_ids = set(_get_team_member_user_ids_for_participant(participant_id))
    if db_participant.user_id is not None:
        affected_user_ids.add(db_participant.user_id)
    if db_participant.manager_user_id is not None:
        affected_user_ids.add(db_participant.manager_user_id)

    for user_id in affected_user_ids:
        _set_registration_state_for_user(
            tournament_id, user_id, RegistrationState.canceled
        )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='participant_removed_by_admin',
        payload={'comment': comment},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(dq_result.unwrap())


def count_active_participants_for_tournament(
    party_id: PartyID, tournament_id: TournamentID
) -> int:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return 0

    count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyParticipant.id))
        .filter_by(tournament_id=tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    return int(count or 0)


def get_active_participant_counts_for_tournaments(
    party_id: PartyID, tournament_ids: set[TournamentID]
) -> dict[TournamentID, int]:
    if not tournament_ids:
        return {}

    rows = db.session.execute(
        select(
            DbNetsessionTourneyParticipant.tournament_id,
            db.func.count(DbNetsessionTourneyParticipant.id),
        )
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyParticipant.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(DbNetsessionTourneyParticipant.tournament_id.in_(tournament_ids))
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
        .group_by(DbNetsessionTourneyParticipant.tournament_id)
    ).all()
    return {tournament_id: int(count) for tournament_id, count in rows}


def get_user_active_participation_tournament_ids(
    party_id: PartyID, tournament_ids: set[TournamentID], user_id: UserID
) -> set[TournamentID]:
    if not tournament_ids:
        return set()

    direct_rows = db.session.scalars(
        select(DbNetsessionTourneyParticipant.tournament_id)
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyParticipant.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(DbNetsessionTourneyParticipant.tournament_id.in_(tournament_ids))
        .filter(DbNetsessionTourneyParticipant.user_id == user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()

    team_rows = db.session.scalars(
        select(DbNetsessionTourneyParticipant.tournament_id)
        .join(
            DbNetsessionTourneyTeamMember,
            DbNetsessionTourneyTeamMember.participant_id
            == DbNetsessionTourneyParticipant.id,
        )
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyParticipant.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(DbNetsessionTourneyParticipant.tournament_id.in_(tournament_ids))
        .filter(DbNetsessionTourneyTeamMember.user_id == user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()

    return set(direct_rows).union(team_rows)


def get_participants_for_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    include_dropped: bool = False,
) -> list[Participant]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return []

    stmt = (
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyParticipant.seed.asc().nullslast(),
            DbNetsessionTourneyParticipant.created_at.asc(),
        )
    )
    if not include_dropped:
        stmt = stmt.filter(
            DbNetsessionTourneyParticipant.status
            != ParticipantStatus.dropped.value
        )

    db_participants = db.session.scalars(stmt).all()
    return [_db_participant_to_model(item) for item in db_participants]


def get_participants_by_ids(
    party_id: PartyID, participant_ids: set[ParticipantID]
) -> dict[ParticipantID, Participant]:
    if not participant_ids:
        return {}

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyParticipant.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
    ).all()
    return {
        item.id: _db_participant_to_model(item)
        for item in db_participants
    }


def get_team_members_for_participants(
    participant_ids: set[ParticipantID],
) -> dict[ParticipantID, list[TeamMember]]:
    if not participant_ids:
        return {}

    db_members = db.session.scalars(
        select(DbNetsessionTourneyTeamMember).filter(
            DbNetsessionTourneyTeamMember.participant_id.in_(participant_ids)
        )
    ).all()

    members_by_participant_id: dict[ParticipantID, list[TeamMember]] = (
        defaultdict(list)
    )
    for db_member in db_members:
        members_by_participant_id[db_member.participant_id].append(
            _db_team_member_to_model(db_member)
        )
    return dict(members_by_participant_id)


def set_participant_seed(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    seed: int,
    initiator: User,
) -> Result[Participant, str]:
    if seed < 1:
        return Err('Seed must be at least 1.')

    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
        .order_by(DbNetsessionTourneyParticipant.created_at.asc())
    ).all()
    db_participants_by_id = {item.id: item for item in db_participants}
    db_participant = db_participants_by_id.get(participant_id)
    if db_participant is None:
        return Err('Unknown participant.')

    active_participant_count = len(db_participants)
    if seed > active_participant_count:
        return Err(
            'Seed must not be higher than the current active participant count.'
        )

    seeded_participants = sorted(
        (
            item
            for item in db_participants
            if item.id != participant_id and item.seed is not None
        ),
        key=lambda item: (item.seed, item.created_at),
    )

    max_assignable_seed = len(seeded_participants) + 1
    if seed > max_assignable_seed:
        return Err(
            'Seeds can only be assigned without gaps. '
            f'The next available manual seed is {max_assignable_seed}.'
        )

    insertion_index = seed - 1
    seeded_participants.insert(insertion_index, db_participant)

    for index, item in enumerate(seeded_participants, start=1):
        item.seed = index

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='participant_seed_set',
        payload={'seed': seed},
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(_db_participant_to_model(db_participant))


def set_participant_status(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    status: ParticipantStatus,
    initiator: User,
) -> Result[Participant, str]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant).filter_by(
            id=participant_id,
            tournament_id=tournament_id,
        )
    )
    if db_participant is None:
        return Err('Unknown participant.')

    db_participant.status = status.value

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='participant_status_set',
        payload={'status': status.value},
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(_db_participant_to_model(db_participant))


def preview_stage_match_generation(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
) -> Result[StageMatchGenerationPreview, str]:
    payload_result = _build_stage_generation_payload(
        party_id,
        tournament_id,
        stage_id,
        require_flatout2_hosts=False,
    )
    if payload_result.is_err():
        return Err(payload_result.unwrap_err())
    payload = payload_result.unwrap()

    round_match_counts: dict[int, int] = defaultdict(int)
    for spec in payload.match_specs:
        round_match_counts[spec.round_no] += 1

    suggested_round_starts_at = _build_round_starts_at_schedule(
        tournament_starts_at=payload.tournament.starts_at,
        stage=payload.stage,
        round_match_counts=round_match_counts,
    )
    display_titles_by_round_no = _build_generation_preview_round_titles_by_round_no(
        payload.stage,
        payload.match_specs,
    )
    preview_participants_by_id = {
        participant.id: participant for participant in payload.participants
    }
    matches_by_round_no: dict[int, list[StageGeneratedMatchPreview]] = (
        defaultdict(list)
    )
    for spec in sorted(payload.match_specs, key=lambda item: (item.round_no, item.match_no)):
        matches_by_round_no[spec.round_no].append(
            StageGeneratedMatchPreview(
                round_no=spec.round_no,
                match_no=spec.match_no,
                participants=[
                    StageMatchGenerationPreviewParticipant(
                        participant_id=slot.participant_id,
                        name=preview_participants_by_id[slot.participant_id].name,
                    )
                    for slot in spec.slots
                    if slot.participant_id is not None
                    and slot.participant_id in preview_participants_by_id
                ],
            )
        )
    rounds = [
        StageRoundGenerationPreview(
            round_no=round_no,
            match_count=round_match_counts[round_no],
            suggested_starts_at=suggested_round_starts_at.get(round_no),
            display_title=display_titles_by_round_no.get(round_no),
        )
        for round_no in sorted(round_match_counts.keys())
    ]

    return Ok(
        StageMatchGenerationPreview(
            stage=payload.stage,
            participant_count=len(payload.participants),
            match_count=len(payload.match_specs),
            rounds=rounds,
            matches_by_round_no=dict(matches_by_round_no),
        )
    )


def _build_generation_preview_round_titles_by_round_no(
    stage: Stage,
    match_specs: list[MatchSpec],
) -> dict[int, str]:
    builder_display_title = str(
        (stage.settings or {}).get('builder_display_title') or ''
    ).strip()
    if builder_display_title:
        round_nos = sorted({spec.round_no for spec in match_specs})
        return {round_no: builder_display_title for round_no in round_nos}

    if stage.type == StageType.ffa_flatout2_single_elimination:
        raw_rounds = (stage.settings or {}).get('flatout2_rounds')
        if isinstance(raw_rounds, list):
            titles_by_round_no: dict[int, str] = {}
            for raw_round in raw_rounds:
                if not isinstance(raw_round, dict):
                    continue
                try:
                    round_no = int(raw_round.get('round_no') or 0)
                except (TypeError, ValueError):
                    continue
                if round_no < 1:
                    continue
                display_title = str(
                    raw_round.get('display_title')
                    or raw_round.get('title')
                    or ''
                ).strip()
                if display_title:
                    titles_by_round_no[round_no] = display_title
            if titles_by_round_no:
                return titles_by_round_no

        round_nos = sorted({spec.round_no for spec in match_specs})
        try:
            total_round_count = int((stage.settings or {}).get('round_count') or 0)
        except (TypeError, ValueError):
            total_round_count = 0

        return {
            round_no: (
                'Finale'
                if total_round_count > 0 and round_no == total_round_count
                else f'Runde {round_no}'
            )
            for round_no in round_nos
        }

    if stage.type not in {
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return {}

    specs_by_match_no = {
        spec.match_no: spec
        for spec in sorted(match_specs, key=lambda item: (item.round_no, item.match_no))
    }
    bracket_by_match_no: dict[int, str] = {}

    changed = True
    while changed:
        changed = False
        for spec in specs_by_match_no.values():
            incoming = [
                (slot.source_match_no, slot.source_outcome)
                for slot in spec.slots
                if slot.source_match_no is not None
            ]
            bracket = bracket_by_match_no.get(spec.match_no)
            next_bracket = bracket
            if not incoming:
                next_bracket = 'WB'
            else:
                source_brackets = {
                    bracket_by_match_no.get(source_match_no)
                    for source_match_no, _ in incoming
                }
                source_brackets.discard(None)

                if 'GF' in source_brackets:
                    next_bracket = 'GF'
                elif any(_is_loser_source_outcome(outcome) for _, outcome in incoming):
                    next_bracket = 'LB'
                elif source_brackets == {'WB'}:
                    next_bracket = 'WB'
                elif source_brackets == {'LB'}:
                    next_bracket = 'LB'
                elif source_brackets == {'WB', 'LB'}:
                    next_bracket = 'GF'

            if next_bracket != bracket:
                bracket_by_match_no[spec.match_no] = next_bracket
                changed = True

    round_nos_by_bracket: dict[str, list[int]] = defaultdict(list)
    brackets_by_round_no: dict[int, set[str]] = defaultdict(set)
    for spec in specs_by_match_no.values():
        bracket = bracket_by_match_no.get(spec.match_no)
        if bracket is None:
            continue
        if spec.round_no not in round_nos_by_bracket[bracket]:
            round_nos_by_bracket[bracket].append(spec.round_no)
        brackets_by_round_no[spec.round_no].add(bracket)

    title_by_round_no: dict[int, str] = {}

    wb_titles = {
        round_no: _get_generation_preview_winner_round_title(
            index, len(round_nos_by_bracket['WB'])
        )
        for index, round_no in enumerate(sorted(round_nos_by_bracket['WB']))
    }
    lb_titles = {
        round_no: _get_generation_preview_loser_round_title(
            index, len(round_nos_by_bracket['LB'])
        )
        for index, round_no in enumerate(sorted(round_nos_by_bracket['LB']))
    }
    gf_titles = {}
    sorted_gf_round_nos = sorted(round_nos_by_bracket['GF'])
    for index, round_no in enumerate(sorted_gf_round_nos):
        gf_titles[round_no] = (
            'Grand Final'
            if index == 0
            else 'Double Grand Final'
            if index == 1
            else f'Grand Final {index + 1}'
        )

    for round_no in sorted(brackets_by_round_no):
        parts = []
        if round_no in wb_titles:
            parts.append(wb_titles[round_no])
        if round_no in lb_titles:
            parts.append(lb_titles[round_no])
        if round_no in gf_titles:
            parts.append(gf_titles[round_no])
        if parts:
            title_by_round_no[round_no] = ' + '.join(parts)

    return title_by_round_no


def _is_loser_source_outcome(outcome: SourceOutcome | str | None) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'


def _get_generation_preview_winner_round_title(
    round_index: int, round_count: int
) -> str:
    if round_count <= 1 or round_index == round_count - 1:
        return 'Winner Bracket Final'
    if round_index == round_count - 2:
        return 'Winner Bracket Semi-Final'
    return f'Winner Bracket Round {round_index + 1}'


def _get_generation_preview_loser_round_title(
    round_index: int, round_count: int
) -> str:
    if round_count <= 1 or round_index == round_count - 1:
        return 'Loser Bracket Final'
    if round_count >= 3 and round_index == round_count - 2:
        return 'Loser Bracket Semi-Final'
    return f'Loser Bracket Round {round_index + 1}'


def get_stage_generation_participants(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
) -> Result[list[Participant], str]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unknown stage.')

    stage = _db_stage_to_model(db_stage)
    return _select_generation_participants_for_stage(
        party_id, tournament_id, stage
    )


def set_stage_generation_seeds(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    auto_seed_participant_ids: list[ParticipantID],
    manual_seed_by_participant_id: dict[ParticipantID, int],
    initiator: User,
) -> Result[list[Participant], str]:
    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unknown stage.')

    stage = _db_stage_to_model(db_stage)
    selected_participants_result = get_stage_generation_participants(
        party_id, tournament_id, stage_id
    )
    if selected_participants_result.is_err():
        return Err(selected_participants_result.unwrap_err())

    selected_participants = selected_participants_result.unwrap()
    if len(selected_participants) < 2:
        return Err('Not enough participants for seed assignment.')

    selected_participants_by_id = {
        participant.id: participant for participant in selected_participants
    }
    selected_participant_ids = set(selected_participants_by_id.keys())
    if set(auto_seed_participant_ids) != selected_participant_ids:
        return Err(
            'Die Teilnehmerliste hat sich geändert. Bitte die Seeding-Seite neu laden.'
        )

    if _is_stage_builder_v1_main_stage_with_locked_qualifier_seeding(stage):
        if manual_seed_by_participant_id:
            return Err(
                'Seeding für dieses Hauptturnier wird automatisch aus den abgeschlossenen Vorrunden übernommen und kann nicht manuell angepasst werden.'
            )

        final_participant_ids = [
            participant.id for participant in selected_participants
        ]
    else:
        normalized_manual_seed_by_participant_id = {
            participant_id: seed
            for participant_id, seed in manual_seed_by_participant_id.items()
            if participant_id in selected_participant_ids
        }
        manual_seed_values = sorted(
            normalized_manual_seed_by_participant_id.values()
        )
        expected_manual_seed_values = list(
            range(1, len(normalized_manual_seed_by_participant_id) + 1)
        )
        if manual_seed_values != expected_manual_seed_values:
            return Err(
                'Manuelle Seeds müssen lückenlos bei 1 beginnen und dürfen keine Duplikate enthalten.'
            )

        manual_prefix_participant_ids = [
            participant_id
            for participant_id, _seed in sorted(
                normalized_manual_seed_by_participant_id.items(),
                key=lambda item: item[1],
            )
        ]
        remaining_auto_seed_participant_ids = [
            participant_id
            for participant_id in auto_seed_participant_ids
            if participant_id not in normalized_manual_seed_by_participant_id
        ]
        final_participant_ids = (
            manual_prefix_participant_ids + remaining_auto_seed_participant_ids
        )

    normalized_manual_seed_by_participant_id = {
        participant_id: seed
        for participant_id, seed in manual_seed_by_participant_id.items()
        if participant_id in selected_participant_ids
    }

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyParticipant.id.in_(final_participant_ids))
    ).all()
    db_participants_by_id = {
        participant.id: participant for participant in db_participants
    }

    now = datetime.utcnow()
    for seed, participant_id in enumerate(final_participant_ids, start=1):
        db_participant = db_participants_by_id.get(participant_id)
        if db_participant is None:
            return Err('A participant could not be found for seed assignment.')
        db_participant.seed = seed

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=stage_id,
        action='stage_generation_seeds_set',
        payload={
            'participant_count': len(final_participant_ids),
            'manual_seed_count': len(normalized_manual_seed_by_participant_id),
        },
        created_at=now,
    )

    db.session.commit()

    return Ok(
        [
            selected_participants_by_id[participant_id]
            for participant_id in final_participant_ids
        ]
    )


def generate_stage_matches(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    initiator: User,
    *,
    correlation_id: str | None = None,
    round_starts_at_by_round_no: dict[int, datetime] | None = None,
    stage_settings_patch: dict[str, Any] | None = None,
    match_settings_by_round_and_match_no: (
        dict[tuple[int, int], dict[str, Any]] | None
    ) = None,
) -> Result[list[Match], str]:
    payload_result = _build_stage_generation_payload(
        party_id,
        tournament_id,
        stage_id,
        stage_settings_override=stage_settings_patch,
    )
    if payload_result.is_err():
        return Err(payload_result.unwrap_err())
    payload = payload_result.unwrap()

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unknown stage.')

    if (
        _is_stage_builder_v1_preliminary_stage(payload.stage)
        and payload.stage.type == StageType.round_robin_groups
    ):
        return _materialize_round_robin_builder_group_stages(
            party_id=party_id,
            tournament_id=tournament_id,
            db_stage=db_stage,
            payload=payload,
            initiator=initiator,
            correlation_id=correlation_id,
            round_starts_at_by_round_no=round_starts_at_by_round_no,
        )

    if stage_settings_patch:
        merged_stage_settings = dict(db_stage.settings_json or {})
        merged_stage_settings.update(stage_settings_patch)
        db_stage.settings_json = merged_stage_settings
        payload = replace(
            payload,
            stage=replace(payload.stage, settings=merged_stage_settings),
        )

    if payload.replace_existing_matches:
        _delete_stage_matches(stage_id)
    matches = _persist_generated_matches(
        tournament_id=tournament_id,
        stage_id=stage_id,
        specs=payload.match_specs,
        match_settings_by_round_and_match_no=match_settings_by_round_and_match_no,
    )
    _schedule_generated_matches(
        tournament_starts_at=payload.tournament.starts_at,
        stage=payload.stage,
        match_ids=[match.id for match in matches],
        round_starts_at_by_round_no=round_starts_at_by_round_no,
    )

    stage_started_now = False
    if (
        payload.tournament.status == TournamentStatus.live
        and db_stage.status == StageStatus.draft.value
    ):
        db_stage.status = StageStatus.live.value
        stage_started_now = True

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=stage_id,
        action='matches_generated',
        payload={
            'match_count': len(matches),
            'correlation_id': correlation_id,
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    if stage_started_now:
        enqueue_discord_event(
            party_id,
            tournament_id,
            event_name='stage_started',
            payload={
                'stage_id': str(stage_id),
                'stage_name': payload.stage.name,
            },
        )

    if payload.tournament.status == TournamentStatus.live:
        for match in matches:
            if match.state != MatchState.ready:
                continue
            db_match = db.session.get(DbNetsessionTourneyMatch, match.id)
            if db_match is None or db_match.state != MatchState.ready.value:
                continue
            _enqueue_match_ready_notifications(db_match)
        db.session.commit()

    _auto_advance_byes(
        tournament_id, payload.stage, engine=payload.engine
    )

    log.info(
        'netsession_tourney.matches_generated',
        tournament_id=str(tournament_id),
        stage_id=str(stage_id),
        actor_user_id=str(initiator.id),
        correlation_id=correlation_id,
        match_count=len(matches),
    )

    return Ok(matches)


def _build_stage_generation_payload(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    *,
    stage_settings_override: dict[str, Any] | None = None,
    require_flatout2_hosts: bool = True,
) -> Result[_StageGenerationPayload, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unknown stage.')

    stage = _db_stage_to_model(db_stage)
    if stage_settings_override:
        merged_stage_settings = dict(stage.settings or {})
        merged_stage_settings.update(stage_settings_override)
        stage = replace(stage, settings=merged_stage_settings)
    tournament = _db_tournament_to_model(db_tournament)
    stage_type_spec = get_stage_type_spec(stage.type)
    if not stage_type_spec.enabled:
        return Err('Stage type is currently disabled.')

    engine = find_stage_engine(stage.type)
    if engine is None:
        return Err('No engine available for this stage type yet.')

    selected_participants_result = _select_generation_participants_for_stage(
        party_id,
        tournament_id,
        stage,
    )
    if selected_participants_result.is_err():
        return Err(selected_participants_result.unwrap_err())
    participants = selected_participants_result.unwrap()

    team_size_validation_result = _validate_bracket_ready_team_sizes(
        tournament, participants
    )
    if team_size_validation_result.is_err():
        return Err(team_size_validation_result.unwrap_err())

    ordered_participants = _order_participants_for_stage_generation(
        participants,
        shuffle_unseeded=(
            (stage.settings or {}).get('participant_source_mode')
            not in {
                'stage_qualifiers',
                'stage_match_qualifiers',
                'builder_fixed_participants',
            }
        ),
    )
    participant_ids = [participant.id for participant in ordered_participants]
    resolved_stage_result = _resolve_stage_builder_stage_for_generation(
        stage,
        participant_count=len(participant_ids),
    )
    if resolved_stage_result.is_err():
        return Err(resolved_stage_result.unwrap_err())
    stage = resolved_stage_result.unwrap()

    if (
        stage.type == StageType.ffa_flatout2_single_elimination
        and (
            (stage.settings or {}).get('flatout2_manual_stage')
            or not (stage.settings or {}).get('builder_kind')
        )
    ):
        return _build_manual_flatout2_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
        )

    validation_result = engine.validate(stage, participant_ids)
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    if stage.type == StageType.ffa_flatout2_single_elimination:
        return _build_flatout2_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            tournament_id=tournament_id,
            require_hosts=require_flatout2_hosts,
        )

    if stage.type == StageType.swiss:
        return _build_swiss_stage_generation_payload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            tournament_id=tournament_id,
        )

    generation_result = engine.generate(stage, participant_ids)
    if generation_result.is_err():
        return Err(generation_result.unwrap_err())

    return Ok(
        _StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=ordered_participants,
            match_specs=generation_result.unwrap(),
        )
    )


def _build_swiss_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
    tournament_id: TournamentID,
) -> Result[_StageGenerationPayload, str]:
    del tournament_id

    round_count = _get_round_count_for_swiss_stage(
        stage, participant_count=len(participants)
    )
    match_specs = _build_full_swiss_stage_specs(
        participants,
        round_count=round_count,
    )

    return Ok(
        _StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=participants,
            match_specs=match_specs,
        )
        )


def _build_manual_flatout2_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
) -> Result[_StageGenerationPayload, str]:
    settings = stage.settings or {}
    raw_rounds = settings.get('flatout2_rounds')
    if not isinstance(raw_rounds, list) or not raw_rounds:
        return Err('Bitte die FlatOut-2-Stage zuerst vorbereiten.')

    try:
        max_players_per_match = int(settings.get('max_players_per_match') or 8)
    except (TypeError, ValueError):
        return Err('Die maximale Teilnehmerzahl pro FlatOut-2-Match ist ungültig.')

    if max_players_per_match < 2 or max_players_per_match > 8:
        return Err(
            'FlatOut 2 unterstützt pro Match nur eine Teilnehmerzahl zwischen 2 und 8.'
        )

    raw_match_blueprints = settings.get('flatout2_match_blueprints')
    if not isinstance(raw_match_blueprints, dict):
        raw_match_blueprints = {}

    match_specs: list[MatchSpec] = []
    seen_match_nos: set[int] = set()

    for raw_round in raw_rounds:
        if not isinstance(raw_round, dict):
            continue

        try:
            round_no = int(raw_round.get('round_no') or 0)
            match_count = int(raw_round.get('match_count') or 0)
        except (TypeError, ValueError):
            return Err('Die FlatOut-2-Rundenkonfiguration ist ungültig.')

        if round_no < 1 or match_count < 1:
            return Err('Jede FlatOut-2-Runde braucht mindestens ein Match.')

        for match_index in range(1, match_count + 1):
            match_no = len(match_specs) + 1
            if match_no in seen_match_nos:
                return Err('Die FlatOut-2-Matchnummern sind nicht eindeutig.')
            seen_match_nos.add(match_no)

            match_key = f'{round_no}:{match_index}'
            blueprint = raw_match_blueprints.get(match_key)
            if not isinstance(blueprint, dict):
                blueprint = {}

            raw_participant_ids = blueprint.get('participant_ids')
            if not isinstance(raw_participant_ids, list):
                raw_participant_ids = []

            participant_ids: list[ParticipantID | None] = []
            for raw_participant_id in raw_participant_ids[:max_players_per_match]:
                if not raw_participant_id:
                    participant_ids.append(None)
                    continue
                try:
                    participant_ids.append(
                        ParticipantID(UUID(str(raw_participant_id)))
                    )
                except (TypeError, ValueError):
                    return Err(
                        'Die Teilnehmerzuordnung in der FlatOut-2-Stage ist ungültig.'
                    )

            while len(participant_ids) < max_players_per_match:
                participant_ids.append(None)

            real_participant_ids = [
                participant_id
                for participant_id in participant_ids
                if participant_id is not None
            ]
            if len(set(real_participant_ids)) != len(real_participant_ids):
                return Err(
                    'Ein FlatOut-2-Match darf denselben Teilnehmer nicht mehrfach enthalten.'
                )

            slots = [
                SlotSpec(
                    slot_no=slot_no,
                    participant_id=participant_id,
                    source_match_no=None,
                )
                for slot_no, participant_id in enumerate(participant_ids, start=1)
            ]

            match_specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='ready' if len(real_participant_ids) >= 2 else 'pending',
                    slots=slots,
                )
            )

    if not match_specs:
        return Err('Bitte mindestens ein FlatOut-2-Match konfigurieren.')

    return Ok(
        _StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=[],
            match_specs=match_specs,
            replace_existing_matches=True,
        )
    )


def _build_flatout2_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
    tournament_id: TournamentID,
    require_hosts: bool,
) -> Result[_StageGenerationPayload, str]:
    context_result = _get_flatout2_current_round_generation_context(
        tournament_id=tournament_id,
        stage=stage,
        engine=engine,
        participants=participants,
    )
    if context_result.is_err():
        return Err(context_result.unwrap_err())

    context = context_result.unwrap()
    if require_hosts:
        match_specs_result = _build_flatout2_current_round_match_specs(
            stage=stage,
            context=context,
        )
        if match_specs_result.is_err():
            return Err(match_specs_result.unwrap_err())
        match_specs = match_specs_result.unwrap()
    else:
        match_specs = [
            MatchSpec(
                round_no=context.current_round_no,
                match_no=match_no,
                state='pending',
                slots=[
                    SlotSpec(
                        slot_no=index + 1,
                        participant_id=participant.id,
                        source_match_no=None,
                    )
                    for index, participant in enumerate(context.participants)
                ],
            )
            for match_no in context.match_nos
        ]

    return Ok(
        _StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=context.participants,
            match_specs=match_specs,
            replace_existing_matches=context.replace_existing_matches,
        )
    )


def _get_flatout2_current_round_generation_context(
    *,
    tournament_id: TournamentID,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
) -> Result[_Flatout2CurrentRoundGenerationContext, str]:
    participant_ids = [participant.id for participant in participants]
    full_generation_result = engine.generate(stage, participant_ids)
    if full_generation_result.is_err():
        return Err(full_generation_result.unwrap_err())

    full_specs = full_generation_result.unwrap()
    if not full_specs:
        return Err('Für diese FlatOut-2-Stage konnten keine Runden berechnet werden.')

    if (stage.settings or {}).get('builder_materialized_round_stage'):
        first_round_no = min(spec.round_no for spec in full_specs)
        current_round_specs = [
            spec for spec in full_specs if spec.round_no == first_round_no
        ]
        try:
            display_round_no = int(
                (stage.settings or {}).get('builder_display_round_no')
                or first_round_no
            )
        except (TypeError, ValueError):
            display_round_no = first_round_no

        return Ok(
            _Flatout2CurrentRoundGenerationContext(
                current_round_no=display_round_no,
                total_round_count=display_round_no,
                match_nos=[spec.match_no for spec in current_round_specs],
                participants=participants,
                replace_existing_matches=True,
            )
        )

    planned_match_nos_by_round_no: dict[int, list[int]] = defaultdict(list)
    for spec in full_specs:
        planned_match_nos_by_round_no[spec.round_no].append(spec.match_no)

    total_round_count = max(planned_match_nos_by_round_no.keys())
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id, stage_id=stage.id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()

    if not db_matches:
        return Ok(
            _Flatout2CurrentRoundGenerationContext(
                current_round_no=1,
                total_round_count=total_round_count,
                match_nos=planned_match_nos_by_round_no.get(1, []),
                participants=participants,
                replace_existing_matches=True,
            )
        )

    if any(match.state != MatchState.completed.value for match in db_matches):
        return Err(
            'Die aktuell generierte FlatOut-2-Runde ist noch nicht abgeschlossen.'
        )

    highest_generated_round_no = max(match.round_no for match in db_matches)
    next_round_no = highest_generated_round_no + 1
    if next_round_no > total_round_count:
        return Err('Alle FlatOut-2-Runden sind bereits generiert.')

    previous_round_matches = [
        match
        for match in db_matches
        if match.round_no == highest_generated_round_no
    ]
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(
                [match.id for match in previous_round_matches]
            )
        )
    ).all():
        slots_by_match_id[db_slot.match_id].append(db_slot)

    qualified_participant_ids: list[ParticipantID] = []
    for previous_round_match in sorted(
        previous_round_matches, key=lambda item: item.match_no
    ):
        qualified_participant_ids.extend(
            _get_ffa_single_elimination_qualifier_ids(
                previous_round_match.id,
                sorted(
                    slots_by_match_id.get(previous_round_match.id, []),
                    key=lambda item: item.slot_no,
                ),
                3,
            )
        )

    participants_by_id = {participant.id: participant for participant in participants}
    qualified_participants = [
        participants_by_id[participant_id]
        for participant_id in qualified_participant_ids
        if participant_id in participants_by_id
    ]
    if len(qualified_participants) < 2:
        return Err(
            'Es stehen noch nicht genug Qualifikanten für die nächste FlatOut-2-Runde fest.'
        )

    return Ok(
        _Flatout2CurrentRoundGenerationContext(
            current_round_no=next_round_no,
            total_round_count=total_round_count,
            match_nos=planned_match_nos_by_round_no.get(next_round_no, []),
            participants=qualified_participants,
            replace_existing_matches=False,
        )
    )


def _build_flatout2_current_round_match_specs(
    *,
    stage: Stage,
    context: _Flatout2CurrentRoundGenerationContext,
) -> Result[list[MatchSpec], str]:
    raw_hosts_by_round = (stage.settings or {}).get('flatout2_round_hosts', {})
    if not isinstance(raw_hosts_by_round, dict):
        raw_hosts_by_round = {}

    raw_host_ids = raw_hosts_by_round.get(str(context.current_round_no)) or []
    if not isinstance(raw_host_ids, list):
        raw_host_ids = []

    host_participant_ids: list[ParticipantID] = []
    for raw_host_id in raw_host_ids:
        try:
            host_participant_ids.append(ParticipantID(UUID(str(raw_host_id))))
        except (TypeError, ValueError):
            return Err(
                'Die Host-Auswahl für die aktuelle FlatOut-2-Runde ist ungültig.'
            )

    if len(host_participant_ids) != len(context.match_nos):
        return Err(
            'Bitte für jedes Match der aktuellen FlatOut-2-Runde genau einen Host auswählen.'
        )

    if len(set(host_participant_ids)) != len(host_participant_ids):
        return Err(
            'Jeder FlatOut-2-Host darf in einer Runde nur einmal ausgewählt werden.'
        )

    allowed_participant_ids = {participant.id for participant in context.participants}
    if any(
        host_participant_id not in allowed_participant_ids
        for host_participant_id in host_participant_ids
    ):
        return Err(
            'Mindestens ein ausgewählter FlatOut-2-Host gehört nicht zum Teilnehmerfeld dieser Runde.'
        )

    ordered_participant_ids = [
        participant.id
        for participant in context.participants
    ]
    host_participant_id_set = set(host_participant_ids)
    remaining_participant_ids = [
        participant_id
        for participant_id in ordered_participant_ids
        if participant_id not in host_participant_id_set
    ]
    additional_sizes = _distribute_evenly(
        len(remaining_participant_ids), len(host_participant_ids)
    )

    specs: list[MatchSpec] = []
    offset = 0
    for index, match_no in enumerate(context.match_nos):
        host_participant_id = host_participant_ids[index]
        additional_count = additional_sizes[index]
        participant_ids_for_match = [host_participant_id]
        participant_ids_for_match.extend(
            remaining_participant_ids[offset : offset + additional_count]
        )
        offset += additional_count

        slots = [
            SlotSpec(
                slot_no=slot_index + 1,
                participant_id=participant_id,
                source_match_no=None,
            )
            for slot_index, participant_id in enumerate(participant_ids_for_match)
        ]
        if len(slots) == 1:
            slots.append(
                SlotSpec(
                    slot_no=2,
                    participant_id=None,
                    source_match_no=None,
                )
            )

        specs.append(
            MatchSpec(
                round_no=context.current_round_no,
                match_no=match_no,
                state='ready' if len(participant_ids_for_match) >= 2 else 'pending',
                slots=slots,
            )
        )

    return Ok(specs)


def _order_participants_for_stage_generation(
    participants: list[Participant],
    *,
    shuffle_unseeded: bool,
) -> list[Participant]:
    participant_count = len(participants)
    if participant_count <= 1:
        return participants

    contiguous_seeded: list[Participant] = []
    deferred_unseeded: list[Participant] = []
    seen_seeds: set[int] = set()
    expected_seed = 1

    for participant in sorted(
        participants,
        key=lambda item: (
            item.seed if item.seed is not None else 999_999,
            item.name.lower(),
            str(item.id),
        ),
    ):
        seed = participant.seed
        if (
            seed is None
            or seed < 1
            or seed > participant_count
            or seed in seen_seeds
            or seed != expected_seed
        ):
            deferred_unseeded.append(participant)
            continue

        contiguous_seeded.append(participant)
        seen_seeds.add(seed)
        expected_seed += 1

    if shuffle_unseeded:
        random.shuffle(deferred_unseeded)
    return contiguous_seeded + deferred_unseeded


def _resolve_stage_builder_stage_for_generation(
    stage: Stage,
    *,
    participant_count: int,
) -> Result[Stage, str]:
    if not _is_stage_builder_v1_preliminary_stage(stage):
        return Ok(stage)

    main_stage_size = _get_stage_builder_main_stage_size(stage)
    if main_stage_size is None:
        return Err('Builder main stage size is invalid.')

    if participant_count <= main_stage_size:
        return Err(
            'Vorrunde ist mit der aktuellen Anzahl ready Teilnehmer nicht nötig.'
        )

    if stage.type == StageType.round_robin_groups:
        plan_result = _resolve_round_robin_builder_plan(
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            round_robin_builder_mode=stage.settings.get(
                'builder_round_robin_mode'
            ),
            round_robin_group_count=stage.settings.get(
                'builder_round_robin_group_count'
            ),
        )
        if plan_result.is_err():
            return Err(plan_result.unwrap_err())

        plan = plan_result.unwrap()
        resolved_settings = dict(stage.settings)
        resolved_settings['group_count'] = plan.group_count
        resolved_settings['builder_resolved_qualifiers_per_group'] = (
            plan.qualifiers_per_group
        )
        resolved_settings['builder_resolved_group_size_min'] = (
            plan.min_group_size
        )
        resolved_settings['builder_resolved_group_size_max'] = (
            plan.max_group_size
        )
        return Ok(
            Stage(
                id=stage.id,
                tournament_id=stage.tournament_id,
                order_no=stage.order_no,
                type=stage.type,
                name=stage.name,
                settings=resolved_settings,
                status=stage.status,
            )
        )

    if stage.type == StageType.swiss:
        threshold = _get_swiss_threshold_for_stage(
            stage, participant_count=participant_count
        )
        if threshold not in SWISS_THRESHOLDS and participant_count > 1:
            return Err('Swiss threshold is invalid.')
        return Ok(stage)

    return Ok(stage)


def _resolve_round_robin_builder_plan(
    *,
    participant_count: int,
    main_stage_size: int,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
) -> Result[_RoundRobinBuilderPlan, str]:
    if round_robin_builder_mode == 'manual_group_count':
        if round_robin_group_count is None:
            return Err(
                'Für die Expertenoption muss eine gültige Gruppenzahl gewählt werden.'
            )
        return _build_round_robin_builder_plan_for_group_count(
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            group_count=round_robin_group_count,
            mode='manual_group_count',
        )

    candidates: list[tuple[tuple[float, int, int], _RoundRobinBuilderPlan]] = []
    for group_count in sorted(_get_divisors(main_stage_size)):
        plan_result = _build_round_robin_builder_plan_for_group_count(
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            group_count=group_count,
            mode='standard',
        )
        if plan_result.is_err():
            continue
        plan = plan_result.unwrap()

        average_group_size = participant_count / plan.group_count
        prefers_esports_default = (
            main_stage_size == 16 and plan.group_count == 8 and plan.qualifiers_per_group == 2
        )
        score = (
            0 if prefers_esports_default else 1,
            abs(average_group_size - 6),
            abs(plan.qualifiers_per_group - 2),
            -plan.group_count,
        )
        candidates.append((score, plan))

    if not candidates:
        return Err(
            'Für Round Robin Groups konnte keine sinnvolle Vorrundenverteilung gefunden werden. '
            'Wähle eine andere Main Stage Größe oder ein anderes Vorrundenformat.'
        )

    candidates.sort(key=lambda item: item[0])
    return Ok(candidates[0][1])


def _build_round_robin_builder_plan_for_group_count(
    *,
    participant_count: int,
    main_stage_size: int,
    group_count: int,
    mode: str,
) -> Result[_RoundRobinBuilderPlan, str]:
    if group_count < 2:
        return Err('Die Gruppenzahl muss mindestens 2 sein.')
    if main_stage_size % group_count != 0:
        return Err(
            'Die Gruppenzahl muss das Hauptturnier gleichmäßig füllen können.'
        )

    qualifiers_per_group = main_stage_size // group_count
    if qualifiers_per_group < 1:
        return Err('Die Gruppenzahl ist ungültig.')

    min_group_size = participant_count // group_count
    max_group_size = min_group_size + (
        1 if participant_count % group_count else 0
    )
    if min_group_size < qualifiers_per_group + 2:
        return Err(
            'Die Gruppenzahl ist für diese Teilnehmerzahl zu klein oder zu aggressiv.'
        )

    return Ok(
        _RoundRobinBuilderPlan(
            group_count=group_count,
            qualifiers_per_group=qualifiers_per_group,
            min_group_size=min_group_size,
            max_group_size=max_group_size,
            mode=mode,
        )
    )


def _distribute_evenly(total: int, bucket_count: int) -> list[int]:
    if bucket_count < 1:
        return []

    base = total // bucket_count
    remainder = total % bucket_count
    return [base + (1 if index < remainder else 0) for index in range(bucket_count)]


def _get_divisors(number: int) -> list[int]:
    divisors: set[int] = set()
    for candidate in range(1, int(math.sqrt(number)) + 1):
        if number % candidate != 0:
            continue
        divisors.add(candidate)
        divisors.add(number // candidate)

    return sorted(divisors)


def _get_round_count_for_swiss_stage(
    stage: Stage, *, participant_count: int
) -> int:
    configured_threshold = _get_configured_swiss_threshold(stage.settings)
    if configured_threshold is not None:
        return _get_swiss_round_count_for_threshold(configured_threshold)

    max_rounds = max(1, participant_count - 1)
    raw_value = (stage.settings or {}).get('round_count')
    if raw_value is None:
        return max_rounds

    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return max_rounds

    if parsed < 1:
        return 1

    return min(parsed, max_rounds)


def _get_swiss_threshold_for_round_count(round_count: int) -> int:
    return (round_count // 2) + 1


def _get_swiss_round_count_for_threshold(threshold: int) -> int:
    return (threshold * 2) - 1


def _get_configured_swiss_threshold(settings: dict[str, Any] | None) -> int | None:
    if not isinstance(settings, dict):
        return None

    raw_value = settings.get('swiss_threshold')
    try:
        threshold = int(raw_value)
    except (TypeError, ValueError):
        return None

    return threshold if threshold in SWISS_THRESHOLDS else None


def _get_swiss_threshold_for_stage(
    stage: Stage, *, participant_count: int
) -> int:
    configured_threshold = _get_configured_swiss_threshold(stage.settings)
    if configured_threshold is not None:
        return configured_threshold

    round_count = _get_round_count_for_swiss_stage(
        stage, participant_count=participant_count
    )
    return _get_swiss_threshold_for_round_count(round_count)


def _build_swiss_round_layout(
    participant_count: int,
    round_count: int,
) -> list[dict[str, Any]]:
    if participant_count < 2 or round_count < 1:
        return []

    threshold = _get_swiss_threshold_for_round_count(round_count)
    counts_by_record: dict[tuple[int, int], int] = {(0, 0): participant_count}
    rounds: list[dict[str, Any]] = []

    for round_no in range(1, round_count + 1):
        pools = []
        active_records = sorted(
            counts_by_record.items(),
            key=lambda item: (-item[0][0], item[0][1]),
        )
        for (wins, losses), count in active_records:
            if count < 1:
                continue
            pools.append(
                {
                    'wins': wins,
                    'losses': losses,
                    'participant_count': count,
                    'match_count': math.ceil(count / 2),
                }
            )

        rounds.append({'round_no': round_no, 'pools': pools})

        next_counts: dict[tuple[int, int], int] = defaultdict(int)
        for pool in pools:
            wins = pool['wins']
            losses = pool['losses']
            count = pool['participant_count']
            winner_count = math.ceil(count / 2)
            loser_count = count // 2

            if wins + 1 < threshold:
                next_counts[(wins + 1, losses)] += winner_count
            if losses + 1 < threshold:
                next_counts[(wins, losses + 1)] += loser_count

        counts_by_record = dict(next_counts)

    return rounds


def _build_full_swiss_stage_specs(
    participants: list[Participant],
    *,
    round_count: int,
) -> list[MatchSpec]:
    if len(participants) < 2:
        return []

    layout = _build_swiss_round_layout(len(participants), round_count)
    if not layout:
        return []

    first_round_specs = _build_initial_swiss_round_specs(participants)
    specs = list(first_round_specs)
    match_no = len(first_round_specs) + 1

    for round_layout in layout[1:]:
        for pool in round_layout['pools']:
            for _ in range(pool['match_count']):
                specs.append(
                    MatchSpec(
                        round_no=round_layout['round_no'],
                        match_no=match_no,
                        state='pending',
                        slots=[
                            SlotSpec(
                                slot_no=1,
                                participant_id=None,
                                source_match_no=None,
                            ),
                            SlotSpec(
                                slot_no=2,
                                participant_id=None,
                                source_match_no=None,
                            ),
                        ],
                    )
                )
                match_no += 1

    return specs


def _build_initial_swiss_round_specs(
    participants: list[Participant],
) -> list[MatchSpec]:
    if len(participants) < 2:
        return []

    ordered = list(participants)
    bye_participant = None
    if len(ordered) % 2 == 1:
        bye_participant = ordered.pop()

    midpoint = len(ordered) // 2
    top_half = ordered[:midpoint]
    bottom_half = ordered[midpoint:]

    specs: list[MatchSpec] = []
    match_no = 1
    for participant_a, participant_b in zip(top_half, bottom_half, strict=False):
        specs.append(
            MatchSpec(
                round_no=1,
                match_no=match_no,
                state='ready',
                slots=[
                    SlotSpec(
                        slot_no=1,
                        participant_id=participant_a.id,
                        source_match_no=None,
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=participant_b.id,
                        source_match_no=None,
                    ),
                ],
            )
        )
        match_no += 1

    if bye_participant is not None:
        specs.append(
            MatchSpec(
                round_no=1,
                match_no=match_no,
                state='pending',
                slots=[
                    SlotSpec(
                        slot_no=1,
                        participant_id=bye_participant.id,
                        source_match_no=None,
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=None,
                        source_match_no=None,
                    ),
                ],
            )
        )

    return specs


def _build_follow_up_swiss_round_specs(
    *,
    participants: list[Participant],
    db_matches: list[DbNetsessionTourneyMatch],
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]],
    results_by_match_id: dict[MatchID, DbNetsessionTourneyMatchResult],
    next_round_no: int,
    first_match_no: int,
    round_count: int,
) -> list[MatchSpec]:
    participant_by_id = {participant.id: participant for participant in participants}
    threshold = _get_swiss_threshold_for_round_count(round_count)
    wins_by_participant_id: dict[ParticipantID, int] = defaultdict(int)
    losses_by_participant_id: dict[ParticipantID, int] = defaultdict(int)
    opponents_by_participant_id: dict[ParticipantID, set[ParticipantID]] = defaultdict(
        set
    )
    bye_count_by_participant_id: dict[ParticipantID, int] = defaultdict(int)

    for db_match in db_matches:
        db_slots = slots_by_match_id.get(db_match.id, [])
        participant_ids = [
            db_slot.participant_id
            for db_slot in db_slots
            if db_slot.participant_id in participant_by_id
        ]
        if not participant_ids:
            continue

        if len(participant_ids) == 1:
            bye_count_by_participant_id[participant_ids[0]] += 1

        if len(participant_ids) == 2:
            participant_a, participant_b = participant_ids
            opponents_by_participant_id[participant_a].add(participant_b)
            opponents_by_participant_id[participant_b].add(participant_a)

        db_result = results_by_match_id.get(db_match.id)
        if db_result is None or db_result.winner_slot is None:
            continue

        winner_participant_id = next(
            (
                db_slot.participant_id
                for db_slot in db_slots
                if db_slot.slot_no == db_result.winner_slot
            ),
            None,
        )
        if winner_participant_id not in participant_by_id:
            continue

        wins_by_participant_id[winner_participant_id] += 1
        for participant_id in participant_ids:
            if participant_id != winner_participant_id:
                losses_by_participant_id[participant_id] += 1

    ranked_participants = sorted(
        [
            participant
            for participant in participants
            if wins_by_participant_id[participant.id] < threshold
            and losses_by_participant_id[participant.id] < threshold
            and (
                wins_by_participant_id[participant.id]
                + losses_by_participant_id[participant.id]
                == next_round_no - 1
            )
        ],
        key=lambda participant: (
            -wins_by_participant_id[participant.id],
            losses_by_participant_id[participant.id],
            participant.seed if participant.seed is not None else 999_999,
            participant.name.lower(),
            str(participant.id),
        ),
    )

    bye_participant = None
    if len(ranked_participants) % 2 == 1:
        bye_participant = _select_swiss_bye_participant(
            ranked_participants, bye_count_by_participant_id
        )
        ranked_participants = [
            participant
            for participant in ranked_participants
            if participant.id != bye_participant.id
        ]

    grouped_participants = defaultdict(list)
    for participant in ranked_participants:
        grouped_participants[
            (
                wins_by_participant_id[participant.id],
                losses_by_participant_id[participant.id],
            )
        ].append(participant)

    pairs: list[tuple[Participant, Participant]] = []
    carry_over: list[Participant] = []
    for record in sorted(
        grouped_participants.keys(), key=lambda item: (-item[0], item[1])
    ):
        current_group = carry_over + grouped_participants[record]
        carry_over = []

        while current_group:
            if len(current_group) % 2 == 1:
                carry_over = [current_group.pop()]

            pairing = _find_swiss_pairing_for_group(
                current_group,
                opponents_by_participant_id,
            )
            if pairing is not None:
                pairs.extend(pairing)
                current_group = []
                continue

            if len(current_group) <= 2:
                if len(current_group) == 2:
                    pairs.append((current_group[0], current_group[1]))
                current_group = []
                continue

            carry_over = [current_group.pop()]

        if carry_over:
            continue

    if carry_over:
        if bye_participant is None:
            bye_participant = _select_swiss_bye_participant(
                carry_over, bye_count_by_participant_id
            )
            carry_over = [
                participant
                for participant in carry_over
                if participant.id != bye_participant.id
            ]
        if len(carry_over) == 2:
            pairs.append((carry_over[0], carry_over[1]))

    specs: list[MatchSpec] = []
    match_no = first_match_no
    for participant_a, participant_b in pairs:
        specs.append(
            MatchSpec(
                round_no=next_round_no,
                match_no=match_no,
                state='ready',
                slots=[
                    SlotSpec(
                        slot_no=1,
                        participant_id=participant_a.id,
                        source_match_no=None,
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=participant_b.id,
                        source_match_no=None,
                    ),
                ],
            )
        )
        match_no += 1

    if bye_participant is not None:
        specs.append(
            MatchSpec(
                round_no=next_round_no,
                match_no=match_no,
                state='pending',
                slots=[
                    SlotSpec(
                        slot_no=1,
                        participant_id=bye_participant.id,
                        source_match_no=None,
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=None,
                        source_match_no=None,
                    ),
                ],
            )
        )

    return specs


def _select_swiss_bye_participant(
    participants: list[Participant],
    bye_count_by_participant_id: dict[ParticipantID, int],
) -> Participant:
    lowest_bye_count = min(
        bye_count_by_participant_id.get(participant.id, 0)
        for participant in participants
    )
    for participant in reversed(participants):
        if (
            bye_count_by_participant_id.get(participant.id, 0)
            == lowest_bye_count
        ):
            return participant

    return participants[-1]


def _find_swiss_pairing_for_group(
    participants: list[Participant],
    opponents_by_participant_id: dict[ParticipantID, set[ParticipantID]],
) -> list[tuple[Participant, Participant]] | None:
    if not participants:
        return []
    if len(participants) % 2 == 1:
        return None

    first = participants[0]
    for index, candidate in enumerate(participants[1:], start=1):
        if candidate.id in opponents_by_participant_id.get(first.id, set()):
            continue

        remainder = participants[1:index] + participants[index + 1 :]
        remainder_pairing = _find_swiss_pairing_for_group(
            remainder, opponents_by_participant_id
        )
        if remainder_pairing is not None:
            return [(first, candidate)] + remainder_pairing

    # Fall back to the least bad option if rematches are unavoidable.
    candidate = participants[1]
    remainder = participants[2:]
    remainder_pairing = _find_swiss_pairing_for_group(
        remainder, opponents_by_participant_id
    )
    if remainder_pairing is None:
        return None
    return [(first, candidate)] + remainder_pairing


def _materialize_round_robin_builder_group_stages(
    *,
    party_id: PartyID,
    tournament_id: TournamentID,
    db_stage: DbNetsessionTourneyStage,
    payload: _StageGenerationPayload,
    initiator: User,
    correlation_id: str | None,
    round_starts_at_by_round_no: dict[int, datetime] | None,
) -> Result[list[Match], str]:
    settings = dict(db_stage.settings_json or {})
    if settings.get('builder_materialized_group_stage_ids'):
        return Err(
            'Diese Builder-Vorrunde wurde bereits in echte Gruppen-Stages aufgeteilt.'
        )

    try:
        group_count = int(payload.stage.settings.get('group_count'))
        qualifiers_per_group = int(
            payload.stage.settings.get('builder_resolved_qualifiers_per_group')
        )
    except (TypeError, ValueError):
        return Err('Builder-Gruppenplan ist ungültig.')

    if group_count < 1 or qualifiers_per_group < 1:
        return Err('Builder-Gruppenplan ist unvollständig.')

    group_stage_specs = _build_round_robin_builder_group_stage_specs(
        payload.participants,
        group_count=group_count,
        qualifiers_per_group=qualifiers_per_group,
    )
    if not group_stage_specs:
        return Err('Es konnten keine Builder-Gruppen erzeugt werden.')

    db_main_stage = _find_builder_main_stage_for_preliminary_stage(
        tournament_id, db_stage.id
    )
    if db_main_stage is None:
        return Err('Das Builder-Hauptturnier zur Vorrunde konnte nicht gefunden werden.')

    db_stages_to_shift = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyStage.order_no > db_stage.order_no)
        .order_by(DbNetsessionTourneyStage.order_no.desc())
    ).all()
    for db_other_stage in db_stages_to_shift:
        db_other_stage.order_no += len(group_stage_specs)

    now = datetime.utcnow()
    created_group_stage_ids: list[StageID] = []
    created_matches: list[Match] = []
    base_settings = {
        key: value
        for key, value in settings.items()
        if key
        in {
            'builder_kind',
            'builder_generation_basis',
            'builder_main_stage_size',
            'match_duration_minutes',
            'max_matches_per_round',
            'break_between_rounds_minutes',
            'result_report_mode',
        }
    }

    for index, group_stage_spec in enumerate(group_stage_specs, start=1):
        group_settings = dict(base_settings)
        group_settings.update(
            {
                'group_count': 1,
                'participant_source_mode': 'builder_fixed_participants',
                'builder_role': 'preliminary_group',
                'builder_preliminary_stage_id': str(db_stage.id),
                'builder_group_label': group_stage_spec.label,
                'builder_group_qualifier_top_n': (
                    group_stage_spec.qualifiers_per_group
                ),
                'builder_fixed_participant_ids': [
                    str(participant_id)
                    for participant_id in group_stage_spec.participant_ids
                ],
            }
        )
        db_group_stage = DbNetsessionTourneyStage(
            StageID(generate_uuid7()),
            tournament_id,
            db_stage.order_no + index,
            StageType.round_robin_groups,
            f'Vorrunde Gruppe {group_stage_spec.label}',
            now,
            settings_json=group_settings,
        )
        db.session.add(db_group_stage)
        created_group_stage_ids.append(db_group_stage.id)

        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='stage',
            object_id=db_group_stage.id,
            action='stage_created',
            payload={
                'type': StageType.round_robin_groups.value,
                'name': db_group_stage.name,
                'settings': group_settings,
                'created_by_builder_materialization': True,
            },
            created_at=now,
        )

    settings['builder_materialized_group_stage_ids'] = [
        str(stage_id) for stage_id in created_group_stage_ids
    ]
    settings['builder_materialized_group_count'] = len(created_group_stage_ids)
    settings['builder_materialized_qualifiers_per_group'] = qualifiers_per_group
    settings['builder_materialized_at'] = now.isoformat()
    db_stage.settings_json = settings
    db_stage.status = StageStatus.closed.value
    db_stage.name = 'Vorrunden-Übersicht'

    main_settings = dict(db_main_stage.settings_json or {})
    main_settings['participant_source_mode'] = 'stage_qualifiers'
    main_settings['qualifier_source_stage_ids'] = [
        str(stage_id) for stage_id in created_group_stage_ids
    ]
    main_settings['qualifier_selection_mode'] = 'per_stage'
    main_settings['qualifier_top_n'] = qualifiers_per_group
    main_settings['builder_auto_qualifier_count'] = False
    main_settings['builder_materialized_group_stage_ids'] = [
        str(stage_id) for stage_id in created_group_stage_ids
    ]
    db_main_stage.settings_json = main_settings

    db.session.commit()

    for group_stage_id in created_group_stage_ids:
        generated_matches_result = generate_stage_matches(
            party_id,
            tournament_id,
            group_stage_id,
            initiator,
            correlation_id=correlation_id,
            round_starts_at_by_round_no=round_starts_at_by_round_no,
        )
        if generated_matches_result.is_err():
            return Err(generated_matches_result.unwrap_err())
        created_matches.extend(generated_matches_result.unwrap())

    return Ok(created_matches)


def _build_round_robin_builder_group_stage_specs(
    participants: list[Participant],
    *,
    group_count: int,
    qualifiers_per_group: int,
) -> list[_BuilderGroupStageSpec]:
    group_sizes = _distribute_evenly(len(participants), group_count)
    specs: list[_BuilderGroupStageSpec] = []
    offset = 0
    for index, group_size in enumerate(group_sizes):
        group_participants = participants[offset : offset + group_size]
        offset += group_size
        specs.append(
            _BuilderGroupStageSpec(
                label=_build_group_label(index),
                participant_ids=[participant.id for participant in group_participants],
                qualifiers_per_group=qualifiers_per_group,
            )
        )

    return specs


def _build_group_label(index: int) -> str:
    label = ''
    value = index
    while True:
        value, remainder = divmod(value, 26)
        label = chr(ord('A') + remainder) + label
        if value == 0:
            return label
        value -= 1


def _find_builder_main_stage_for_preliminary_stage(
    tournament_id: TournamentID, preliminary_stage_id: StageID
) -> DbNetsessionTourneyStage | None:
    for db_stage in db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ):
        settings = db_stage.settings_json or {}
        if (
            settings.get('builder_role') == 'main'
            and settings.get('builder_preliminary_stage_id')
            == str(preliminary_stage_id)
        ):
            return db_stage

    return None


def _select_generation_participants_for_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage: Stage,
) -> Result[list[Participant], str]:
    all_tournament_participants = get_participants_for_tournament(
        party_id, tournament_id
    )
    is_stage_builder_v1_stage = _is_stage_builder_v1_main_stage(
        stage
    ) or _is_stage_builder_v1_preliminary_stage(stage)
    eligible_participants = (
        domain_service.select_ready_participants(all_tournament_participants)
        if is_stage_builder_v1_stage
        else domain_service.select_bracket_ready_participants(
            all_tournament_participants
        )
    )
    builder_main_stage_size = _get_stage_builder_main_stage_size(stage)
    if (
        _is_stage_builder_v1_main_stage(stage)
        and builder_main_stage_size is not None
    ):
        if (
            stage.settings.get('builder_preliminary_stage_id')
            and len(eligible_participants) <= builder_main_stage_size
        ):
            return Ok(eligible_participants)
        if (
            not stage.settings.get('builder_preliminary_stage_id')
            and len(eligible_participants) > builder_main_stage_size
        ):
            return Err(
                'Die aktuelle Anzahl ready Teilnehmer überschreitet die konfigurierte Main Stage Größe. '
                'Aktiviere eine Vorrunde oder reduziere die Teilnehmerbasis.'
            )

    source_mode = (stage.settings or {}).get('participant_source_mode')
    if source_mode == 'builder_fixed_participants':
        fixed_participant_ids: list[ParticipantID] = []
        for raw_participant_id in (stage.settings or {}).get(
            'builder_fixed_participant_ids', []
        ):
            try:
                fixed_participant_ids.append(
                    ParticipantID(UUID(str(raw_participant_id)))
                )
            except ValueError:
                continue

        if not fixed_participant_ids:
            return Err('Builder-Gruppen-Teilnehmerliste ist leer.')

        ready_participants = domain_service.select_ready_participants(
            all_tournament_participants
        )
        ready_participants_by_id = {
            participant.id: participant for participant in ready_participants
        }
        selected_participants = [
            ready_participants_by_id[participant_id]
            for participant_id in fixed_participant_ids
            if participant_id in ready_participants_by_id
        ]
        if len(selected_participants) < 2:
            return Err('Not enough ready participants for this builder group.')
        return Ok(selected_participants)

    if source_mode == 'stage_match_qualifiers':
        source_stage_ids = _parse_source_stage_ids(
            (stage.settings or {}).get('qualifier_source_stage_ids', [])
        )
        if not source_stage_ids:
            return Err(
                'No source stages configured. Configure qualifier source stages first.'
            )
        if stage.id in source_stage_ids:
            return Err('A stage cannot use itself as qualifier source.')

        try:
            top_n_per_match = int(
                (stage.settings or {}).get('qualifier_top_n_per_match') or 0
            )
        except (TypeError, ValueError):
            top_n_per_match = 0
        if top_n_per_match < 1 or top_n_per_match > 16:
            return Err('Qualifier top count per match is invalid.')

        unique_source_stage_ids = list(dict.fromkeys(source_stage_ids))
        db_source_stages = db.session.scalars(
            select(DbNetsessionTourneyStage)
            .filter_by(tournament_id=tournament_id)
            .filter(DbNetsessionTourneyStage.id.in_(unique_source_stage_ids))
            .order_by(DbNetsessionTourneyStage.order_no.asc())
        ).all()
        if len(db_source_stages) != len(unique_source_stage_ids):
            return Err('At least one configured source stage does not exist.')

        selected_participant_ids: list[ParticipantID] = []
        for db_source_stage in db_source_stages:
            ranked_participant_ids_by_match_result = (
                _get_ranked_participant_ids_by_match_for_stage(
                    db_source_stage.id,
                    tournament_id,
                    top_n_per_match=top_n_per_match,
                )
            )
            if ranked_participant_ids_by_match_result.is_err():
                message = ranked_participant_ids_by_match_result.unwrap_err()
                if message.endswith('is not fully completed yet.'):
                    message = (
                        'ist noch nicht vollständig abgeschlossen. '
                        'Schließe zuerst alle Vorrunden-Matches ab.'
                    )
                return Err(
                    f'Source stage "{db_source_stage.name}": {message}'
                )

            selected_participant_ids.extend(
                ranked_participant_ids_by_match_result.unwrap()
            )

        participants_by_id = get_participants_by_ids(
            party_id, set(selected_participant_ids)
        )
        participants = [
            participants_by_id[participant_id]
            for participant_id in selected_participant_ids
            if participant_id in participants_by_id
        ]
        participants = domain_service.select_ready_participants(participants)
        if len(participants) < 2:
            return Err(
                'Not enough qualified participants for this stage. '
                'Adjust source stages or top count.'
            )

        return Ok(participants)

    if source_mode != 'stage_qualifiers':
        return Ok(eligible_participants)

    source_stage_ids = _parse_source_stage_ids(
        (stage.settings or {}).get('qualifier_source_stage_ids', [])
    )
    if not source_stage_ids:
        return Err(
            'No source stages configured. Configure qualifier source stages first.'
        )
    if stage.id in source_stage_ids:
        return Err('A stage cannot use itself as qualifier source.')

    selection_mode = (stage.settings or {}).get(
        'qualifier_selection_mode', 'per_stage'
    )
    if selection_mode not in {'per_stage', 'per_group'}:
        return Err('Qualifier selection mode is invalid.')

    unique_source_stage_ids = list(dict.fromkeys(source_stage_ids))
    db_source_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyStage.id.in_(unique_source_stage_ids))
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()
    if len(db_source_stages) != len(unique_source_stage_ids):
        return Err('At least one configured source stage does not exist.')

    selected_participant_ids: list[ParticipantID] = []
    for db_source_stage in db_source_stages:
        qualifier_top_n_result = _get_effective_qualifier_top_n_for_source_stage(
            stage,
            db_source_stage,
            tournament_id,
            selection_mode=selection_mode,
        )
        if qualifier_top_n_result.is_err():
            return Err(
                f'Source stage "{db_source_stage.name}": '
                f'{qualifier_top_n_result.unwrap_err()}'
            )
        top_n = qualifier_top_n_result.unwrap()

        if selection_mode == 'per_group':
            ranked_group_participant_ids_result = (
                _get_ranked_participant_ids_by_group_for_stage(
                    db_source_stage.id,
                    tournament_id,
                )
            )
            if ranked_group_participant_ids_result.is_err():
                message = ranked_group_participant_ids_result.unwrap_err()
                if message.endswith('is not fully completed yet.'):
                    message = (
                        'ist noch nicht vollständig abgeschlossen. '
                        'Schließe zuerst alle Vorrunden-Matches ab.'
                    )
                return Err(
                    f'Source stage "{db_source_stage.name}": '
                    f'{message}'
                )

            for ranked_group_participant_ids in (
                ranked_group_participant_ids_result.unwrap()
            ):
                if len(ranked_group_participant_ids) < top_n:
                    return Err(
                        f'Source stage "{db_source_stage.name}" has a group with '
                        f'only {len(ranked_group_participant_ids)} ranked '
                        f'participants, but top {top_n} per group is required.'
                    )

                selected_participant_ids.extend(
                    ranked_group_participant_ids[:top_n]
                )
        else:
            ranked_participant_ids_result = _get_ranked_participant_ids_for_stage(
                db_source_stage.id, tournament_id
            )
            if ranked_participant_ids_result.is_err():
                message = ranked_participant_ids_result.unwrap_err()
                if message.endswith('is not fully completed yet.'):
                    message = (
                        'ist noch nicht vollständig abgeschlossen. '
                        'Schließe zuerst alle Vorrunden-Matches ab.'
                    )
                return Err(
                    f'Source stage "{db_source_stage.name}": '
                    f'{message}'
                )

            ranked_participant_ids = ranked_participant_ids_result.unwrap()
            if len(ranked_participant_ids) < top_n:
                return Err(
                    f'Source stage "{db_source_stage.name}" has only '
                    f'{len(ranked_participant_ids)} ranked participants, '
                    f'but top {top_n} is required.'
                )

            selected_participant_ids.extend(ranked_participant_ids[:top_n])

    deduplicated_participant_ids = list(dict.fromkeys(selected_participant_ids))
    participants_by_id = get_participants_by_ids(
        party_id, set(deduplicated_participant_ids)
    )
    participants = [
        participants_by_id[participant_id]
        for participant_id in deduplicated_participant_ids
        if participant_id in participants_by_id
    ]
    participants = (
        domain_service.select_ready_participants(participants)
        if is_stage_builder_v1_stage
        else domain_service.select_bracket_ready_participants(participants)
    )

    if len(participants) < 2:
        return Err(
            'Not enough qualified participants for this stage. '
            'Adjust source stages or top count.'
        )

    return Ok(participants)


def _get_ranked_participant_ids_by_match_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
    *,
    top_n_per_match: int,
) -> Result[list[ParticipantID], str]:
    if top_n_per_match < 1:
        return Err('qualifier top count per match is invalid.')

    db_stage = db.session.get(DbNetsessionTourneyStage, stage_id)
    if db_stage is None:
        return Err('does not exist.')

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(stage_id=stage_id, tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return Err('contains no generated matches yet.')

    if any(db_match.state != MatchState.completed.value for db_match in db_matches):
        return Err('is not fully completed yet.')

    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(
                [db_match.id for db_match in db_matches]
            )
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = defaultdict(
        list
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    ranked_participant_ids: list[ParticipantID] = []
    for db_match in db_matches:
        ranked_participant_ids.extend(
            _get_ffa_single_elimination_qualifier_ids(
                db_match.id,
                sorted(
                    slots_by_match_id.get(db_match.id, []),
                    key=lambda db_slot: db_slot.slot_no,
                ),
                top_n_per_match,
            )
        )

    if not ranked_participant_ids:
        return Err('contains no rankable participants.')

    return Ok(ranked_participant_ids)


def _is_stage_builder_v1_main_stage(stage: Stage) -> bool:
    return (
        (stage.settings or {}).get('builder_kind') == STAGE_BUILDER_KIND_V1
        and (stage.settings or {}).get('builder_role') == 'main'
    )


def _is_stage_builder_v1_preliminary_stage(stage: Stage) -> bool:
    return (
        (stage.settings or {}).get('builder_kind') == STAGE_BUILDER_KIND_V1
        and (stage.settings or {}).get('builder_role') == 'preliminary'
    )


def _is_stage_builder_v1_main_stage_with_locked_qualifier_seeding(
    stage: Stage,
) -> bool:
    settings = stage.settings or {}
    return (
        settings.get('builder_kind') == STAGE_BUILDER_KIND_V1
        and settings.get('builder_role') == 'main'
        and bool(settings.get('builder_preliminary_stage_id'))
    )


def _get_stage_builder_main_stage_size(stage: Stage) -> int | None:
    raw_value = (stage.settings or {}).get('builder_main_stage_size')
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed in STAGE_BUILDER_MAIN_STAGE_SIZES else None


def _get_effective_qualifier_top_n_for_source_stage(
    stage: Stage,
    db_source_stage: DbNetsessionTourneyStage,
    tournament_id: TournamentID,
    *,
    selection_mode: str,
) -> Result[int, str]:
    if not (stage.settings or {}).get('builder_auto_qualifier_count'):
        raw_top_n = (stage.settings or {}).get('qualifier_top_n', 1)
        try:
            top_n = int(raw_top_n)
        except (TypeError, ValueError):
            return Err('Qualifier top count is invalid.')
        if top_n < 1 or top_n > 128:
            return Err('Qualifier top count must be between 1 and 128.')
        return Ok(top_n)

    main_stage_size = _get_stage_builder_main_stage_size(stage)
    if main_stage_size is None:
        return Err('Builder main stage size is invalid.')

    if selection_mode == 'per_stage':
        return Ok(main_stage_size)

    if db_source_stage.type != StageType.round_robin_groups.value:
        return Err(
            'Automatic per-group qualifier counts require a Round Robin Groups source stage.'
        )

    ranked_group_participant_ids_result = _get_ranked_participant_ids_by_group_for_stage(
        db_source_stage.id,
        tournament_id,
    )
    if ranked_group_participant_ids_result.is_err():
        return Err(ranked_group_participant_ids_result.unwrap_err())

    ranked_groups = ranked_group_participant_ids_result.unwrap()
    group_count = len(ranked_groups)
    if group_count < 1:
        return Err('contains no ranked groups.')
    if main_stage_size % group_count != 0:
        return Err(
            'cannot distribute qualifiers evenly from the generated groups to the configured main stage size.'
        )

    top_n = main_stage_size // group_count
    if top_n < 1:
        return Err('Qualifier top count is invalid.')

    return Ok(top_n)


def _get_ranked_participant_ids_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[list[ParticipantID], str]:
    ranking_data_result = _build_stage_ranking_data(stage_id, tournament_id)
    if ranking_data_result.is_err():
        return Err(ranking_data_result.unwrap_err())

    ranking_data = ranking_data_result.unwrap()
    ranked_participant_ids = _sort_ranked_participant_ids(
        ranking_data.rows_by_participant_id,
        stage_type=ranking_data.db_stage.type,
        head_to_head_winner_id_by_pair=(
            ranking_data.head_to_head_winner_id_by_pair
        ),
        is_ffa_scoring_stage=ranking_data.is_ffa_scoring_stage,
    )

    if not ranked_participant_ids:
        return Err('contains no rankable participants.')

    return Ok(ranked_participant_ids)


def _get_ranked_participant_ids_by_group_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[list[list[ParticipantID]], str]:
    ranking_data_result = _build_stage_ranking_data(stage_id, tournament_id)
    if ranking_data_result.is_err():
        return Err(ranking_data_result.unwrap_err())

    ranking_data = ranking_data_result.unwrap()
    if ranking_data.db_stage.type != StageType.round_robin_groups.value:
        return Err(
            'group-based qualifiers are only supported for Round Robin Groups.'
        )

    connected_participant_ids_by_participant_id: dict[
        ParticipantID, set[ParticipantID]
    ] = defaultdict(set)
    first_match_no_by_participant_id: dict[ParticipantID, int] = {}

    for db_match in ranking_data.db_matches:
        match_participant_ids = [
            participant_id
            for participant_id in {
                db_slot.participant_id
                for db_slot in ranking_data.slots_by_match_id.get(db_match.id, [])
                if db_slot.participant_id is not None
            }
        ]
        if not match_participant_ids:
            continue

        for participant_id in match_participant_ids:
            current_first_match_no = first_match_no_by_participant_id.get(
                participant_id
            )
            if (
                current_first_match_no is None
                or db_match.match_no < current_first_match_no
            ):
                first_match_no_by_participant_id[participant_id] = (
                    db_match.match_no
                )

        for index, participant_id in enumerate(match_participant_ids):
            for other_participant_id in match_participant_ids[index + 1 :]:
                connected_participant_ids_by_participant_id[
                    participant_id
                ].add(other_participant_id)
                connected_participant_ids_by_participant_id[
                    other_participant_id
                ].add(participant_id)

    visited_participant_ids: set[ParticipantID] = set()
    ranked_group_participant_ids: list[tuple[int, list[ParticipantID]]] = []

    for participant_id in ranking_data.rows_by_participant_id:
        if participant_id in visited_participant_ids:
            continue

        stack = [participant_id]
        group_participant_ids: set[ParticipantID] = set()
        while stack:
            current_participant_id = stack.pop()
            if current_participant_id in visited_participant_ids:
                continue

            visited_participant_ids.add(current_participant_id)
            group_participant_ids.add(current_participant_id)
            stack.extend(
                connected_participant_ids_by_participant_id.get(
                    current_participant_id, set()
                )
            )

        group_rows_by_participant_id = {
            group_participant_id: ranking_data.rows_by_participant_id[
                group_participant_id
            ]
            for group_participant_id in group_participant_ids
        }
        sorted_group_participant_ids = _sort_ranked_participant_ids(
            group_rows_by_participant_id,
            stage_type=ranking_data.db_stage.type,
            head_to_head_winner_id_by_pair=(
                ranking_data.head_to_head_winner_id_by_pair
            ),
            is_ffa_scoring_stage=ranking_data.is_ffa_scoring_stage,
        )
        first_match_no = min(
            first_match_no_by_participant_id.get(
                group_participant_id, 999_999
            )
            for group_participant_id in group_participant_ids
        )
        ranked_group_participant_ids.append(
            (first_match_no, sorted_group_participant_ids)
        )

    ranked_group_participant_ids.sort(key=lambda item: item[0])

    return Ok(
        [
            sorted_group_participant_ids
            for _, sorted_group_participant_ids in ranked_group_participant_ids
        ]
    )


def _build_stage_ranking_data(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[_StageRankingData, str]:
    db_stage = db.session.get(DbNetsessionTourneyStage, stage_id)
    if db_stage is None:
        return Err('does not exist.')

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(stage_id=stage_id, tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return Err('no matches generated yet.')

    if any(match.state != MatchState.completed.value for match in db_matches):
        return Err('is not fully completed yet.')

    match_ids = [match.id for match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(match_ids)
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    participant_ids: set[ParticipantID] = set()
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)
        if db_slot.participant_id is not None:
            participant_ids.add(db_slot.participant_id)

    if not participant_ids:
        return Err('contains no participants.')

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
    ).all()
    db_participant_by_id = {
        participant.id: participant for participant in db_participants
    }

    rows_by_participant_id: dict[ParticipantID, dict[str, Any]] = {}
    for participant_id in participant_ids:
        db_participant = db_participant_by_id.get(participant_id)
        if db_participant is None:
            continue

        rows_by_participant_id[participant_id] = {
            'total_points': 0,
            'points': 0,
            'wins': 0,
            'losses': 0,
            'match_points': 0,
            'round_wins': 0,
            'round_losses': 0,
            'round_diff': 0,
            'buchholz': 0,
            'opponent_wl_sum': 0,
            'second_order_sos': 0,
            'kills': 0,
            'placement': None,
            'seed': db_participant.seed,
            'created_at': db_participant.created_at,
        }

    is_ffa_scoring_stage = db_stage.type in {
        StageType.ffa_simple.value,
        StageType.ffa_single_elimination.value,
        StageType.ffa_flatout2_single_elimination.value,
    }
    is_swiss_stage = db_stage.type == StageType.swiss.value
    points_per_kill = _get_ffa_points_per_kill(dict(db_stage.settings_json or {}))

    db_results = db.session.scalars(
        select(DbNetsessionTourneyMatchResult).filter(
            DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
        )
    ).all()
    opponent_ids_by_participant_id: dict[ParticipantID, list[ParticipantID]] = (
        defaultdict(list)
    )
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ] = {}
    for db_result in db_results:
        db_match_slots = slots_by_match_id.get(db_result.match_id, [])
        real_match_slots = [
            db_slot
            for db_slot in db_match_slots
            if db_slot.participant_id is not None
        ]
        real_participant_ids = [
            db_slot.participant_id
            for db_slot in real_match_slots
            if db_slot.participant_id is not None
        ]
        winner_participant_id = None
        if db_result.winner_slot is not None:
            winner_participant_id = next(
                (
                    slot.participant_id
                    for slot in db_match_slots
                    if slot.slot_no == db_result.winner_slot
                ),
                None,
            )

        placement_by_slot_no: dict[int, int] = {}
        points_by_slot_no: dict[int, int] = {}
        if is_ffa_scoring_stage:
            raw_ranking = db_result.ranking_json or {}
            raw_placements = raw_ranking.get('placements')
            if isinstance(raw_placements, dict):
                for db_slot in db_match_slots:
                    raw_value = raw_placements.get(str(db_slot.slot_no))
                    if raw_value is None:
                        raw_value = raw_placements.get(db_slot.slot_no)
                    try:
                        placement_by_slot_no[db_slot.slot_no] = int(raw_value)
                    except (TypeError, ValueError):
                        continue
            raw_points = raw_ranking.get('points')
            if isinstance(raw_points, dict):
                for db_slot in db_match_slots:
                    raw_value = raw_points.get(str(db_slot.slot_no))
                    if raw_value is None:
                        raw_value = raw_points.get(db_slot.slot_no)
                    try:
                        points_by_slot_no[db_slot.slot_no] = int(raw_value)
                    except (TypeError, ValueError):
                        continue

        score_slots = _parse_match_result_slot_scores(
            real_match_slots,
            db_result.score_json,
            winner_slot=db_result.winner_slot,
        )
        is_walkover_result = _is_walkover_score_json(db_result.score_json)

        if (
            len(real_participant_ids) == 2
            and winner_participant_id in real_participant_ids
            and not (is_swiss_stage and is_walkover_result)
        ):
            participant_a, participant_b = real_participant_ids
            opponent_ids_by_participant_id[participant_a].append(
                participant_b
            )
            opponent_ids_by_participant_id[participant_b].append(
                participant_a
            )
            head_to_head_winner_id_by_pair[
                frozenset(real_participant_ids)
            ] = winner_participant_id

        for db_slot in db_match_slots:
            participant_id = db_slot.participant_id
            if participant_id is None:
                continue

            row = rows_by_participant_id.get(participant_id)
            if row is None:
                continue

            if is_ffa_scoring_stage:
                row['points'] += points_by_slot_no.get(db_slot.slot_no, 0)
                raw_kills = score_slots.get(str(db_slot.slot_no))
                if raw_kills is None:
                    raw_kills = score_slots.get(db_slot.slot_no)
                try:
                    row['kills'] += int(raw_kills)
                except (TypeError, ValueError):
                    pass
                row['total_points'] = row['points'] + (
                    row['kills'] * points_per_kill
                )

                placement = placement_by_slot_no.get(db_slot.slot_no)
                if (
                    placement is not None
                    and (
                        row['placement'] is None
                        or placement < row['placement']
                    )
                ):
                    row['placement'] = placement

            if (
                winner_participant_id is None
                or len(real_participant_ids) < 2
            ):
                continue

            if participant_id == winner_participant_id:
                row['wins'] += 1
                row['match_points'] += 3
            else:
                row['losses'] += 1

            if len(real_participant_ids) != 2:
                continue

            if is_swiss_stage and is_walkover_result:
                continue

            raw_round_wins = score_slots.get(str(db_slot.slot_no))
            if raw_round_wins is None:
                raw_round_wins = score_slots.get(db_slot.slot_no)
            round_wins = _parse_numeric_score_value(raw_round_wins)

            round_losses = sum(
                _parse_numeric_score_value(
                    score_slots.get(str(other_slot.slot_no))
                    if score_slots.get(str(other_slot.slot_no)) is not None
                    else score_slots.get(other_slot.slot_no)
                )
                for other_slot in real_match_slots
                if other_slot.slot_no != db_slot.slot_no
            )
            row['round_wins'] += round_wins
            row['round_losses'] += round_losses
            row['round_diff'] = row['round_wins'] - row['round_losses']

    for participant_id, row in rows_by_participant_id.items():
        row['buchholz'] = sum(
            rows_by_participant_id.get(opponent_id, {}).get('wins', 0)
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )
        row['opponent_wl_sum'] = sum(
            rows_by_participant_id.get(opponent_id, {}).get('wins', 0)
            - rows_by_participant_id.get(opponent_id, {}).get('losses', 0)
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )
    for participant_id, row in rows_by_participant_id.items():
        row['second_order_sos'] = sum(
            rows_by_participant_id.get(opponent_id, {}).get(
                'opponent_wl_sum', 0
            )
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )

    return Ok(
        _StageRankingData(
            db_stage=db_stage,
            db_matches=db_matches,
            slots_by_match_id=slots_by_match_id,
            rows_by_participant_id=rows_by_participant_id,
            head_to_head_winner_id_by_pair=head_to_head_winner_id_by_pair,
            opponent_ids_by_participant_id=opponent_ids_by_participant_id,
            is_ffa_scoring_stage=is_ffa_scoring_stage,
        )
    )


def _parse_numeric_score_value(value: Any) -> int:
    if value is None:
        return 0

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _is_walkover_score_json(score_json: dict[str, Any] | None) -> bool:
    if not isinstance(score_json, dict):
        return False

    return bool(score_json.get('walkover'))


def _parse_match_result_slot_scores(
    slots: list[DbNetsessionTourneyMatchSlot],
    score_json: dict[str, Any] | None,
    *,
    winner_slot: int | None,
) -> dict[int, str]:
    if not slots or not isinstance(score_json, dict):
        return {}

    raw_slots = score_json.get('slots')
    if isinstance(raw_slots, dict):
        parsed_scores = {}
        for slot in slots:
            raw_value = raw_slots.get(str(slot.slot_no))
            if raw_value is None:
                raw_value = raw_slots.get(slot.slot_no)
            if raw_value is None:
                continue

            normalized = str(raw_value).strip()
            if not normalized:
                continue

            parsed_scores[slot.slot_no] = normalized

        if parsed_scores:
            return parsed_scores

    raw_display = score_json.get('display')
    if isinstance(raw_display, str):
        display = raw_display.strip().replace(' ', '')
        if display:
            delimiter = next(
                (
                    candidate
                    for candidate in [':', '-', '/']
                    if candidate in display
                ),
                None,
            )
            if delimiter is not None:
                parts = display.split(delimiter)
                if len(parts) == len(slots) and all(
                    part.isdigit() for part in parts
                ):
                    normalized_parts = list(parts)
                    if len(slots) == 2 and winner_slot is not None:
                        left = int(parts[0])
                        right = int(parts[1])
                        if left != right:
                            first_slot_no = slots[0].slot_no
                            second_slot_no = slots[1].slot_no
                            winner_has_lower_score = (
                                winner_slot == first_slot_no
                                and left < right
                            ) or (
                                winner_slot == second_slot_no
                                and right < left
                            )
                            if winner_has_lower_score:
                                normalized_parts = [parts[1], parts[0]]

                    return {
                        slot.slot_no: normalized_parts[index]
                        for index, slot in enumerate(slots)
                    }

    if winner_slot is None or len(slots) != 2:
        return {}

    return {
        slots[0].slot_no: '1' if winner_slot == slots[0].slot_no else '0',
        slots[1].slot_no: '1' if winner_slot == slots[1].slot_no else '0',
    }


def _sort_ranked_participant_ids(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    *,
    stage_type: str | None = None,
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ] | None = None,
    is_ffa_scoring_stage: bool,
) -> list[ParticipantID]:
    if not is_ffa_scoring_stage and stage_type == StageType.swiss.value:
        swiss_head_to_head_scores = _build_swiss_head_to_head_scores(
            rows_by_participant_id, head_to_head_winner_id_by_pair
        )
        return [
            participant_id
            for participant_id, _ in sorted(
                rows_by_participant_id.items(),
                key=lambda item: (
                    -item[1].get('wins', 0),
                    item[1].get('losses', 0),
                    -item[1].get('buchholz', 0),
                    -item[1].get('opponent_wl_sum', 0),
                    -item[1].get('second_order_sos', 0),
                    -swiss_head_to_head_scores.get(item[0], 0),
                    -item[1].get('round_diff', 0),
                    -item[1].get('round_wins', 0),
                    (
                        item[1]['seed']
                        if item[1]['seed'] is not None
                        else 999_999
                    ),
                    item[1]['created_at'],
                ),
            )
        ]

    if (
        not is_ffa_scoring_stage
        and stage_type == StageType.round_robin_groups.value
    ):
        tie_break_values_by_participant_id: dict[
            ParticipantID, tuple[int, int, int, int]
        ] = {}
        participants_by_points: dict[int, list[ParticipantID]] = defaultdict(list)
        for participant_id, row in rows_by_participant_id.items():
            participants_by_points[row.get('match_points', 0)].append(
                participant_id
            )

        for participant_ids in participants_by_points.values():
            direct_compare_scores = {
                participant_id: 0 for participant_id in participant_ids
            }
            if (
                len(participant_ids) == 2
                and head_to_head_winner_id_by_pair is not None
            ):
                winner_id = head_to_head_winner_id_by_pair.get(
                    frozenset(participant_ids)
                )
                if winner_id in direct_compare_scores:
                    direct_compare_scores[winner_id] = 1

            for participant_id in participant_ids:
                row = rows_by_participant_id[participant_id]
                tie_break_values_by_participant_id[participant_id] = (
                    row.get('match_points', 0),
                    direct_compare_scores[participant_id],
                    row.get('round_diff', 0),
                    row.get('round_wins', 0),
                )

        return [
            participant_id
            for participant_id, _ in sorted(
                rows_by_participant_id.items(),
                key=lambda item: (
                    -tie_break_values_by_participant_id[item[0]][0],
                    -tie_break_values_by_participant_id[item[0]][1],
                    -tie_break_values_by_participant_id[item[0]][2],
                    -tie_break_values_by_participant_id[item[0]][3],
                    (
                        item[1]['seed']
                        if item[1]['seed'] is not None
                        else 999_999
                    ),
                    item[1]['created_at'],
                ),
            )
        ]

    return [
        participant_id
        for participant_id, _ in sorted(
            rows_by_participant_id.items(),
            key=lambda item: (
                (
                    -item[1]['total_points']
                    if is_ffa_scoring_stage
                    else 0
                ),
                (
                    -item[1]['points']
                    if is_ffa_scoring_stage
                    else 0
                ),
                (
                    -item[1]['kills']
                    if is_ffa_scoring_stage
                    else 0
                ),
                (
                    (
                        item[1]['placement']
                        if item[1]['placement'] is not None
                        else 999_999
                    )
                    if is_ffa_scoring_stage
                    else 0
                ),
                -item[1]['wins'],
                item[1]['losses'],
                item[1]['seed'] if item[1]['seed'] is not None else 999_999,
                item[1]['created_at'],
            ),
        )
    ]


def _build_swiss_head_to_head_scores(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ]
    | None,
) -> dict[ParticipantID, int]:
    scores_by_participant_id = {
        participant_id: 0 for participant_id in rows_by_participant_id
    }
    if head_to_head_winner_id_by_pair is None:
        return scores_by_participant_id

    participant_ids_by_base_tie_values: dict[
        tuple[int, int, int, int, int], list[ParticipantID]
    ] = defaultdict(list)
    for participant_id, row in rows_by_participant_id.items():
        participant_ids_by_base_tie_values[
            (
                row.get('wins', 0),
                row.get('losses', 0),
                row.get('buchholz', 0),
                row.get('opponent_wl_sum', 0),
                row.get('second_order_sos', 0),
            )
        ].append(participant_id)

    for participant_ids in participant_ids_by_base_tie_values.values():
        if len(participant_ids) != 2:
            continue

        winner_id = head_to_head_winner_id_by_pair.get(
            frozenset(participant_ids)
        )
        if winner_id in scores_by_participant_id:
            scores_by_participant_id[winner_id] = 1

    return scores_by_participant_id


def _get_ffa_points_per_kill(settings: dict[str, Any] | None) -> int:
    if not isinstance(settings, dict):
        return 1

    raw_value = settings.get('points_per_kill', 1)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 1

    return max(0, value)


def get_matches_for_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    only_open: bool = False,
) -> list[Match]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return []

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()

    match_ids = [db_match.id for db_match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        _get_participant_status_value_by_participant_id_for_slots(db_slots)
    )

    matches = [
        _db_match_to_model_with_effective_state(
            item,
            tournament_status=db_tournament.status,
            db_match_slots=slots_by_match_id.get(item.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        )
        for item in db_matches
    ]
    if only_open:
        matches = [
            match
            for match in matches
            if match.state
            in {
                MatchState.ready,
                MatchState.in_progress,
                MatchState.pending_confirmation,
                MatchState.needs_admin_review,
            }
        ]

    return matches


def get_open_matches_for_party(party_id: PartyID) -> list[Match]:
    stmt = (
        select(DbNetsessionTourneyMatch)
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyMatch.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(DbNetsessionTourneyTournament.status == TournamentStatus.live.value)
        .filter(
            DbNetsessionTourneyMatch.state.in_(
                [
                    MatchState.ready.value,
                    MatchState.in_progress.value,
                    MatchState.pending_confirmation.value,
                    MatchState.needs_admin_review.value,
                ]
            )
        )
        .order_by(DbNetsessionTourneyMatch.scheduled_at.asc().nullslast())
    )
    db_matches = db.session.scalars(stmt).all()
    if not db_matches:
        return []

    match_ids = [db_match.id for db_match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        _get_participant_status_value_by_participant_id_for_slots(db_slots)
    )

    return [
        match
        for match in (
            _db_match_to_model_with_effective_state(
                db_match,
                tournament_status=TournamentStatus.live.value,
                db_match_slots=slots_by_match_id.get(db_match.id, []),
                participant_status_value_by_participant_id=participant_status_value_by_participant_id,
            )
            for db_match in db_matches
        )
        if match.state
        in {
            MatchState.ready,
            MatchState.in_progress,
            MatchState.pending_confirmation,
            MatchState.needs_admin_review,
        }
    ]


def find_match_for_tournament(
    party_id: PartyID, tournament_id: TournamentID, match_id: MatchID
) -> Match | None:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return None

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch).filter_by(
            id=match_id,
            tournament_id=tournament_id,
        )
    )
    if db_match is None:
        return None

    db_match_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    participant_status_value_by_participant_id = (
        _get_participant_status_value_by_participant_id_for_slots(db_match_slots)
    )

    return _db_match_to_model_with_effective_state(
        db_match,
        tournament_status=db_tournament.status,
        db_match_slots=db_match_slots,
        participant_status_value_by_participant_id=participant_status_value_by_participant_id,
    )


def get_match_slots_for_match(match_id: MatchID) -> list[MatchSlot]:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    return [_db_match_slot_to_model(item) for item in db_slots]


def get_match_result_for_match(match_id: MatchID) -> MatchResult | None:
    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is None:
        return None

    return _db_match_result_to_model(db_result)


def can_user_access_match_chat(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    user_id: UserID,
    *,
    is_admin_or_referee: bool = False,
) -> bool:
    if is_admin_or_referee:
        return True

    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return False

    match_exists = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            id=match_id,
            tournament_id=tournament_id,
        )
    )
    if not match_exists:
        return False

    match_participant_ids = {
        participant_id
        for participant_id in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot.participant_id).filter_by(
                match_id=match_id
            )
        ).all()
        if participant_id is not None
    }
    if not match_participant_ids:
        return False

    own_participant_ids = set(
        db.session.scalars(
            select(DbNetsessionTourneyParticipant.id)
            .filter_by(tournament_id=tournament_id)
            .filter(
                DbNetsessionTourneyParticipant.status.in_(
                    ACTIVE_PARTICIPANT_STATUS_VALUES
                )
            )
            .filter(
                or_(
                    DbNetsessionTourneyParticipant.user_id == user_id,
                    DbNetsessionTourneyParticipant.manager_user_id == user_id,
                )
            )
        ).all()
    )

    team_participant_ids = set(
        db.session.scalars(
            select(DbNetsessionTourneyTeamMember.participant_id)
            .join(
                DbNetsessionTourneyParticipant,
                DbNetsessionTourneyParticipant.id
                == DbNetsessionTourneyTeamMember.participant_id,
            )
            .filter(DbNetsessionTourneyParticipant.tournament_id == tournament_id)
            .filter(
                DbNetsessionTourneyParticipant.status.in_(
                    ACTIVE_PARTICIPANT_STATUS_VALUES
                )
            )
            .filter(DbNetsessionTourneyTeamMember.user_id == user_id)
        ).all()
    )

    return bool((own_participant_ids | team_participant_ids) & match_participant_ids)


def get_match_chat_messages(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
) -> list[MatchChatMessage]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return []

    db_messages = db.session.scalars(
        select(DbNetsessionTourneyMatchChatMessage)
        .filter_by(
            tournament_id=tournament_id,
            match_id=match_id,
        )
        .order_by(DbNetsessionTourneyMatchChatMessage.created_at.asc())
    ).all()
    return [_db_match_chat_message_to_model(item) for item in db_messages]


def post_match_chat_message(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    actor_user_id: UserID,
    body: str,
    *,
    actor_is_admin_or_referee: bool = False,
) -> Result[MatchChatMessage, str]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch).filter_by(
            id=match_id, tournament_id=tournament_id
        )
    )
    if db_match is None:
        return Err('Unknown match.')

    if not can_user_access_match_chat(
        party_id,
        tournament_id,
        match_id,
        actor_user_id,
        is_admin_or_referee=actor_is_admin_or_referee,
    ):
        return Err('You are not allowed to post in this match chat.')

    body = body.strip()
    if not body:
        return Err('Message cannot be empty.')
    if len(body) > 2000:
        return Err('Message is too long.')

    now = datetime.utcnow()
    db_message = DbNetsessionTourneyMatchChatMessage(
        generate_uuid7(),
        tournament_id,
        match_id,
        actor_user_id,
        body,
        now,
    )
    db.session.add(db_message)

    db_tournament = db.session.get(DbNetsessionTourneyTournament, tournament_id)

    _append_audit_log(
        actor_user_id=actor_user_id,
        object_type='match',
        object_id=match_id,
        action='chat_message_posted',
        payload={'body_preview': body[:120]},
        created_at=now,
    )
    _append_notifications_for_match(
        db_match,
        actor_user_id=actor_user_id,
        kind='chat_message_posted',
        payload={
            'match_id': str(match_id),
            'body_preview': body[:120],
            'url': (
                _build_site_match_path(db_tournament.slug, match_id)
                if db_tournament is not None
                else None
            ),
        },
    )

    db.session.commit()
    return Ok(_db_match_chat_message_to_model(db_message))


def get_match_timeline_entries(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
) -> list[dict[str, Any]]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return []

    db_entries = db.session.scalars(
        select(DbNetsessionTourneyAuditLog)
        .filter(
            or_(
                (
                    (DbNetsessionTourneyAuditLog.object_type == 'match')
                    & (DbNetsessionTourneyAuditLog.object_id == match_id)
                ),
                (
                    (DbNetsessionTourneyAuditLog.object_type == 'tournament')
                    & (DbNetsessionTourneyAuditLog.object_id == tournament_id)
                    & DbNetsessionTourneyAuditLog.action.in_(
                        [
                            'tournament_published',
                            'tournament_closed',
                            'tournament_canceled',
                        ]
                    )
                ),
            )
        )
        .order_by(DbNetsessionTourneyAuditLog.created_at.asc())
    ).all()

    return [
        {
            'id': entry.id,
            'actor_user_id': entry.actor_user_id,
            'action': entry.action,
            'payload': dict(entry.payload_json or {}),
            'created_at': entry.created_at,
        }
        for entry in db_entries
        if entry.action != 'chat_message_posted'
    ]


def get_match_slots(match_ids: set[MatchID]) -> dict[MatchID, list[MatchSlot]]:
    if not match_ids:
        return {}

    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[MatchSlot]] = defaultdict(list)
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(_db_match_slot_to_model(db_slot))
    return dict(slots_by_match_id)


def get_match_results(match_ids: set[MatchID]) -> dict[MatchID, MatchResult]:
    if not match_ids:
        return {}

    db_results = db.session.scalars(
        select(DbNetsessionTourneyMatchResult).filter(
            DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
        )
    ).all()
    return {item.match_id: _db_match_result_to_model(item) for item in db_results}


def _get_stage_result_report_mode(stage_settings: dict[str, Any] | None) -> str:
    if not stage_settings:
        return RESULT_REPORT_MODE_BOTH_MUST_CONFIRM

    raw_value = stage_settings.get('result_report_mode')
    if raw_value in RESULT_REPORT_MODES:
        return raw_value

    return RESULT_REPORT_MODE_BOTH_MUST_CONFIRM


def _validate_actor_matches_report_mode(
    tournament_mode: TournamentMode,
    stage_result_report_mode: str,
    *,
    actor_is_admin_or_referee: bool,
    actor_slot_no: int | None,
    winner_slot: int | None,
) -> str | None:
    if actor_is_admin_or_referee or tournament_mode != TournamentMode.duel:
        return None

    if stage_result_report_mode == RESULT_REPORT_MODE_BOTH_MUST_CONFIRM:
        return None

    if winner_slot is None:
        return 'A winner must be provided.'
    if actor_slot_no is None:
        return 'Only participants of this match can report a result.'

    if stage_result_report_mode == RESULT_REPORT_MODE_WINNER_CAN_REPORT:
        if actor_slot_no != winner_slot:
            return 'Only the winner can report the result for this stage.'
        return None

    if stage_result_report_mode == RESULT_REPORT_MODE_LOSER_CAN_REPORT:
        if actor_slot_no == winner_slot:
            return 'Only the loser can report the result for this stage.'
        return None

    return None


def _determine_post_report_state(
    tournament_mode: TournamentMode,
    stage_result_report_mode: str,
    *,
    actor_is_admin_or_referee: bool,
    reports_agree: bool,
    conflicting_duel_reports: bool,
) -> MatchState:
    if actor_is_admin_or_referee:
        return MatchState.completed

    if tournament_mode == TournamentMode.ffa:
        return MatchState.needs_admin_review

    if stage_result_report_mode in {
        RESULT_REPORT_MODE_WINNER_CAN_REPORT,
        RESULT_REPORT_MODE_LOSER_CAN_REPORT,
    }:
        return MatchState.completed

    if conflicting_duel_reports:
        return MatchState.needs_admin_review

    if reports_agree:
        return MatchState.completed

    return MatchState.pending_confirmation


def report_result(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    actor_user_id: UserID,
    *,
    idempotency_key: str,
    winner_slot: int | None,
    score: dict[str, Any] | None = None,
    ranking: dict[str, Any] | None = None,
    actor_is_admin_or_referee: bool = False,
    admin_comment: str | None = None,
    reason_code: str | None = None,
    correlation_id: str | None = None,
) -> Result[MatchResult, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id, tournament_id=tournament_id)
        .with_for_update()
    )
    if db_match is None:
        return Err('Unknown match.')

    db_receipt = db.session.scalar(
        select(DbNetsessionTourneyResultReportReceipt).filter_by(
            match_id=match_id,
            idempotency_key=idempotency_key,
        )
    )
    if db_receipt is not None:
        db_existing_result = db.session.get(
            DbNetsessionTourneyMatchResult, db_receipt.result_id
        )
        if db_existing_result is None:
            return Err('Idempotency receipt references unknown result.')
        return Ok(_db_match_result_to_model(db_existing_result))

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None:
        return Err('Unknown stage.')
    stage = _db_stage_to_model(db_stage)
    tournament = _db_tournament_to_model(db_tournament)

    if not actor_is_admin_or_referee:
        if tournament.status != TournamentStatus.live:
            return Err(
                'Match results can only be reported while the tournament is live.'
            )

        if MatchState(db_match.state) not in {
            MatchState.ready,
            MatchState.in_progress,
            MatchState.pending_confirmation,
        }:
            return Err(
                'Result reporting is not allowed in the current match state.'
            )

    if _is_match_marked_as_skipped_double_grand_final(stage, match_id):
        return Err(
            'This match has been canceled because no bracket reset is required.'
        )

    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    participant_ids = {slot.participant_id for slot in db_slots if slot.participant_id}
    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    db_participants_by_id = {
        db_participant.id: db_participant for db_participant in db_participants
    }
    manager_user_ids = {
        participant.manager_user_id
        for participant in db_participants
        if participant.manager_user_id is not None
    }
    manager_user_id_by_slot_no = {
        db_slot.slot_no: (
            db_participants_by_id.get(db_slot.participant_id).manager_user_id
            if db_slot.participant_id is not None
            and db_participants_by_id.get(db_slot.participant_id) is not None
            else None
        )
        for db_slot in db_slots
    }
    actor_slot_no = next(
        (
            slot_no
            for slot_no, manager_user_id in manager_user_id_by_slot_no.items()
            if manager_user_id == actor_user_id
        ),
        None,
    )
    is_match_participant_manager = actor_user_id in manager_user_ids
    if not domain_service.can_actor_report_match_result(
        tournament.mode,
        actor_is_admin_or_referee,
        is_match_participant_manager,
    ):
        return Err('Actor is not allowed to report a result for this match.')

    stage_result_report_mode = _get_stage_result_report_mode(stage.settings)
    report_mode_validation_error = _validate_actor_matches_report_mode(
        tournament.mode,
        stage_result_report_mode,
        actor_is_admin_or_referee=actor_is_admin_or_referee,
        actor_slot_no=actor_slot_no,
        winner_slot=winner_slot,
    )
    if report_mode_validation_error is not None:
        return Err(report_mode_validation_error)

    score_data = score or {}
    ranking_data = ranking or {}
    now = datetime.utcnow()

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is None:
        db_result = DbNetsessionTourneyMatchResult(
            MatchResultID(generate_uuid7()),
            match_id,
            now,
            winner_slot=winner_slot,
            score_json=score_data,
            ranking_json=ranking_data,
            submitted_by_user_id=actor_user_id,
        )
        db.session.add(db_result)
        reports_agree = False
    else:
        reports_agree = (
            db_result.winner_slot == winner_slot
            and db_result.score_json == score_data
            and db_result.ranking_json == ranking_data
            and db_result.submitted_by_user_id != actor_user_id
        )
        if (
            actor_is_admin_or_referee
            and db_result.submitted_by_user_id is not None
            and not admin_comment
        ):
            return Err('Admin corrections require a comment.')

        db_result.winner_slot = winner_slot
        db_result.score_json = score_data
        db_result.ranking_json = ranking_data
        db_result.updated_at = now
        if db_result.submitted_by_user_id is None:
            db_result.submitted_by_user_id = actor_user_id
        if (
            not actor_is_admin_or_referee
            and db_result.submitted_by_user_id != actor_user_id
        ):
            db_result.confirmed_by_user_id = actor_user_id

    conflicting_duel_reports = (
        not actor_is_admin_or_referee
        and tournament.mode == TournamentMode.duel
        and db_result.submitted_by_user_id is not None
        and db_result.submitted_by_user_id != actor_user_id
        and not reports_agree
    )

    new_state = _determine_post_report_state(
        tournament.mode,
        stage_result_report_mode,
        actor_is_admin_or_referee=actor_is_admin_or_referee,
        reports_agree=reports_agree,
        conflicting_duel_reports=conflicting_duel_reports,
    )

    db_match.state = new_state.value
    db_match.reported_by_user_id = actor_user_id
    db_match.updated_at = now
    db_match.lock_version += 1
    if actor_is_admin_or_referee:
        db_match.confirmed_by_admin_id = actor_user_id
        db_result.confirmed_by_admin_id = actor_user_id
        db_result.confirmation_comment = admin_comment

    if not actor_is_admin_or_referee and new_state == MatchState.pending_confirmation:
        db_match.confirmation_deadline_at = now + timedelta(minutes=15)
    else:
        db_match.confirmation_deadline_at = None

    db.session.add(
        DbNetsessionTourneyResultReportReceipt(
            generate_uuid7(),
            match_id,
            idempotency_key,
            db_result.id,
            now,
        )
    )

    if new_state == MatchState.completed:
        winner_participant_id = None
        for db_slot in db_slots:
            if db_slot.slot_no == winner_slot:
                winner_participant_id = db_slot.participant_id
                break
        engine = find_stage_engine(stage.type)
        _advance_stage_from_match(
            tournament_id=tournament_id,
            stage=stage,
            source_match_id=match_id,
            winner_participant_id=winner_participant_id,
            engine=engine,
        )
        if engine is not None:
            _auto_advance_byes(tournament_id, stage, engine=engine)
        _update_optional_double_grand_final_state(
            stage=stage, source_match_id=match_id
        )
    _append_audit_log(
        actor_user_id=actor_user_id,
        object_type='match',
        object_id=match_id,
        action='result_reported',
        payload={
            'winner_slot': winner_slot,
            'score': score_data,
            'ranking': ranking_data,
            'state': new_state.value,
            'reason_code': reason_code,
            'comment': admin_comment,
            'correlation_id': correlation_id,
        },
        created_at=now,
    )

    db.session.commit()
    _append_notification_for_match_report(db_match, stage, actor_user_id)
    if new_state == MatchState.completed:
        enqueue_discord_event(
            party_id,
            tournament_id,
            event_name='match_completed',
            payload=_build_discord_match_completed_payload(
                db_tournament,
                db_match,
                stage,
                db_slots,
                db_participants_by_id,
                winner_slot,
                score_data,
                ranking_data,
            ),
        )
    if new_state == MatchState.completed:
        _auto_generate_builder_main_stages_from_completed_source(
            party_id=party_id,
            tournament_id=tournament_id,
            source_stage_id=stage.id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )

    log.info(
        'netsession_tourney.result_reported',
        tournament_id=str(tournament_id),
        stage_id=str(stage.id),
        match_id=str(match_id),
        actor_user_id=str(actor_user_id),
        correlation_id=correlation_id,
        state=new_state.value,
    )

    return Ok(_db_match_result_to_model(db_result))


def _auto_generate_builder_main_stages_from_completed_source(
    *,
    party_id: PartyID,
    tournament_id: TournamentID,
    source_stage_id: StageID,
    actor_user_id: UserID,
    correlation_id: str | None,
) -> None:
    if not _is_stage_fully_completed(tournament_id, source_stage_id):
        return

    db_candidate_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    for db_stage in db_candidate_stages:
        settings = dict(db_stage.settings_json or {})
        if (
            settings.get('builder_kind') != STAGE_BUILDER_KIND_V1
            or settings.get('builder_role') != 'main'
            or settings.get('participant_source_mode') != 'stage_qualifiers'
        ):
            continue

        source_stage_ids = _parse_source_stage_ids(
            settings.get('qualifier_source_stage_ids', [])
        )
        if source_stage_id not in source_stage_ids:
            continue
        if not source_stage_ids:
            continue
        if not all(
            _is_stage_fully_completed(tournament_id, stage_id)
            for stage_id in source_stage_ids
        ):
            continue
        if _stage_has_assigned_participants(tournament_id, db_stage.id):
            continue
        if _stage_has_reported_results(tournament_id, db_stage.id):
            continue

        initiator = User(
            id=actor_user_id,
            screen_name=None,
            initialized=True,
            suspended=False,
            deleted=False,
            avatar_url='',
        )
        result = generate_stage_matches(
            party_id,
            tournament_id,
            db_stage.id,
            initiator,
            correlation_id=correlation_id,
        )
        if result.is_err():
            log.warning(
                'netsession_tourney.builder_main_auto_generation_failed',
                tournament_id=str(tournament_id),
                source_stage_id=str(source_stage_id),
                target_stage_id=str(db_stage.id),
                reason=result.unwrap_err(),
                correlation_id=correlation_id,
            )
            continue

        log.info(
            'netsession_tourney.builder_main_auto_generated',
            tournament_id=str(tournament_id),
            source_stage_id=str(source_stage_id),
            target_stage_id=str(db_stage.id),
            match_count=len(result.unwrap()),
            correlation_id=correlation_id,
        )


def _is_stage_fully_completed(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    total_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            tournament_id=tournament_id,
            stage_id=stage_id,
        )
    )
    if not total_match_count:
        return False

    incomplete_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id))
        .filter_by(
            tournament_id=tournament_id,
            stage_id=stage_id,
        )
        .filter(DbNetsessionTourneyMatch.state != MatchState.completed.value)
    )
    return int(incomplete_match_count or 0) == 0


def _stage_has_assigned_participants(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    assigned_participant_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatchSlot.id))
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyMatch.id == DbNetsessionTourneyMatchSlot.match_id,
        )
        .filter(
            DbNetsessionTourneyMatch.tournament_id == tournament_id,
            DbNetsessionTourneyMatch.stage_id == stage_id,
            DbNetsessionTourneyMatchSlot.participant_id.is_not(None),
        )
    )
    return bool(assigned_participant_count)


def _stage_has_reported_results(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    result_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatchResult.id))
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyMatch.id == DbNetsessionTourneyMatchResult.match_id,
        )
        .filter(
            DbNetsessionTourneyMatch.tournament_id == tournament_id,
            DbNetsessionTourneyMatch.stage_id == stage_id,
        )
    )
    return bool(result_count)


def delete_match_result_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id, tournament_id=tournament_id)
        .with_for_update()
    )
    if db_match is None:
        return Err('Unknown match.')

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None:
        return Err('Unknown stage.')

    stage = _db_stage_to_model(db_stage)
    if stage.type == StageType.swiss:
        return Err(
            'Deleting stored results is not supported for Swiss stages yet.'
        )

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult)
        .filter_by(match_id=match_id)
        .with_for_update()
    )
    if db_result is None:
        return Err('No stored result exists for this match.')

    blocking_match_id = _find_match_result_delete_blocker(match_id)
    if blocking_match_id is not None:
        db_blocking_match = db.session.get(
            DbNetsessionTourneyMatch, blocking_match_id
        )
        if db_blocking_match is None:
            return Err(
                'Stored result cannot be deleted because a dependent match already has a manually reported result.'
            )

        return Err(
            'Stored result cannot be deleted because a dependent match '
            f'(round {db_blocking_match.round_no}, match {db_blocking_match.match_no}) '
            'already has a manually reported result.'
        )

    deleted_match_ids: set[MatchID] = set()
    _delete_match_result_branch(match_id, deleted_match_ids=deleted_match_ids)

    now = datetime.utcnow()
    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='result_deleted',
        payload={
            'deleted_match_ids': [str(item) for item in sorted(deleted_match_ids)],
            'deleted_match_count': len(deleted_match_ids),
        },
        created_at=now,
    )
    db.session.commit()

    return Ok(None)


def _find_match_result_delete_blocker(
    match_id: MatchID, *, visited: set[MatchID] | None = None
) -> MatchID | None:
    if visited is None:
        visited = set()

    source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id, slot_no=1)
    )
    if source_slot is None:
        return None

    downstream_match_ids = {
        downstream_match_id
        for downstream_match_id in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot.match_id).filter_by(
                source_match_slot_id=source_slot.id
            )
        ).all()
    }

    for downstream_match_id in sorted(downstream_match_ids):
        if downstream_match_id in visited:
            continue

        visited.add(downstream_match_id)
        db_result = db.session.scalar(
            select(DbNetsessionTourneyMatchResult).filter_by(
                match_id=downstream_match_id
            )
        )
        if db_result is None:
            continue

        if db_result.submitted_by_user_id is not None:
            return downstream_match_id

        blocking_match_id = _find_match_result_delete_blocker(
            downstream_match_id, visited=visited
        )
        if blocking_match_id is not None:
            return blocking_match_id

    return None


def _delete_match_result_branch(
    match_id: MatchID,
    *,
    deleted_match_ids: set[MatchID],
    visited: set[MatchID] | None = None,
) -> None:
    if visited is None:
        visited = set()

    if match_id in visited:
        return

    visited.add(match_id)

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id)
        .with_for_update()
    )
    if db_match is None:
        return

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult)
        .filter_by(match_id=match_id)
        .with_for_update()
    )
    if db_result is None:
        return

    source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id, slot_no=1)
    )
    downstream_slots = (
        db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(
                source_match_slot_id=source_slot.id
            )
        ).all()
        if source_slot is not None
        else []
    )
    downstream_match_ids = sorted({db_slot.match_id for db_slot in downstream_slots})

    for downstream_match_id in downstream_match_ids:
        db_downstream_result = db.session.scalar(
            select(DbNetsessionTourneyMatchResult)
            .filter_by(match_id=downstream_match_id)
            .with_for_update()
        )
        if db_downstream_result is None:
            continue

        _delete_match_result_branch(
            downstream_match_id,
            deleted_match_ids=deleted_match_ids,
            visited=visited,
        )

    db.session.execute(
        delete(DbNetsessionTourneyResultReportReceipt).filter_by(match_id=match_id)
    )
    db.session.delete(db_result)
    _reset_match_after_result_delete(db_match)

    affected_downstream_match_ids: set[MatchID] = set()
    for db_slot in downstream_slots:
        if db_slot.participant_id is not None:
            db_slot.participant_id = None
        affected_downstream_match_ids.add(db_slot.match_id)

    for downstream_match_id in affected_downstream_match_ids:
        db_downstream_match = db.session.scalar(
            select(DbNetsessionTourneyMatch)
            .filter_by(id=downstream_match_id)
            .with_for_update()
        )
        if db_downstream_match is None:
            continue

        _reset_match_after_result_delete(db_downstream_match)

    deleted_match_ids.add(match_id)


def _reset_match_after_result_delete(db_match: DbNetsessionTourneyMatch) -> None:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=db_match.id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()

    db_match.state = _calculate_match_state_for_slots(
        tournament_status=_get_tournament_status_value(db_match.tournament_id),
        db_match_slots=db_slots,
    ).value

    db_match.reported_by_user_id = None
    db_match.confirmed_by_admin_id = None
    db_match.confirmation_deadline_at = None
    db_match.dispute_reason_code = None
    db_match.dispute_comment = None
    db_match.updated_at = datetime.utcnow()
    db_match.lock_version += 1


def set_match_slot_participant_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    slot_no: int,
    participant_id: ParticipantID | None,
    initiator: User,
    *,
    comment: str | None = None,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Match assignment is only possible while tournament is in draft.'
        )

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id, tournament_id=tournament_id)
        .with_for_update()
    )
    if db_match is None:
        return Err('Unknown match.')

    if db_match.state in {
        MatchState.completed.value,
        MatchState.in_progress.value,
        MatchState.pending_confirmation.value,
        MatchState.needs_admin_review.value,
        MatchState.disputed.value,
    }:
        return Err(
            'Match slot assignment is only possible for pending/ready matches.'
        )

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is not None:
        return Err('Match slot assignment is not possible after a result exists.')

    db_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id, slot_no=slot_no)
        .with_for_update()
    )
    if db_slot is None:
        return Err('Unknown match slot.')

    # Slots that are fed by previous matches are maintained by bracket logic.
    if db_slot.source_match_slot_id is not None:
        return Err(
            'This slot is linked to a previous match and cannot be edited manually.'
        )

    if participant_id is not None:
        db_participant = db.session.scalar(
            select(DbNetsessionTourneyParticipant)
            .filter_by(id=participant_id, tournament_id=tournament_id)
            .filter(
                DbNetsessionTourneyParticipant.status.in_(
                    ACTIVE_PARTICIPANT_STATUS_VALUES
                )
            )
        )
        if db_participant is None:
            return Err('Unknown participant.')

        duplicate_in_match = db.session.scalar(
            select(DbNetsessionTourneyMatchSlot.id)
            .filter_by(match_id=match_id, participant_id=participant_id)
            .filter(DbNetsessionTourneyMatchSlot.slot_no != slot_no)
        )
        if duplicate_in_match is not None:
            return Err('Participant is already assigned to this match.')

        duplicate_in_round = db.session.scalar(
            select(DbNetsessionTourneyMatchSlot.id)
            .join(
                DbNetsessionTourneyMatch,
                DbNetsessionTourneyMatch.id
                == DbNetsessionTourneyMatchSlot.match_id,
            )
            .filter(DbNetsessionTourneyMatch.stage_id == db_match.stage_id)
            .filter(DbNetsessionTourneyMatch.round_no == db_match.round_no)
            .filter(DbNetsessionTourneyMatchSlot.participant_id == participant_id)
            .filter(DbNetsessionTourneyMatchSlot.match_id != match_id)
        )
        if duplicate_in_round is not None:
            return Err('Participant is already assigned in this round.')

    db_slot.participant_id = participant_id

    previous_state = MatchState(db_match.state)
    db_match_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    next_state = _calculate_match_state_for_slots(
        tournament_status=db_tournament.status,
        db_match_slots=db_match_slots,
    )
    db_match.state = next_state.value
    db_match.updated_at = datetime.utcnow()

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is not None:
        stage = _db_stage_to_model(db_stage)
        _auto_advance_byes(
            tournament_id,
            stage,
            engine=find_stage_engine(stage.type),
        )

    if previous_state != MatchState.ready and next_state == MatchState.ready:
        _enqueue_match_ready_notifications(db_match)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='match_slot_assignment_updated_by_admin',
        payload={
            'slot_no': slot_no,
            'participant_id': (
                str(participant_id) if participant_id is not None else None
            ),
            'comment': comment.strip() if comment else None,
        },
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(None)


def set_flatout2_match_host_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    host_participant_id: ParticipantID | None,
    initiator: User,
) -> Result[Match, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id, tournament_id=tournament_id)
        .with_for_update()
    )
    if db_match is None:
        return Err('Unknown match.')

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if (
        db_stage is None
        or db_stage.type != StageType.ffa_flatout2_single_elimination.value
    ):
        return Err('This match does not use the FlatOut 2 stage type.')

    allowed_participant_ids = {
        slot.participant_id
        for slot in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
        ).all()
        if slot.participant_id is not None
    }

    if host_participant_id is not None and host_participant_id not in allowed_participant_ids:
        return Err('Selected host is not part of this match.')

    settings = dict(db_match.settings_json or {})
    previous_host_participant_id = settings.get('host_participant_id')
    if host_participant_id is None:
        settings.pop('host_participant_id', None)
    else:
        settings['host_participant_id'] = str(host_participant_id)

    db_match.settings_json = settings
    db_match.updated_at = datetime.utcnow()
    stage_settings = dict(db_stage.settings_json or {})
    match_hosts = dict(stage_settings.get('flatout2_match_hosts') or {})
    match_key = f'{db_match.round_no}:{db_match.match_no}'
    if host_participant_id is None:
        match_hosts.pop(match_key, None)
    else:
        match_hosts[match_key] = str(host_participant_id)
    stage_settings['flatout2_match_hosts'] = match_hosts
    db_stage.settings_json = stage_settings

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='flatout2_match_host_updated_by_admin',
        payload={
            'host_participant_id': (
                str(host_participant_id) if host_participant_id is not None else None
            ),
        },
        created_at=datetime.utcnow(),
    )

    should_notify = (
        host_participant_id is not None
        and str(host_participant_id) != str(previous_host_participant_id or '')
        and db_tournament.status == TournamentStatus.live.value
        and db_match.state == MatchState.ready.value
    )

    if should_notify:
        _enqueue_flatout2_host_assignment_notifications(db_match)

    db.session.commit()
    return Ok(_db_match_to_model(db_match))


def reschedule_match(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    scheduled_at: datetime,
    initiator: User,
    *,
    comment: str,
    correlation_id: str | None = None,
) -> Result[Match, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    comment = comment.strip()
    if not comment:
        return Err('A comment is required.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch).filter_by(
            id=match_id, tournament_id=tournament_id
        )
    )
    if db_match is None:
        return Err('Unknown match.')

    db_match.scheduled_at = scheduled_at
    db_match.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='match_rescheduled',
        payload={
            'scheduled_at': scheduled_at.isoformat(),
            'comment': comment,
            'correlation_id': correlation_id,
        },
        created_at=datetime.utcnow(),
    )

    _append_notifications_for_match(
        db_match,
        actor_user_id=initiator.id,
        kind='schedule_changed',
        payload={
            'match_id': str(db_match.id),
            'scheduled_at': scheduled_at.isoformat(),
            'url': _build_site_match_path(db_tournament.slug, db_match.id),
        },
    )

    db.session.commit()

    log.info(
        'netsession_tourney.match_rescheduled',
        tournament_id=str(tournament_id),
        match_id=str(match_id),
        actor_user_id=str(initiator.id),
        correlation_id=correlation_id,
    )

    return Ok(_db_match_to_model(db_match))


def open_match_dispute(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    initiator: User,
    *,
    reason_code: str,
    comment: str,
    correlation_id: str | None = None,
) -> Result[Match, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    reason_code = reason_code.strip()
    comment = comment.strip()
    if not reason_code:
        return Err('A reason code is required.')
    if not comment:
        return Err('A comment is required.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch).filter_by(
            id=match_id, tournament_id=tournament_id
        )
    )
    if db_match is None:
        return Err('Unknown match.')

    db_match.state = MatchState.disputed.value
    db_match.dispute_reason_code = reason_code
    db_match.dispute_comment = comment
    db_match.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='match',
        object_id=match_id,
        action='match_disputed',
        payload={
            'reason_code': reason_code,
            'comment': comment,
            'correlation_id': correlation_id,
        },
        created_at=datetime.utcnow(),
    )

    _append_notifications_for_match(
        db_match,
        actor_user_id=initiator.id,
        kind='dispute_opened',
        payload={
            'match_id': str(db_match.id),
            'reason_code': reason_code,
            'url': _build_site_match_path(db_tournament.slug, db_match.id),
        },
    )

    db.session.commit()

    log.info(
        'netsession_tourney.match_disputed',
        tournament_id=str(tournament_id),
        match_id=str(match_id),
        actor_user_id=str(initiator.id),
        reason_code=reason_code,
        correlation_id=correlation_id,
    )

    return Ok(_db_match_to_model(db_match))


def apply_walkover_result(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    initiator: User,
    *,
    winner_slot: int,
    idempotency_key: str,
    comment: str,
    correlation_id: str | None = None,
) -> Result[MatchResult, str]:
    comment = comment.strip()
    if not comment:
        return Err('A comment is required.')

    return report_result(
        party_id,
        tournament_id,
        match_id,
        initiator.id,
        idempotency_key=idempotency_key,
        winner_slot=winner_slot,
        score={'walkover': True},
        ranking={},
        actor_is_admin_or_referee=True,
        admin_comment=comment,
        reason_code='walkover',
        correlation_id=correlation_id,
    )


def disqualify_participant(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    *,
    reason_code: str,
    comment: str,
    correlation_id: str | None = None,
) -> Result[Participant, str]:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return Err('Unbekanntes Turnier.')

    reason_code = reason_code.strip()
    comment = comment.strip()
    if not reason_code:
        return Err('A reason code is required.')
    if not comment:
        return Err('A comment is required.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant).filter_by(
            id=participant_id,
            tournament_id=tournament_id,
        )
    )
    if db_participant is None:
        return Err('Unknown participant.')

    db_participant.status = ParticipantStatus.dropped.value

    affected_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .join(
            DbNetsessionTourneyMatchSlot,
            DbNetsessionTourneyMatch.id == DbNetsessionTourneyMatchSlot.match_id,
        )
        .filter(DbNetsessionTourneyMatch.tournament_id == tournament_id)
        .filter(DbNetsessionTourneyMatchSlot.participant_id == participant_id)
        .filter(
            DbNetsessionTourneyMatch.state.in_(
                [
                    MatchState.pending.value,
                    MatchState.ready.value,
                    MatchState.in_progress.value,
                    MatchState.pending_confirmation.value,
                ]
            )
        )
    ).all()

    now = datetime.utcnow()
    for db_match in affected_matches:
        db_match.state = MatchState.needs_admin_review.value
        db_match.dispute_reason_code = 'participant_disqualified'
        db_match.dispute_comment = comment
        db_match.updated_at = now

        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='match',
            object_id=db_match.id,
            action='match_needs_admin_review',
            payload={
                'reason_code': 'participant_disqualified',
                'participant_id': str(participant_id),
                'comment': comment,
                'correlation_id': correlation_id,
            },
            created_at=now,
        )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='participant_disqualified',
        payload={
            'reason_code': reason_code,
            'comment': comment,
            'affected_match_count': len(affected_matches),
            'correlation_id': correlation_id,
        },
        created_at=now,
    )

    if db_participant.manager_user_id is not None:
        _append_notification(
            tournament_id=tournament_id,
            user_id=db_participant.manager_user_id,
            kind='participant_disqualified',
            payload={
                'participant_id': str(participant_id),
                'reason_code': reason_code,
            },
            created_at=now,
        )

    db.session.commit()

    log.info(
        'netsession_tourney.participant_disqualified',
        tournament_id=str(tournament_id),
        participant_id=str(participant_id),
        actor_user_id=str(initiator.id),
        reason_code=reason_code,
        correlation_id=correlation_id,
    )

    return Ok(_db_participant_to_model(db_participant))


def resolve_pending_confirmations(party_id: PartyID) -> int:
    now = datetime.utcnow()
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .join(
            DbNetsessionTourneyTournament,
            DbNetsessionTourneyMatch.tournament_id
            == DbNetsessionTourneyTournament.id,
        )
        .filter(DbNetsessionTourneyTournament.party_id == party_id)
        .filter(
            DbNetsessionTourneyMatch.state
            == MatchState.pending_confirmation.value
        )
        .filter(DbNetsessionTourneyMatch.confirmation_deadline_at < now)
    ).all()

    for db_match in db_matches:
        db_match.state = MatchState.needs_admin_review.value
        db_match.updated_at = now
        db_match.confirmation_deadline_at = None
        _append_audit_log(
            actor_user_id=None,
            object_type='match',
            object_id=db_match.id,
            action='result_confirmation_timed_out',
            payload={'reason_code': 'confirmation_timeout'},
            created_at=now,
        )

    db.session.commit()
    return len(db_matches)


def enqueue_discord_event(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    event_name: str,
    payload: dict[str, Any],
) -> None:
    if event_name not in DISCORD_SUPPORTED_EVENTS:
        log.warning(
            'netsession_tourney.discord_event_ignored_unknown',
            tournament_id=str(tournament_id),
            event_name=event_name,
        )
        return

    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None or not db_tournament.discord_enabled:
        return

    if event_name not in (db_tournament.discord_event_mask or []):
        return

    db.session.add(
        DbNetsessionTourneyDiscordOutbox(
            DiscordOutboxID(generate_uuid7()),
            tournament_id,
            event_name,
            payload,
            datetime.utcnow(),
        )
    )
    db.session.commit()


def process_discord_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    db_rows = db.session.scalars(
        select(DbNetsessionTourneyDiscordOutbox)
        .filter(
            DbNetsessionTourneyDiscordOutbox.status.in_(
                [
                    DiscordOutboxStatus.pending.value,
                    DiscordOutboxStatus.failed.value,
                ]
            )
        )
        .filter(
            (DbNetsessionTourneyDiscordOutbox.next_attempt_at.is_(None))
            | (DbNetsessionTourneyDiscordOutbox.next_attempt_at <= now)
        )
        .order_by(DbNetsessionTourneyDiscordOutbox.created_at.asc())
        .limit(limit)
    ).all()

    match get_configured_discord_bot_credentials():
        case Err(message):
            credentials_error = message
            credentials = None
        case Ok(credentials):
            credentials_error = None

    processed = 0
    for db_row in db_rows:
        processed += 1
        db_row.attempt_count += 1
        db_row.updated_at = now

        db_tournament = db.session.get(
            DbNetsessionTourneyTournament, db_row.tournament_id
        )
        if db_tournament is None:
            _mark_discord_outbox_dead_letter(
                db_row, 'Unknown tournament for Discord outbox item.', now
            )
            continue

        if not db_tournament.discord_enabled:
            _mark_discord_outbox_dead_letter(
                db_row,
                'Discord-Forum ist für dieses Turnier nicht aktiviert.',
                now,
            )
            continue

        if not db_tournament.discord_forum_channel_id:
            _mark_discord_outbox_dead_letter(
                db_row,
                'Keine Discord-Forum-Channel-ID konfiguriert.',
                now,
            )
            continue

        if credentials is None:
            _schedule_discord_outbox_retry(
                db_row,
                credentials_error
                or 'Keine gültige Discord-Bot-Konfiguration aktiv.',
                now,
            )
            continue

        application_id, bot_token = credentials
        if not db_tournament.discord_thread_id:
            try:
                _sync_discord_thread_for_tournament(db_tournament)
            except Exception:
                pass

        thread_id = db_tournament.discord_thread_id
        if not thread_id:
            _schedule_discord_outbox_retry(
                db_row,
                'Discord-Forum-Thread konnte noch nicht erstellt werden.',
                now,
            )
            continue

        try:
            _post_discord_forum_message(
                application_id=application_id,
                bot_token=bot_token,
                thread_id=thread_id,
                payload=_build_discord_message_payload(
                    db_tournament, db_row
                ),
            )
        except httpx.HTTPStatusError as exc:
            recovered_thread_id = _recover_deleted_discord_forum_thread(
                db_tournament=db_tournament,
                failed_thread_id=thread_id,
                exc=exc,
            )
            if recovered_thread_id:
                try:
                    _post_discord_forum_message(
                        application_id=application_id,
                        bot_token=bot_token,
                        thread_id=recovered_thread_id,
                        payload=_build_discord_message_payload(
                            db_tournament, db_row
                        ),
                    )
                except httpx.HTTPError as retry_exc:
                    _schedule_discord_outbox_retry(
                        db_row,
                        (
                            'Discord-Forum-Anfrage fehlgeschlagen: '
                            f'{type(retry_exc).__name__}'
                        ),
                        now,
                    )
                    log.warning(
                        'netsession_tourney.discord_forum_delivery_failed',
                        tournament_id=str(db_row.tournament_id),
                        outbox_id=str(db_row.id),
                        event_name=db_row.event_name,
                        error=type(retry_exc).__name__,
                    )
                    continue

                db_row.status = DiscordOutboxStatus.sent.value
                db_row.next_attempt_at = None
                db_row.last_error = None
                continue

            _schedule_discord_outbox_retry(
                db_row,
                f'Discord-Forum-Anfrage fehlgeschlagen: {type(exc).__name__}',
                now,
            )
            log.warning(
                'netsession_tourney.discord_forum_delivery_failed',
                tournament_id=str(db_row.tournament_id),
                outbox_id=str(db_row.id),
                event_name=db_row.event_name,
                error=type(exc).__name__,
            )
            continue
        except httpx.HTTPError as exc:
            _schedule_discord_outbox_retry(
                db_row,
                f'Discord-Forum-Anfrage fehlgeschlagen: {type(exc).__name__}',
                now,
            )
            log.warning(
                'netsession_tourney.discord_forum_delivery_failed',
                tournament_id=str(db_row.tournament_id),
                outbox_id=str(db_row.id),
                event_name=db_row.event_name,
                error=type(exc).__name__,
            )
            continue

        db_row.status = DiscordOutboxStatus.sent.value
        db_row.next_attempt_at = None
        db_row.last_error = None
    db.session.commit()
    return processed


def process_discord_dm_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    try:
        db_rows = db.session.scalars(
            select(DbNetsessionTourneyDiscordDmOutbox)
            .filter(
                DbNetsessionTourneyDiscordDmOutbox.status.in_(
                    [
                        DiscordDmOutboxStatus.pending.value,
                        DiscordDmOutboxStatus.failed.value,
                    ]
                )
            )
            .filter(
                (DbNetsessionTourneyDiscordDmOutbox.next_attempt_at.is_(None))
                | (DbNetsessionTourneyDiscordDmOutbox.next_attempt_at <= now)
            )
            .order_by(DbNetsessionTourneyDiscordDmOutbox.created_at.asc())
            .limit(limit)
        ).all()
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return 0
        raise

    processed = 0
    for db_row in db_rows:
        processed += 1
        db_row.attempt_count += 1
        db_row.updated_at = now

        db_notification = db.session.get(
            DbNetsessionTourneyNotification, db_row.notification_id
        )
        if db_notification is None:
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Unknown notification.', now
            )
            continue

        db_tournament = db.session.get(
            DbNetsessionTourneyTournament, db_notification.tournament_id
        )
        if db_tournament is None:
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Unknown tournament for Discord-DM outbox item.', now
            )
            continue

        db_config = db.session.get(
            DbNetsessionTourneyDiscordDmConfig, db_tournament.party_id
        )
        if (
            db_config is None
            or not db_config.enabled
            or not db_config.application_id
            or not db_config.bot_token_encrypted
        ):
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Discord-DM-Konfiguration ist unvollständig.', now
            )
            continue

        bot_token = _decrypt_discord_dm_bot_token(
            db_config.bot_token_encrypted
        )
        if not bot_token:
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Kein gültiges Discord-Bot-Token konfiguriert.', now
            )
            continue

        connected_account = (
            external_accounts_service.find_connected_external_account_for_user_and_service(
                db_notification.user_id, 'discord'
            )
        )
        discord_user_id = (
            connected_account.external_id
            if connected_account is not None
            else None
        )
        if not discord_user_id:
            _mark_discord_dm_outbox_dead_letter(
                db_row, 'Empfänger hat keinen verbundenen Discord-Account.',
                now,
            )
            continue

        payload = _build_discord_dm_message_payload(
            db_tournament,
            db_notification,
        )

        try:
            _send_discord_dm(
                application_id=db_config.application_id,
                bot_token=bot_token,
                discord_user_id=discord_user_id,
                payload=payload,
            )
        except httpx.HTTPError as exc:
            _schedule_discord_dm_outbox_retry(
                db_row,
                f'Discord-DM-Anfrage fehlgeschlagen: {type(exc).__name__}',
                now,
            )
            continue
        except ValueError as exc:
            _mark_discord_dm_outbox_dead_letter(db_row, str(exc), now)
            continue

        db_row.status = DiscordDmOutboxStatus.sent.value
        db_row.next_attempt_at = None
        db_row.last_error = None

    db.session.commit()
    return processed

def get_discord_dm_config(party_id: PartyID) -> DiscordDmConfig:
    try:
        db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return _build_default_discord_dm_config(party_id)
        raise

    if db_config is None:
        return _build_default_discord_dm_config(party_id)

    return _db_discord_dm_config_to_model(db_config)


def is_discord_dm_enabled_for_party(party_id: PartyID) -> bool:
    try:
        db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return False
        raise

    return bool(
        db_config
        and db_config.enabled
        and db_config.application_id
        and db_config.bot_token_encrypted
    )


def configure_discord_dm(
    party_id: PartyID,
    *,
    enabled: bool,
    application_id: str | None,
    bot_token: str | None,
    default_event_mask: list[str],
) -> Result[DiscordDmConfig, str]:
    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unknown party.')

    try:
        db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return Err(
                'Discord-DM-Tabellen sind noch nicht installiert.'
            )
        raise

    normalized_application_id = (application_id or '').strip() or None
    normalized_bot_token = (bot_token or '').strip() or None
    normalized_event_mask = sorted(
        {
            item
            for item in default_event_mask
            if item in DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS
        }
    )

    if enabled and not normalized_application_id:
        return Err('Eine Application ID ist erforderlich.')

    now = datetime.utcnow()
    if db_config is None:
        db_config = DbNetsessionTourneyDiscordDmConfig(party_id, now)
        db.session.add(db_config)

    if enabled and not normalized_bot_token and not db_config.bot_token_encrypted:
        return Err('Ein Bot-Token ist erforderlich.')

    db_config.enabled = enabled
    db_config.application_id = normalized_application_id
    if normalized_bot_token:
        db_config.bot_token_encrypted = _encrypt_discord_dm_bot_token(
            normalized_bot_token
        )
    db_config.default_event_mask = normalized_event_mask
    db_config.updated_at = now
    db.session.commit()

    return Ok(_db_discord_dm_config_to_model(db_config))


def get_masked_discord_dm_bot_token(party_id: PartyID) -> str:
    try:
        db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return ''
        raise

    if db_config is None or not db_config.bot_token_encrypted:
        return ''

    return _mask_discord_dm_bot_token(
        _decrypt_discord_dm_bot_token(db_config.bot_token_encrypted)
    )


def get_configured_discord_bot_credentials() -> Result[tuple[str, str] | None, str]:
    try:
        db_configs = db.session.scalars(
            select(DbNetsessionTourneyDiscordDmConfig)
        ).all()
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return Ok(None)
        raise

    credentials: set[tuple[str, str]] = set()
    for db_config in db_configs:
        if not db_config.application_id or not db_config.bot_token_encrypted:
            continue

        bot_token = _decrypt_discord_dm_bot_token(
            db_config.bot_token_encrypted
        )
        if not bot_token:
            continue

        credentials.add((db_config.application_id, bot_token))

    if not credentials:
        return Ok(None)

    if len(credentials) > 1:
        return Err(
            'Mehrere unterschiedliche Discord-Bot-Konfigurationen sind aktiv.'
        )

    return Ok(next(iter(credentials)))


def get_enabled_discord_dm_bot_credentials() -> Result[tuple[str, str] | None, str]:
    match get_configured_discord_bot_credentials():
        case Err(message):
            return Err(message)
        case Ok(None):
            return Ok(None)
        case Ok(credentials):
            pass

    try:
        db_configs = db.session.scalars(
            select(DbNetsessionTourneyDiscordDmConfig).filter_by(enabled=True)
        ).all()
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return Ok(None)
        raise

    enabled_credentials: set[tuple[str, str]] = set()
    for db_config in db_configs:
        if not db_config.application_id or not db_config.bot_token_encrypted:
            continue

        bot_token = _decrypt_discord_dm_bot_token(
            db_config.bot_token_encrypted
        )
        if not bot_token:
            continue

        enabled_credentials.add((db_config.application_id, bot_token))

    if not enabled_credentials:
        return Ok(None)

    return Ok(credentials)


def send_test_discord_dm(
    party_id: PartyID,
    user_id: UserID,
) -> Result[None, str]:
    db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    if db_config is None or not db_config.enabled:
        return Err('Discord-Privatbenachrichtigungen sind nicht aktiviert.')

    if not db_config.application_id or not db_config.bot_token_encrypted:
        return Err('Discord-DM-Konfiguration ist unvollständig.')

    connected_account = (
        external_accounts_service.find_connected_external_account_for_user_and_service(
            user_id, 'discord'
        )
    )
    discord_user_id = (
        connected_account.external_id
        if connected_account is not None
        else None
    )
    if not discord_user_id:
        return Err('Dein Benutzerkonto hat keinen verbundenen Discord-Account.')

    bot_token = _decrypt_discord_dm_bot_token(
        db_config.bot_token_encrypted
    )
    if not bot_token:
        return Err('Kein gültiges Discord-Bot-Token konfiguriert.')

    payload = _build_test_discord_dm_message_payload(party_id)

    try:
        _send_discord_dm(
            application_id=db_config.application_id,
            bot_token=bot_token,
            discord_user_id=discord_user_id,
            payload=payload,
        )
    except httpx.HTTPError as exc:
        return Err(
            f'Discord-DM-Anfrage fehlgeschlagen: {type(exc).__name__}'
        )
    except ValueError as exc:
        return Err(str(exc))

    return Ok(None)


def upsert_discord_dm_subscription(
    party_id: PartyID,
    user_id: UserID,
) -> Result[None, str]:
    if not is_discord_dm_enabled_for_party(party_id):
        return Err('Discord-Benachrichtigungen sind deaktiviert.')

    connected_account = (
        external_accounts_service.find_connected_external_account_for_user_and_service(
            user_id, 'discord'
        )
    )
    if connected_account is None or not connected_account.external_id:
        return Err('Bitte verbinde zuerst deinen Discord-Account.')

    now = datetime.utcnow()
    try:
        db_subscription = db.session.scalar(
            select(DbNetsessionTourneyDiscordDmSubscription).filter_by(
                party_id=party_id,
                user_id=user_id,
            )
        )
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return Err(
                'Discord-DM-Tabellen sind noch nicht installiert.'
            )
        raise

    if db_subscription is None:
        db_subscription = DbNetsessionTourneyDiscordDmSubscription(
            DiscordDmSubscriptionID(generate_uuid7()),
            party_id,
            user_id,
            now,
        )
        db.session.add(db_subscription)
    else:
        db_subscription.enabled = True
        db_subscription.last_seen_at = now
        db_subscription.updated_at = now

    db.session.commit()
    return Ok(None)


def disable_discord_dm_subscription(
    party_id: PartyID,
    user_id: UserID,
) -> None:
    try:
        db_subscription = db.session.scalar(
            select(DbNetsessionTourneyDiscordDmSubscription).filter_by(
                party_id=party_id,
                user_id=user_id,
            )
        )
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return
        raise
    if db_subscription is None:
        return

    db_subscription.enabled = False
    db_subscription.updated_at = datetime.utcnow()
    db.session.commit()


def has_active_discord_dm_subscription_for_user(
    party_id: PartyID, user_id: UserID
) -> bool:
    return count_active_discord_dm_subscriptions_for_user(
        party_id, user_id
    ) > 0


def count_active_discord_dm_subscriptions_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    try:
        count = db.session.scalar(
            select(db.func.count(DbNetsessionTourneyDiscordDmSubscription.id))
            .filter_by(party_id=party_id, user_id=user_id, enabled=True)
        )
    except DBAPIError as exc:
        if _is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return 0
        raise

    return int(count or 0)


def get_browser_push_config(party_id: PartyID) -> BrowserPushConfig:
    try:
        db_config = db.session.get(DbNetsessionTourneyBrowserPushConfig, party_id)
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return _build_default_browser_push_config(party_id)
        raise

    if db_config is None:
        return _build_default_browser_push_config(party_id)

    return _db_browser_push_config_to_model(db_config)


def is_browser_push_enabled_for_party(party_id: PartyID) -> bool:
    try:
        db_config = db.session.get(DbNetsessionTourneyBrowserPushConfig, party_id)
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return False
        raise

    return bool(db_config and db_config.enabled and db_config.vapid_public_key)


def get_browser_push_public_key_for_party(party_id: PartyID) -> str | None:
    try:
        db_config = db.session.get(DbNetsessionTourneyBrowserPushConfig, party_id)
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return None
        raise

    if db_config is None or not db_config.enabled:
        return None

    return db_config.vapid_public_key


def configure_browser_push(
    party_id: PartyID,
    *,
    enabled: bool,
) -> Result[BrowserPushConfig, str]:
    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unknown party.')

    try:
        db_config = db.session.get(DbNetsessionTourneyBrowserPushConfig, party_id)
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return Err('Browser push tables are not installed yet.')
        raise

    now = datetime.utcnow()
    if db_config is None:
        db_config = DbNetsessionTourneyBrowserPushConfig(party_id, now)
        db.session.add(db_config)

    if enabled and (
        not db_config.vapid_public_key
        or not db_config.vapid_private_key_encrypted
    ):
        private_key_pem = _generate_browser_push_private_key_pem()
        db_config.vapid_public_key = _derive_browser_push_public_key(
            private_key_pem
        )
        db_config.vapid_private_key_encrypted = _encrypt_browser_push_private_key(
            private_key_pem
        )

    db_config.enabled = enabled
    db_config.updated_at = now
    db.session.commit()

    return Ok(_db_browser_push_config_to_model(db_config))


def upsert_browser_push_subscription(
    party_id: PartyID,
    user_id: UserID,
    *,
    endpoint: str,
    endpoint_p256dh: str,
    endpoint_auth: str,
    user_agent: str | None = None,
) -> Result[None, str]:
    if not is_browser_push_enabled_for_party(party_id):
        return Err('Browser notifications are disabled.')

    endpoint = endpoint.strip()
    endpoint_p256dh = endpoint_p256dh.strip()
    endpoint_auth = endpoint_auth.strip()
    if not endpoint or not endpoint_p256dh or not endpoint_auth:
        return Err('Subscription data is incomplete.')

    now = datetime.utcnow()
    try:
        db_subscription = db.session.scalar(
            select(DbNetsessionTourneyBrowserPushSubscription).filter_by(
                party_id=party_id,
                endpoint=endpoint,
            )
        )
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return Err('Browser push tables are not installed yet.')
        raise
    if db_subscription is None:
        db_subscription = DbNetsessionTourneyBrowserPushSubscription(
            BrowserPushSubscriptionID(generate_uuid7()),
            party_id,
            user_id,
            endpoint,
            endpoint_p256dh,
            endpoint_auth,
            now,
            user_agent=(user_agent or '').strip()[:500] or None,
        )
        db.session.add(db_subscription)
    else:
        db_subscription.user_id = user_id
        db_subscription.endpoint_p256dh = endpoint_p256dh
        db_subscription.endpoint_auth = endpoint_auth
        db_subscription.user_agent = (user_agent or '').strip()[:500] or None
        db_subscription.enabled = True
        db_subscription.last_seen_at = now
        db_subscription.updated_at = now

    db.session.commit()
    return Ok(None)


def disable_browser_push_subscription(
    party_id: PartyID,
    user_id: UserID,
    *,
    endpoint: str,
) -> None:
    try:
        db_subscription = db.session.scalar(
            select(DbNetsessionTourneyBrowserPushSubscription).filter_by(
                party_id=party_id,
                user_id=user_id,
                endpoint=endpoint.strip(),
            )
        )
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return
        raise
    if db_subscription is None:
        return

    db_subscription.enabled = False
    db_subscription.updated_at = datetime.utcnow()
    db.session.commit()


def has_active_browser_push_subscription_for_user(
    party_id: PartyID, user_id: UserID
) -> bool:
    return count_active_browser_push_subscriptions_for_user(
        party_id, user_id
    ) > 0


def count_active_browser_push_subscriptions_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    try:
        count = db.session.scalar(
            select(db.func.count(DbNetsessionTourneyBrowserPushSubscription.id))
            .filter_by(party_id=party_id, user_id=user_id, enabled=True)
        )
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return 0
        raise
    return int(count or 0)


def count_browser_push_subscribed_participants_for_tournament(
    party_id: PartyID, tournament_id: TournamentID
) -> int:
    user_ids, _subscription_count = (
        _get_active_browser_push_subscription_recipients_for_tournament(
            party_id, tournament_id
        )
    )
    return len(user_ids)


def _get_active_browser_push_subscription_recipients_for_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
) -> tuple[set[UserID], int]:
    user_ids = _get_active_user_ids_for_tournament(tournament_id)
    if not user_ids:
        return set(), 0

    try:
        rows = db.session.execute(
            select(DbNetsessionTourneyBrowserPushSubscription.user_id).filter_by(
                party_id=party_id,
                enabled=True,
            ).filter(
                DbNetsessionTourneyBrowserPushSubscription.user_id.in_(user_ids)
            )
        ).all()
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return set(), 0
        raise

    subscribed_user_ids = {user_id for (user_id,) in rows}
    return subscribed_user_ids, len(rows)


def get_browser_push_subscribed_user_ids_for_tournament(
    party_id: PartyID, tournament_id: TournamentID
) -> set[UserID]:
    user_ids = _get_active_user_ids_for_tournament(tournament_id)
    if not user_ids:
        return set()

    try:
        rows = db.session.scalars(
            select(DbNetsessionTourneyBrowserPushSubscription.user_id)
            .filter_by(party_id=party_id, enabled=True)
            .filter(
                DbNetsessionTourneyBrowserPushSubscription.user_id.in_(user_ids)
            )
            .distinct()
        ).all()
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return set()
        raise

    return set(rows)


def get_recent_browser_push_outbox_entries_for_tournament(
    tournament_id: TournamentID,
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    try:
        rows = db.session.execute(
            select(
                DbNetsessionTourneyBrowserPushOutbox,
                DbNetsessionTourneyNotification,
            )
            .join(
                DbNetsessionTourneyNotification,
                DbNetsessionTourneyNotification.id
                == DbNetsessionTourneyBrowserPushOutbox.notification_id,
            )
            .filter(DbNetsessionTourneyNotification.tournament_id == tournament_id)
            .order_by(DbNetsessionTourneyBrowserPushOutbox.created_at.desc())
            .limit(limit)
        ).all()
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return []
        raise

    entries = []
    for db_outbox, db_notification in rows:
        payload = dict(db_notification.payload_json or {})
        entries.append(
            {
                'notification_id': db_notification.id,
                'user_id': db_notification.user_id,
                'kind': db_notification.kind,
                'title': str(payload.get('title') or '').strip() or None,
                'body': str(payload.get('body') or '').strip() or None,
                'status': db_outbox.status,
                'attempt_count': db_outbox.attempt_count,
                'next_attempt_at': db_outbox.next_attempt_at,
                'last_error': db_outbox.last_error,
                'created_at': db_outbox.created_at,
                'updated_at': db_outbox.updated_at,
            }
        )

    return entries


def process_browser_push_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    try:
        db_rows = db.session.scalars(
            select(DbNetsessionTourneyBrowserPushOutbox)
            .filter(
                DbNetsessionTourneyBrowserPushOutbox.status.in_(
                    [
                        BrowserPushOutboxStatus.pending.value,
                        BrowserPushOutboxStatus.failed.value,
                    ]
                )
            )
            .filter(
                (DbNetsessionTourneyBrowserPushOutbox.next_attempt_at.is_(None))
                | (DbNetsessionTourneyBrowserPushOutbox.next_attempt_at <= now)
            )
            .order_by(DbNetsessionTourneyBrowserPushOutbox.created_at.asc())
            .limit(limit)
        ).all()
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return 0
        raise

    processed = 0
    for db_row in db_rows:
        processed += 1
        db_row.attempt_count += 1
        db_row.updated_at = now

        db_notification = db.session.get(
            DbNetsessionTourneyNotification, db_row.notification_id
        )
        if db_notification is None:
            _mark_browser_push_outbox_dead_letter(
                db_row, 'Unknown notification.', now
            )
            continue

        db_tournament = db.session.get(
            DbNetsessionTourneyTournament, db_notification.tournament_id
        )
        if db_tournament is None:
            _mark_browser_push_outbox_dead_letter(
                db_row, 'Unbekanntes Turnier.', now
            )
            continue

        db_config = db.session.get(
            DbNetsessionTourneyBrowserPushConfig, db_tournament.party_id
        )
        if (
            db_config is None
            or not db_config.enabled
            or not db_config.vapid_private_key_encrypted
        ):
            db_row.status = BrowserPushOutboxStatus.sent.value
            db_row.next_attempt_at = None
            db_row.last_error = None
            continue

        private_key_pem = _decrypt_browser_push_private_key(
            db_config.vapid_private_key_encrypted
        )
        if private_key_pem is None:
            _schedule_browser_push_outbox_retry(
                db_row,
                'No valid browser push private key configured.',
                now,
            )
            continue

        db_subscriptions = db.session.scalars(
            select(DbNetsessionTourneyBrowserPushSubscription).filter_by(
                party_id=db_tournament.party_id,
                user_id=db_notification.user_id,
                enabled=True,
            )
        ).all()
        if not db_subscriptions:
            db_row.status = BrowserPushOutboxStatus.sent.value
            db_row.next_attempt_at = None
            db_row.last_error = None
            continue

        vapid_private_key = _build_browser_push_private_key_for_pywebpush(
            private_key_pem
        )

        message = _build_browser_push_message_payload(
            db_tournament, db_notification
        )
        delivered = False
        had_transient_error = False
        transient_error_message = None
        for db_subscription in db_subscriptions:
            try:
                if webpush is None:
                    raise RuntimeError(
                        'pywebpush is not installed in this environment.'
                    )

                vapid_claims = {
                    'sub': _build_browser_push_vapid_subject(
                        db_tournament.party_id, db_subscription.endpoint
                    ),
                }

                webpush(
                    subscription_info={
                        'endpoint': db_subscription.endpoint,
                        'keys': {
                            'p256dh': db_subscription.endpoint_p256dh,
                            'auth': db_subscription.endpoint_auth,
                        },
                    },
                    data=json.dumps(message),
                    vapid_private_key=vapid_private_key,
                    vapid_claims=vapid_claims,
                )
                delivered = True
            except WebPushException as exc:  # pragma: no branch
                status_code = getattr(
                    getattr(exc, 'response', None), 'status_code', None
                )
                if status_code in {404, 410}:
                    db_subscription.enabled = False
                    db_subscription.updated_at = now
                    continue

                had_transient_error = True
                transient_error_message = _format_browser_push_delivery_error(
                    exc
                )
            except Exception as exc:  # pragma: no cover - delivery fallback
                had_transient_error = True
                transient_error_message = _format_browser_push_delivery_error(
                    exc
                )

        if delivered or not had_transient_error:
            db_row.status = BrowserPushOutboxStatus.sent.value
            db_row.next_attempt_at = None
            db_row.last_error = None
            continue

        _schedule_browser_push_outbox_retry(
            db_row,
            f'Browser push delivery failed: {transient_error_message}',
            now,
        )

    db.session.commit()
    return processed


def configure_discord(
    party_id: PartyID,
    tournament_id: TournamentID,
    initiator: User,
    *,
    enabled: bool,
    forum_channel_id: str | None,
    discord_forum_image_url: str | None,
    applied_tag_ids: list[str],
    event_mask: list[str],
    discord_dm_enabled: bool,
    discord_dm_event_mask: list[str],
) -> Result[Tournament, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    normalized_forum_channel_id = (forum_channel_id or '').strip() or None
    normalized_discord_forum_image_url = (
        discord_forum_image_url.strip() if discord_forum_image_url else None
    )
    normalized_event_mask = sorted(set(event_mask))
    if enabled and not normalized_forum_channel_id:
        return Err('Eine Discord-Forum-Channel-ID ist erforderlich.')

    invalid_events = sorted(
        set(normalized_event_mask).difference(DISCORD_SUPPORTED_EVENTS)
    )
    if invalid_events:
        return Err(
            'Unbekannte Discord-Forum-Events: ' + ', '.join(invalid_events)
        )
    if enabled and not normalized_event_mask:
        return Err(
            'Mindestens ein Discord-Forum-Event muss ausgewählt werden.'
        )

    invalid_dm_events = sorted(
        set(discord_dm_event_mask).difference(DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS)
    )
    if invalid_dm_events:
        return Err(
            'Unknown Discord-DM event(s): ' + ', '.join(invalid_dm_events)
        )

    normalized_discord_dm_event_mask = sorted(set(discord_dm_event_mask))
    if discord_dm_enabled and not normalized_discord_dm_event_mask:
        return Err(
            'Mindestens ein Discord-DM-Event muss ausgewählt werden.'
        )

    forum_channel_changed = (
        db_tournament.discord_forum_channel_id != normalized_forum_channel_id
    )
    db_tournament.discord_enabled = enabled
    db_tournament.discord_forum_channel_id = normalized_forum_channel_id
    db_tournament.discord_forum_image_url = normalized_discord_forum_image_url
    if forum_channel_changed:
        db_tournament.discord_thread_id = None
    db_tournament.discord_applied_tag_ids = list(applied_tag_ids)
    db_tournament.discord_event_mask = normalized_event_mask
    db_tournament.discord_dm_enabled = discord_dm_enabled
    db_tournament.discord_dm_event_mask = normalized_discord_dm_event_mask
    db_tournament.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='discord_configuration_updated',
        payload={
            'enabled': enabled,
            'forum_channel_id': normalized_forum_channel_id,
            'discord_forum_image_url': normalized_discord_forum_image_url,
            'event_mask': normalized_event_mask,
            'discord_dm_enabled': discord_dm_enabled,
            'discord_dm_event_mask': normalized_discord_dm_event_mask,
        },
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    if db_tournament.discord_enabled:
        _sync_discord_thread_for_tournament(db_tournament)

    return Ok(_db_tournament_to_model(db_tournament))


def _ensure_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
) -> None:
    _sync_discord_thread_for_tournament(db_tournament, update_existing=False)


def _sync_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    update_existing: bool = True,
) -> None:
    if not db_tournament.discord_enabled or not db_tournament.discord_forum_channel_id:
        return

    match get_configured_discord_bot_credentials():
        case Err(message):
            log.warning(
                'netsession_tourney.discord_forum_thread_credentials_invalid',
                tournament_id=str(db_tournament.id),
                error=message,
            )
            return
        case Ok(None):
            return
        case Ok((application_id, bot_token)):
            pass

    if db_tournament.discord_thread_id:
        try:
            _get_discord_channel(
                application_id=application_id,
                bot_token=bot_token,
                channel_id=db_tournament.discord_thread_id,
            )
        except httpx.HTTPStatusError as exc:
            if _is_discord_resource_missing(exc):
                _clear_discord_thread_reference(
                    db_tournament,
                    audit_action='discord_thread_missing_reset',
                    audit_payload={
                        'thread_id': db_tournament.discord_thread_id,
                        'reason': 'thread_missing',
                    },
                )
            else:
                log.warning(
                    'netsession_tourney.discord_forum_thread_validate_failed',
                    tournament_id=str(db_tournament.id),
                    thread_id=str(db_tournament.discord_thread_id),
                    error=type(exc).__name__,
                )
                return
        except httpx.HTTPError as exc:
            log.warning(
                'netsession_tourney.discord_forum_thread_validate_failed',
                tournament_id=str(db_tournament.id),
                thread_id=str(db_tournament.discord_thread_id),
                error=type(exc).__name__,
            )
            return

    if db_tournament.discord_thread_id:
        if update_existing:
            try:
                _update_discord_forum_thread(
                    db_tournament=db_tournament,
                    application_id=application_id,
                    bot_token=bot_token,
                )
            except httpx.HTTPError as exc:
                log.warning(
                    'netsession_tourney.discord_forum_thread_sync_failed',
                    tournament_id=str(db_tournament.id),
                    thread_id=str(db_tournament.discord_thread_id),
                    error=type(exc).__name__,
                )
        return

    payload = _build_discord_forum_thread_payload(db_tournament)

    try:
        thread_id = _create_discord_forum_thread(
            application_id=application_id,
            bot_token=bot_token,
            forum_channel_id=db_tournament.discord_forum_channel_id,
            payload=payload,
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning(
            'netsession_tourney.discord_forum_thread_create_failed',
            tournament_id=str(db_tournament.id),
            error=type(exc).__name__,
        )
        return

    db_tournament.discord_thread_id = thread_id
    db_tournament.updated_at = datetime.utcnow()
    db.session.commit()

    _append_audit_log(
        actor_user_id=None,
        object_type='tournament',
        object_id=db_tournament.id,
        action='discord_thread_created',
        payload={'thread_id': thread_id},
        created_at=datetime.utcnow(),
    )
    db.session.commit()


def _update_discord_forum_thread(
    *,
    db_tournament: DbNetsessionTourneyTournament,
    application_id: str,
    bot_token: str,
) -> None:
    thread_id = db_tournament.discord_thread_id
    if not thread_id:
        return

    payload = _build_discord_forum_thread_payload(db_tournament)
    channel_payload: dict[str, Any] = {'name': payload['name']}
    if 'applied_tags' in payload:
        channel_payload['applied_tags'] = payload['applied_tags']

    try:
        _patch_discord_channel(
            application_id=application_id,
            bot_token=bot_token,
            channel_id=thread_id,
            payload=channel_payload,
        )
    except httpx.HTTPStatusError as exc:
        if _is_discord_resource_missing(exc):
            _clear_discord_thread_reference(
                db_tournament,
                audit_action='discord_thread_missing_reset',
                audit_payload={
                    'thread_id': thread_id,
                    'reason': 'thread_missing_while_updating',
                },
            )
            _sync_discord_thread_for_tournament(
                db_tournament, update_existing=False
            )
            return
        raise

    try:
        _patch_discord_forum_starter_message(
            application_id=application_id,
            bot_token=bot_token,
            thread_id=thread_id,
            payload=payload['message'],
        )
    except httpx.HTTPStatusError as exc:
        if not _is_discord_resource_missing(exc):
            raise
    except httpx.HTTPError:
        return


def _recover_deleted_discord_forum_thread(
    *,
    db_tournament: DbNetsessionTourneyTournament,
    failed_thread_id: str,
    exc: httpx.HTTPStatusError,
) -> str | None:
    if not _is_discord_resource_missing(exc):
        return None

    if db_tournament.discord_thread_id == failed_thread_id:
        _clear_discord_thread_reference(
            db_tournament,
            audit_action='discord_thread_missing_reset',
            audit_payload={
                'thread_id': failed_thread_id,
                'reason': 'message_delivery_failed_missing_thread',
            },
        )

    try:
        _sync_discord_thread_for_tournament(
            db_tournament, update_existing=False
        )
    except httpx.HTTPError:
        return None

    return db_tournament.discord_thread_id


def _clear_discord_thread_reference(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    audit_action: str,
    audit_payload: dict[str, Any],
) -> None:
    if not db_tournament.discord_thread_id:
        return

    db_tournament.discord_thread_id = None
    db_tournament.updated_at = datetime.utcnow()
    db.session.commit()

    _append_audit_log(
        actor_user_id=None,
        object_type='tournament',
        object_id=db_tournament.id,
        action=audit_action,
        payload=audit_payload,
        created_at=datetime.utcnow(),
    )
    db.session.commit()


def _is_discord_resource_missing(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code == 404


def _mark_discord_outbox_dead_letter(
    db_row: DbNetsessionTourneyDiscordOutbox,
    reason: str,
    now: datetime,
) -> None:
    db_row.status = DiscordOutboxStatus.dead_letter.value
    db_row.next_attempt_at = None
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _schedule_discord_outbox_retry(
    db_row: DbNetsessionTourneyDiscordOutbox,
    reason: str,
    now: datetime,
) -> None:
    if db_row.attempt_count >= DISCORD_MAX_ATTEMPTS:
        _mark_discord_outbox_dead_letter(
            db_row,
            f'Delivery failed repeatedly. Last error: {reason}',
            now,
        )
        return

    backoff_minutes = 2 ** min(db_row.attempt_count, 6)
    db_row.status = DiscordOutboxStatus.failed.value
    db_row.next_attempt_at = now + timedelta(minutes=backoff_minutes)
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _build_discord_tournament_finished_payload(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any]:
    payload: dict[str, Any] = {'slug': db_tournament.slug}
    result_summary = _build_discord_tournament_result_summary(db_tournament)
    if result_summary:
        payload['result_summary'] = result_summary
    return payload


def _build_discord_match_completed_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_match: DbNetsessionTourneyMatch,
    stage: Stage,
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
    ranking_data: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'stage_name': stage.name,
        'match_label': f'Match #{db_match.match_no}',
        'url': _build_site_match_path(db_tournament.slug, db_match.id),
    }

    result_summary = _build_discord_match_result_summary(
        stage=stage,
        db_slots=db_slots,
        db_participants_by_id=db_participants_by_id,
        winner_slot=winner_slot,
        score_data=score_data,
        ranking_data=ranking_data,
    )
    if result_summary:
        payload['result_summary'] = result_summary

    return payload


def _build_discord_match_result_summary(
    *,
    stage: Stage,
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
    ranking_data: dict[str, Any],
) -> dict[str, Any] | None:
    occupied_slots = [
        db_slot
        for db_slot in sorted(db_slots, key=lambda item: item.slot_no)
        if db_slot.participant_id is not None
        and db_slot.participant_id in db_participants_by_id
    ]
    if not occupied_slots:
        return None

    is_ffa_stage = stage.type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }

    if is_ffa_stage:
        raw_placements = (
            ranking_data.get('placements')
            if isinstance(ranking_data, dict)
            else None
        )
        raw_points = (
            ranking_data.get('points')
            if isinstance(ranking_data, dict)
            else None
        )
        if not isinstance(raw_placements, dict):
            return None

        rows: list[dict[str, Any]] = []
        for db_slot in occupied_slots:
            participant = db_participants_by_id.get(db_slot.participant_id)
            if participant is None:
                continue

            placement = raw_placements.get(str(db_slot.slot_no))
            if placement is None:
                placement = raw_placements.get(db_slot.slot_no)
            if placement is None:
                continue

            points = None
            if isinstance(raw_points, dict):
                points = raw_points.get(str(db_slot.slot_no))
                if points is None:
                    points = raw_points.get(db_slot.slot_no)

            rows.append(
                {
                    'position': int(placement),
                    'participant_name': participant.name,
                    'points': points,
                }
            )

        if not rows:
            return None

        rows.sort(key=lambda item: (item['position'], item['participant_name']))
        return {'format': 'ffa', 'rows': rows}

    parsed_scores = _parse_match_result_slot_scores(
        db_slots, score_data, winner_slot=winner_slot
    )
    rows = []
    for db_slot in occupied_slots:
        participant = db_participants_by_id.get(db_slot.participant_id)
        if participant is None:
            continue

        rows.append(
            {
                'slot_no': db_slot.slot_no,
                'participant_name': participant.name,
                'score': parsed_scores.get(db_slot.slot_no),
                'is_winner': winner_slot == db_slot.slot_no,
            }
        )

    if not rows:
        return None

    rows.sort(
        key=lambda item: (
            0 if item['is_winner'] else 1,
            item['slot_no'],
        )
    )
    return {'format': 'duel', 'rows': rows}


def _build_discord_tournament_result_summary(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any] | None:
    participants_by_id = {
        participant.id: participant
        for participant in get_participants_for_tournament(
            db_tournament.party_id, db_tournament.id
        )
    }
    if not participants_by_id:
        return None

    stages = get_stages_for_tournament(db_tournament.party_id, db_tournament.id)
    for stage in reversed(stages):
        ranked_participant_ids_result = _get_ranked_participant_ids_for_stage(
            stage.id, db_tournament.id
        )
        if ranked_participant_ids_result.is_err():
            continue

        placements: list[dict[str, Any]] = []
        for position, participant_id in enumerate(
            ranked_participant_ids_result.unwrap()[:8], start=1
        ):
            participant = participants_by_id.get(participant_id)
            if participant is None:
                continue
            placements.append(
                {
                    'position': position,
                    'participant_name': participant.name,
                }
            )

        if placements:
            return {
                'stage_name': stage.name,
                'placements': placements,
            }

    return None


def _build_discord_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_row: DbNetsessionTourneyDiscordOutbox,
) -> dict[str, Any]:
    payload_data = db_row.payload_json or {}
    event_name = db_row.event_name
    title = db_tournament.title
    url = _build_absolute_notification_url(
        db_tournament.party_id, _build_site_tournament_overview_path(db_tournament.slug)
    )
    brand_icon_url = _build_absolute_notification_url(
        db_tournament.party_id, '/static_sites/netsession/icon-192.png'
    )
    color = 0xFF2B00
    description = 'Es gibt ein neues Turnier-Update.'

    if event_name == 'manual_announcement':
        embed_title = 'Turnier-Update'
        description = str(payload_data.get('body') or '').strip() or description
        title = str(payload_data.get('title') or '').strip() or title
        custom_url = str(payload_data.get('url') or '').strip()
        if custom_url:
            url = _build_absolute_notification_url(
                db_tournament.party_id, custom_url
            )
    elif event_name == 'match_completed':
        embed_title = 'Match beendet'
        description = _build_discord_match_completed_description(
            title, payload_data
        )
        custom_url = str(payload_data.get('url') or '').strip()
        if custom_url:
            url = _build_absolute_notification_url(
                db_tournament.party_id, custom_url
            )
        color = 0x3B82F6
    elif event_name == 'stage_started':
        stage_name = str(payload_data.get('stage_name') or '').strip()
        embed_title = 'Stage gestartet'
        description = (
            f'**{title}**\n{stage_name} ist gestartet.'
            if stage_name
            else f'**{title}**\nEine neue Stage ist gestartet.'
        )
        title = stage_name or title
        color = 0xF97316
    elif event_name == 'tournament_finished':
        embed_title = 'Turnier beendet'
        description = _build_discord_tournament_finished_description(
            title, payload_data
        )
        color = 0x10B981
    elif event_name == 'tournament_canceled':
        embed_title = 'Turnier abgesagt'
        description = f'**{title}**\nDas Turnier wurde abgesagt.'
        color = 0xEF4444
    elif event_name == 'tournament_live':
        embed_title = 'Turnier live'
        description = f'**{title}**\nDas Turnier ist jetzt live.'
    else:
        embed_title = 'Turnier-Update'
        description = f'**{title}**\n{description}'

    fields = [
        {'name': 'Turnier', 'value': db_tournament.title[:1024], 'inline': True},
        {'name': 'Ereignis', 'value': embed_title[:1024], 'inline': True},
    ]
    if url:
        fields.append(
            {
                'name': 'Oeffnen',
                'value': f'[Turnierseite oeffnen]({url})',
                'inline': False,
            }
        )
    if event_name == 'tournament_finished':
        fields.extend(
            _build_discord_tournament_finished_fields(payload_data)
        )
    elif event_name == 'match_completed':
        fields.extend(_build_discord_match_completed_fields(payload_data))

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': embed_title[:256],
        'description': description[:4096],
        'color': color,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': db_row.created_at.replace(microsecond=0).isoformat() + 'Z',
    }
    if url:
        embed['url'] = url
    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }


def _build_discord_tournament_finished_description(
    tournament_title: str, payload_data: dict[str, Any]
) -> str:
    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return f'**{tournament_title}**\nDas Turnier wurde beendet.'

    placements = _normalize_discord_tournament_placements(
        result_summary.get('placements')
    )
    if not placements:
        return f'**{tournament_title}**\nDas Turnier wurde beendet.'

    winner_name = placements[0][1]
    stage_name = str(result_summary.get('stage_name') or '').strip()
    lines = [
        f'**{tournament_title}**',
        f'Gewonnen hat **{winner_name}**.',
    ]
    if stage_name:
        lines.append(f'Gewertet wurde die Abschluss-Stage **{stage_name}**.')
    return '\n'.join(lines)


def _build_discord_tournament_finished_fields(
    payload_data: dict[str, Any],
) -> list[dict[str, Any]]:
    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return []

    placements = _normalize_discord_tournament_placements(
        result_summary.get('placements')
    )
    if not placements:
        return []

    fields: list[dict[str, Any]] = []
    stage_name = str(result_summary.get('stage_name') or '').strip()
    if stage_name:
        fields.append(
            {
                'name': 'Abschluss-Stage',
                'value': stage_name[:1024],
                'inline': True,
            }
        )

    podium_lines = [
        _format_discord_tournament_placement(position, participant_name)
        for position, participant_name in placements[:3]
    ]
    if podium_lines:
        fields.append(
            {
                'name': 'Podium',
                'value': '\n'.join(podium_lines)[:1024],
                'inline': False,
            }
        )

    remaining_lines = [
        _format_discord_tournament_placement(position, participant_name)
        for position, participant_name in placements[3:]
    ]
    if remaining_lines:
        fields.append(
            {
                'name': 'Weitere Plaetze',
                'value': '\n'.join(remaining_lines)[:1024],
                'inline': False,
            }
        )

    return fields


def _build_discord_match_completed_description(
    tournament_title: str, payload_data: dict[str, Any]
) -> str:
    stage_name = str(payload_data.get('stage_name') or '').strip()
    match_label = str(payload_data.get('match_label') or '').strip()
    result_summary = payload_data.get('result_summary')

    lines = [f'**{tournament_title}**']
    if stage_name and match_label:
        lines.append(f'{stage_name} - {match_label} ist abgeschlossen.')
    elif match_label:
        lines.append(f'{match_label} ist abgeschlossen.')
    else:
        lines.append('Ein Match ist abgeschlossen.')

    if isinstance(result_summary, dict):
        rows = result_summary.get('rows')
        if isinstance(rows, list) and rows:
            winner_name = str(rows[0].get('participant_name') or '').strip()
            if winner_name:
                lines.append(f'Gewonnen hat **{winner_name}**.')

    return '\n'.join(lines)


def _build_discord_match_completed_fields(
    payload_data: dict[str, Any]
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    stage_name = str(payload_data.get('stage_name') or '').strip()
    if stage_name:
        fields.append(
            {
                'name': 'Stage',
                'value': stage_name[:1024],
                'inline': True,
            }
        )

    match_label = str(payload_data.get('match_label') or '').strip()
    if match_label:
        fields.append(
            {
                'name': 'Match',
                'value': match_label[:1024],
                'inline': True,
            }
        )

    result_summary = payload_data.get('result_summary')
    if not isinstance(result_summary, dict):
        return fields

    rows = result_summary.get('rows')
    if not isinstance(rows, list) or not rows:
        return fields

    if result_summary.get('format') == 'ffa':
        ranking_lines = []
        for row in rows[:8]:
            participant_name = str(row.get('participant_name') or '').strip()
            if not participant_name:
                continue
            try:
                position = int(row.get('position'))
            except (TypeError, ValueError):
                continue

            points = row.get('points')
            line = f'{position}. {participant_name}'
            if points is not None and str(points).strip():
                line += f' - {points} Pkt.'
            ranking_lines.append(line)

        if ranking_lines:
            fields.append(
                {
                    'name': 'Ranking',
                    'value': '\n'.join(ranking_lines)[:1024],
                    'inline': False,
                }
            )
    else:
        result_lines = []
        for row in rows[:8]:
            participant_name = str(row.get('participant_name') or '').strip()
            if not participant_name:
                continue
            score = row.get('score')
            score_suffix = (
                f' - {score}' if score is not None and str(score).strip() else ''
            )
            prefix = 'W' if row.get('is_winner') else '-'
            result_lines.append(f'{prefix} {participant_name}{score_suffix}')

        if result_lines:
            fields.append(
                {
                    'name': 'Ergebnis',
                    'value': '\n'.join(result_lines)[:1024],
                    'inline': False,
                }
            )

    return fields


def _normalize_discord_tournament_placements(
    raw_placements: Any,
) -> list[tuple[int, str]]:
    if not isinstance(raw_placements, list):
        return []

    normalized: list[tuple[int, str]] = []
    for item in raw_placements:
        if not isinstance(item, dict):
            continue

        participant_name = str(item.get('participant_name') or '').strip()
        if not participant_name:
            continue

        try:
            position = int(item.get('position'))
        except (TypeError, ValueError):
            continue

        if position < 1:
            continue

        normalized.append((position, participant_name))

    return normalized


def _format_discord_tournament_placement(
    position: int, participant_name: str
) -> str:
    marker = {1: '🥇', 2: '🥈', 3: '🥉'}.get(position, f'{position}.')
    return f'{marker} {participant_name}'


def _build_discord_forum_thread_payload(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any]:
    url = _build_absolute_notification_url(
        db_tournament.party_id, _build_site_tournament_overview_path(db_tournament.slug)
    )
    brand_icon_url = _build_absolute_notification_url(
        db_tournament.party_id, '/static_sites/netsession/icon-192.png'
    )
    image_url = (
        _build_absolute_notification_url(
            db_tournament.party_id, db_tournament.discord_forum_image_url
        )
        if db_tournament.discord_forum_image_url
        else None
    )
    description_lines = [f'**{db_tournament.title}**']
    if db_tournament.subtitle:
        description_lines.append(db_tournament.subtitle)
    description_lines.append(
        'Der Discord-Thread fuer dieses Turnier wurde eingerichtet.'
    )

    fields = [
        {'name': 'Turnier', 'value': db_tournament.title[:1024], 'inline': True},
    ]
    if db_tournament.game:
        fields.append(
            {'name': 'Spiel', 'value': db_tournament.game[:1024], 'inline': True}
        )
    if db_tournament.starts_at is not None:
        fields.append(
            {
                'name': 'Start',
                'value': db_tournament.starts_at.strftime('%d.%m.%Y %H:%M')[:1024],
                'inline': True,
            }
        )
    if url:
        fields.append(
            {
                'name': 'Link',
                'value': f'[Turnierseite oeffnen]({url})',
                'inline': False,
            }
        )

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': db_tournament.title[:256],
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    }
    if url:
        embed['url'] = url
    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url
    if image_url:
        embed['image'] = {'url': image_url}

    payload: dict[str, Any] = {
        'name': db_tournament.title[:100],
        'auto_archive_duration': 10080,
        'message': {
            'allowed_mentions': {'parse': []},
            'embeds': [embed],
        },
    }
    if db_tournament.discord_applied_tag_ids:
        payload['applied_tags'] = db_tournament.discord_applied_tag_ids

    return payload


def _build_discord_bot_headers(
    *, application_id: str, bot_token: str
) -> dict[str, str]:
    return {
        'Authorization': f'Bot {bot_token}',
        'Content-Type': 'application/json',
        'User-Agent': f'BYCEPS Netsession/{application_id}',
    }


def _create_discord_forum_thread(
    *,
    application_id: str,
    bot_token: str,
    forum_channel_id: str,
    payload: dict[str, Any],
) -> str:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.post(
            f'/channels/{forum_channel_id}/threads',
            json=payload,
        )
        response.raise_for_status()
        response_data = response.json()
        thread_id = str(response_data.get('id') or '').strip()
        if not thread_id:
            raise ValueError('Discord-Forum-Thread konnte nicht erstellt werden.')
        return thread_id


def _get_discord_channel(
    *,
    application_id: str,
    bot_token: str,
    channel_id: str,
) -> dict[str, Any]:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.get(f'/channels/{channel_id}')
        response.raise_for_status()
        return response.json()


def _patch_discord_channel(
    *,
    application_id: str,
    bot_token: str,
    channel_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.patch(f'/channels/{channel_id}', json=payload)
        response.raise_for_status()


def _patch_discord_forum_starter_message(
    *,
    application_id: str,
    bot_token: str,
    thread_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.patch(
            f'/channels/{thread_id}/messages/{thread_id}',
            json=payload,
        )
        response.raise_for_status()


def _post_discord_forum_message(
    *,
    application_id: str,
    bot_token: str,
    thread_id: str,
    payload: dict[str, Any],
) -> None:
    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_FORUM_TIMEOUT_SECONDS,
        headers=_build_discord_bot_headers(
            application_id=application_id, bot_token=bot_token
        ),
    ) as client:
        response = client.post(
            f'/channels/{thread_id}/messages',
            json=payload,
        )
        response.raise_for_status()


def _delete_stage_matches(stage_id: StageID) -> None:
    db_match_ids = db.session.scalars(
        select(DbNetsessionTourneyMatch.id).filter_by(stage_id=stage_id)
    ).all()
    if not db_match_ids:
        return

    db.session.execute(
        delete(DbNetsessionTourneyMatchChatMessage).filter(
            DbNetsessionTourneyMatchChatMessage.match_id.in_(db_match_ids)
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyResultReportReceipt).filter(
            DbNetsessionTourneyResultReportReceipt.match_id.in_(db_match_ids)
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyMatchResult).filter(
            DbNetsessionTourneyMatchResult.match_id.in_(db_match_ids)
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(db_match_ids)
        )
    )
    db.session.execute(delete(DbNetsessionTourneyMatch).filter_by(stage_id=stage_id))


def _delete_all_stages_for_tournament(tournament_id: TournamentID) -> int:
    stage_ids = db.session.scalars(
        select(DbNetsessionTourneyStage.id).filter_by(tournament_id=tournament_id)
    ).all()
    for stage_id in stage_ids:
        _delete_stage_matches(stage_id)

    db.session.execute(
        delete(DbNetsessionTourneyStage).filter_by(tournament_id=tournament_id)
    )
    return len(stage_ids)


def _is_builder_round_robin_summary_db_stage(
    db_stage: DbNetsessionTourneyStage,
) -> bool:
    settings = db_stage.settings_json or {}
    return (
        settings.get('builder_kind') == STAGE_BUILDER_KIND_V1
        and settings.get('builder_role') == 'preliminary'
        and db_stage.type == StageType.round_robin_groups.value
    )


def _is_builder_container_db_stage(
    db_stage: DbNetsessionTourneyStage,
) -> bool:
    settings = db_stage.settings_json or {}
    has_materialized_stage_ids = bool(
        settings.get('builder_materialized_stage_ids')
    )
    has_materialized_group_stage_ids = bool(
        settings.get('builder_materialized_group_stage_ids')
    ) and settings.get('builder_role') == 'preliminary'
    return settings.get('builder_kind') == STAGE_BUILDER_KIND_V1 and bool(
        has_materialized_stage_ids or has_materialized_group_stage_ids
    )


def _get_builder_generated_group_db_stages(
    tournament_id: TournamentID, preliminary_stage_id: StageID
) -> list[DbNetsessionTourneyStage]:
    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    return [
        db_stage
        for db_stage in db_stages
        if (db_stage.settings_json or {}).get('builder_role')
        == 'preliminary_group'
        and (db_stage.settings_json or {}).get('builder_preliminary_stage_id')
        == str(preliminary_stage_id)
    ]


def _get_builder_generated_child_db_stages(
    tournament_id: TournamentID, parent_stage_id: StageID
) -> list[DbNetsessionTourneyStage]:
    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    return [
        db_stage
        for db_stage in db_stages
        if (db_stage.settings_json or {}).get('builder_parent_stage_id')
        == str(parent_stage_id)
    ]


def _delete_builder_generated_child_stages(
    tournament_id: TournamentID,
    parent_stage_id: StageID,
    *,
    initiator: User,
) -> None:
    now = datetime.utcnow()
    for db_child_stage in _get_builder_generated_child_db_stages(
        tournament_id, parent_stage_id
    ):
        _delete_stage_matches(db_child_stage.id)
        db.session.delete(db_child_stage)
        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='stage',
            object_id=db_child_stage.id,
            action='stage_deleted',
            payload={
                'name': db_child_stage.name,
                'type': db_child_stage.type,
                'deleted_by_builder_container': True,
            },
            created_at=now,
        )


def _delete_builder_generated_group_stages(
    tournament_id: TournamentID,
    preliminary_stage_id: StageID,
    *,
    initiator: User,
) -> None:
    now = datetime.utcnow()
    for db_group_stage in _get_builder_generated_group_db_stages(
        tournament_id, preliminary_stage_id
    ):
        _delete_stage_matches(db_group_stage.id)
        db.session.delete(db_group_stage)
        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='stage',
            object_id=db_group_stage.id,
            action='stage_deleted',
            payload={
                'name': db_group_stage.name,
                'type': db_group_stage.type,
                'deleted_by_builder_container': True,
            },
            created_at=now,
        )


def _detach_builder_main_stage_from_preliminary_stage(
    tournament_id: TournamentID, preliminary_stage_id: StageID
) -> None:
    db_main_stage = _find_builder_main_stage_for_preliminary_stage(
        tournament_id, preliminary_stage_id
    )
    if db_main_stage is None:
        return

    settings = dict(db_main_stage.settings_json or {})
    settings.pop('builder_preliminary_stage_id', None)
    settings.pop('qualifier_source_stage_ids', None)
    settings.pop('qualifier_selection_mode', None)
    settings.pop('qualifier_top_n', None)
    settings.pop('builder_auto_qualifier_count', None)
    settings.pop('builder_materialized_group_stage_ids', None)
    settings['participant_source_mode'] = 'tournament'
    db_main_stage.settings_json = settings


def _renumber_stages_for_tournament(tournament_id: TournamentID) -> None:
    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    if not db_stages:
        return

    max_order_no = max(db_stage.order_no for db_stage in db_stages)
    temporary_order_no_base = max_order_no + len(db_stages) + 1

    # Move all rows out of the currently occupied order_no range first so the
    # final compacting step cannot violate the per-tournament unique
    # constraint, even if the UPDATE statements are executed in bulk.
    for index, db_stage in enumerate(db_stages, start=0):
        db_stage.order_no = temporary_order_no_base + index

    db.session.flush()

    for index, db_stage in enumerate(db_stages, start=1):
        db_stage.order_no = index


def _persist_generated_matches(
    *,
    tournament_id: TournamentID,
    stage_id: StageID,
    specs: list[MatchSpec],
    match_settings_by_round_and_match_no: (
        dict[tuple[int, int], dict[str, Any]] | None
    ) = None,
) -> list[Match]:
    now = datetime.utcnow()
    match_id_by_match_no: dict[int, MatchID] = {}
    source_slot_id_by_match_no: dict[int, MatchSlotID] = {}
    created_matches: list[DbNetsessionTourneyMatch] = []

    for spec in specs:
        db_match = DbNetsessionTourneyMatch(
            MatchID(generate_uuid7()),
            tournament_id,
            stage_id,
            spec.round_no,
            spec.match_no,
            now,
            state=MatchState(spec.state),
            settings_json=dict(
                (match_settings_by_round_and_match_no or {}).get(
                    (spec.round_no, spec.match_no), {}
                )
            ),
        )
        db.session.add(db_match)
        created_matches.append(db_match)
        match_id_by_match_no[spec.match_no] = db_match.id

    db.session.flush()

    for spec in specs:
        for slot in spec.slots:
            source_slot_id = None
            if slot.source_match_no is not None:
                source_slot_id = source_slot_id_by_match_no.get(slot.source_match_no)
            db_slot = DbNetsessionTourneyMatchSlot(
                MatchSlotID(generate_uuid7()),
                match_id_by_match_no[spec.match_no],
                slot.slot_no,
                participant_id=slot.participant_id,
                source_match_slot_id=source_slot_id,
                source_outcome=_parse_source_outcome(slot.source_outcome),
            )
            db.session.add(db_slot)
            if slot.slot_no == 1:
                source_slot_id_by_match_no[spec.match_no] = db_slot.id

    db.session.flush()
    return [_db_match_to_model(item) for item in created_matches]


def _auto_advance_byes(
    tournament_id: TournamentID, stage: Stage, *, engine: StageEngine
) -> None:
    while True:
        progressed = False
        db_matches = db.session.scalars(
            select(DbNetsessionTourneyMatch)
            .filter_by(tournament_id=tournament_id, stage_id=stage.id)
            .filter(
                DbNetsessionTourneyMatch.state.in_(
                    [MatchState.pending.value, MatchState.ready.value]
                )
            )
            .order_by(
                DbNetsessionTourneyMatch.round_no.asc(),
                DbNetsessionTourneyMatch.match_no.asc(),
            )
        ).all()
        for db_match in db_matches:
            db_slots = db.session.scalars(
                select(DbNetsessionTourneyMatchSlot)
                .filter_by(match_id=db_match.id)
                .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
            ).all()
            filled_slots = [slot for slot in db_slots if slot.participant_id]
            has_any_source_slots = any(
                slot.source_match_slot_id is not None for slot in db_slots
            )
            # Auto-advance only hard byes, not unresolved feeder slots.
            # A feeder slot with no participant is considered resolved if the
            # source match is already completed and produced no winner/loser
            # for that outcome path (e.g. loser path from a bye match).
            unresolved_source_slots = [
                slot
                for slot in db_slots
                if slot.participant_id is None
                and slot.source_match_slot_id is not None
                and (
                    (
                        source_slot := db.session.get(
                            DbNetsessionTourneyMatchSlot,
                            slot.source_match_slot_id,
                        )
                    )
                    is None
                    or (
                        source_match := db.session.get(
                            DbNetsessionTourneyMatch, source_slot.match_id
                        )
                    )
                    is None
                    or source_match.state != MatchState.completed.value
                )
            ]
            if unresolved_source_slots:
                continue

            winner_slot_no: int | None = None
            winner_participant_id: ParticipantID | None = None

            if len(filled_slots) == 1:
                winner_slot_no = filled_slots[0].slot_no
                winner_participant_id = filled_slots[0].participant_id
            elif len(filled_slots) == 0:
                # Propagate an explicitly empty feeder path (e.g. LB branch fed
                # only by bye matches), but never consume pre-created placeholder
                # matches that do not have resolved feeder sources yet.
                if not has_any_source_slots:
                    continue
                winner_slot_no = None
                winner_participant_id = None
            else:
                continue

            db_result = DbNetsessionTourneyMatchResult(
                MatchResultID(generate_uuid7()),
                db_match.id,
                datetime.utcnow(),
                winner_slot=winner_slot_no,
                score_json={
                    'walkover': True,
                    'empty_match': len(filled_slots) == 0,
                },
                ranking_json={},
                submitted_by_user_id=None,
            )
            db.session.add(db_result)
            db_match.state = MatchState.completed.value
            db_match.updated_at = datetime.utcnow()

            _advance_stage_from_match(
                tournament_id=tournament_id,
                stage=stage,
                source_match_id=db_match.id,
                winner_participant_id=winner_participant_id,
                engine=engine,
            )
            _update_optional_double_grand_final_state(
                stage=stage, source_match_id=db_match.id
            )
            progressed = True
        db.session.commit()
        if not progressed:
            return


def _seed_swiss_follow_up_rounds(
    *,
    tournament_id: TournamentID,
    stage: Stage,
) -> list[MatchID]:
    newly_ready_match_ids: list[MatchID] = []
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id, stage_id=stage.id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return []

    match_ids = [match.id for match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    results_by_match_id = {
        db_result.match_id: db_result
        for db_result in db.session.scalars(
            select(DbNetsessionTourneyMatchResult).filter(
                DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
            )
        ).all()
    }

    participant_ids = {
        db_slot.participant_id
        for db_slot in db_slots
        if db_slot.participant_id is not None
    }
    participants = [
        _db_participant_to_model(db_participant)
        for db_participant in db.session.scalars(
            select(DbNetsessionTourneyParticipant).filter(
                DbNetsessionTourneyParticipant.id.in_(participant_ids)
            )
        ).all()
    ]
    if not participants:
        return []

    round_count = _get_round_count_for_swiss_stage(
        stage, participant_count=len(participants)
    )
    layout = _build_swiss_round_layout(len(participants), round_count)
    matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = defaultdict(list)
    for db_match in db_matches:
        matches_by_round_no[db_match.round_no].append(db_match)

    for round_layout in layout[1:]:
        round_no = round_layout['round_no']
        previous_round_matches = matches_by_round_no.get(round_no - 1, [])
        if not previous_round_matches or any(
            match.state != MatchState.completed.value
            for match in previous_round_matches
        ):
            return []

        target_matches = sorted(
            matches_by_round_no.get(round_no, []),
            key=lambda match: match.match_no,
        )
        if not target_matches:
            return []

        if any(
            slot.participant_id is not None
            for match in target_matches
            for slot in slots_by_match_id.get(match.id, [])
        ):
            continue

        seeded_specs = _build_follow_up_swiss_round_specs(
            participants=participants,
            db_matches=db_matches,
            slots_by_match_id=slots_by_match_id,
            results_by_match_id=results_by_match_id,
            next_round_no=round_no,
            first_match_no=target_matches[0].match_no,
            round_count=round_count,
        )
        if not seeded_specs:
            continue

        specs_by_match_no = {
            spec.match_no: spec
            for spec in seeded_specs
        }
        for db_match in target_matches:
            spec = specs_by_match_no.get(db_match.match_no)
            if spec is None:
                continue

            db_match_slots = sorted(
                slots_by_match_id.get(db_match.id, []),
                key=lambda slot: slot.slot_no,
            )
            participant_id_by_slot_no = {
                slot.slot_no: slot.participant_id for slot in spec.slots
            }
            for db_slot in db_match_slots:
                db_slot.participant_id = participant_id_by_slot_no.get(
                    db_slot.slot_no
                )

            next_state = _calculate_match_state_for_slots(
                tournament_status=payload.tournament.status.value,
                db_match_slots=db_match_slots,
            )
            db_match.state = next_state.value
            if next_state == MatchState.ready:
                if db_match.id not in newly_ready_match_ids:
                    newly_ready_match_ids.append(db_match.id)
            db_match.updated_at = datetime.utcnow()

    return newly_ready_match_ids


def _advance_stage_from_match(
    *,
    tournament_id: TournamentID,
    stage: Stage,
    source_match_id: MatchID,
    winner_participant_id: ParticipantID | None,
    engine: StageEngine | None = None,
) -> None:
    if engine is None:
        engine = find_stage_engine(stage.type)
    if engine is None:
        return

    if stage.type == StageType.swiss:
        ready_match_ids = _seed_swiss_follow_up_rounds(
            tournament_id=tournament_id,
            stage=stage,
        ) or []
        for match_id in ready_match_ids:
            db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
            if db_match is None:
                continue
            _enqueue_match_ready_notifications(db_match)
        return

    source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            match_id=source_match_id, slot_no=1
        )
    )
    if source_slot is None:
        return

    source_match_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=source_match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    source_participant_ids = [
        slot.participant_id
        for slot in source_match_slots
        if slot.participant_id is not None
    ]
    loser_participant_id: ParticipantID | None = None
    if winner_participant_id is not None:
        for participant_id in source_participant_ids:
            if participant_id != winner_participant_id:
                loser_participant_id = participant_id
                break

    downstream_db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            source_match_slot_id=source_slot.id
        )
    ).all()
    downstream_winner_slots = [
        (db_slot.match_id, db_slot.slot_no)
        for db_slot in downstream_db_slots
        if db_slot.source_outcome != SourceOutcome.loser.value
    ]
    downstream_loser_slots = [
        (db_slot.match_id, db_slot.slot_no)
        for db_slot in downstream_db_slots
        if db_slot.source_outcome == SourceOutcome.loser.value
    ]

    if stage.type in {
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }:
        ranked_participant_ids = _get_ffa_single_elimination_qualifier_ids(
            source_match_id,
            source_match_slots,
            len(downstream_winner_slots),
        )
        updates = [
            (
                match_id,
                slot_no,
                ranked_participant_ids[index]
                if index < len(ranked_participant_ids)
                else None,
            )
            for index, (match_id, slot_no) in enumerate(
                sorted(downstream_winner_slots, key=lambda item: (item[0], item[1]))
            )
        ]
    else:
        updates = engine.advance(
            stage, winner_participant_id, downstream_winner_slots
        )
    updates.extend(
        (
            match_id,
            slot_no,
            loser_participant_id,
        )
        for match_id, slot_no in downstream_loser_slots
    )
    ready_match_ids: set[MatchID] = set()
    for match_id, slot_no, participant_id in updates:
        db_slot = db.session.scalar(
            select(DbNetsessionTourneyMatchSlot).filter_by(
                match_id=match_id,
                slot_no=slot_no,
            )
        )
        if db_slot is None:
            continue
        db_slot.participant_id = participant_id

        db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
        if db_match is None:
            continue
        previous_state = MatchState(db_match.state)
        db_match_slots = db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
        ).all()
        next_state = _calculate_match_state_for_slots(
            tournament_status=_get_tournament_status_value(tournament_id),
            db_match_slots=db_match_slots,
        )
        db_match.state = next_state.value
        db_match.updated_at = datetime.utcnow()
        if previous_state != MatchState.ready and next_state == MatchState.ready:
            ready_match_ids.add(match_id)

    db.session.commit()

    for match_id in ready_match_ids:
        db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
        if db_match is None or db_match.state != MatchState.ready.value:
            continue

        _enqueue_match_ready_notifications(db_match)
    db.session.commit()


def _get_ffa_single_elimination_qualifier_ids(
    source_match_id: MatchID,
    source_match_slots: list[DbNetsessionTourneyMatchSlot],
    qualifier_count: int,
) -> list[ParticipantID]:
    if qualifier_count < 1:
        return []

    filled_slots = [
        slot for slot in source_match_slots if slot.participant_id is not None
    ]
    if not filled_slots:
        return []

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=source_match_id)
    )

    placements_by_slot_no: dict[int, int] = {}
    if db_result is not None and isinstance(db_result.ranking_json, dict):
        raw_placements = db_result.ranking_json.get('placements')
        if isinstance(raw_placements, dict):
            for slot in filled_slots:
                raw_value = raw_placements.get(str(slot.slot_no))
                if raw_value is None:
                    raw_value = raw_placements.get(slot.slot_no)
                try:
                    placements_by_slot_no[slot.slot_no] = int(raw_value)
                except (TypeError, ValueError):
                    continue

    sorted_slots = sorted(
        filled_slots,
        key=lambda slot: (
            placements_by_slot_no.get(slot.slot_no, 999_999),
            0
            if db_result is not None and db_result.winner_slot == slot.slot_no
            else 1,
            slot.slot_no,
        ),
    )

    participant_ids = [
        slot.participant_id for slot in sorted_slots if slot.participant_id is not None
    ]
    return participant_ids[:qualifier_count]


def _is_grand_final_reset_skipped_score(score_json: dict[str, Any] | None) -> bool:
    if not isinstance(score_json, dict):
        return False

    return bool(score_json.get(DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG))


def _is_match_marked_as_skipped_double_grand_final(
    stage: Stage, match_id: MatchID
) -> bool:
    if stage.type != StageType.double_elimination_double_grand_final:
        return False

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is None:
        return False

    return _is_grand_final_reset_skipped_score(db_result.score_json)


def _update_optional_double_grand_final_state(
    *, stage: Stage, source_match_id: MatchID
) -> None:
    if stage.type != StageType.double_elimination_double_grand_final:
        return

    db_source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            match_id=source_match_id, slot_no=1
        )
    )
    if db_source_slot is None:
        return

    downstream_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            source_match_slot_id=db_source_slot.id
        )
    ).all()
    if not downstream_slots:
        return

    downstream_slots_by_match_id = defaultdict(list)
    for db_slot in downstream_slots:
        downstream_slots_by_match_id[db_slot.match_id].append(db_slot)

    reset_match_id = None
    for match_id, slots in downstream_slots_by_match_id.items():
        outcomes = {slot.source_outcome for slot in slots}
        if outcomes == {SourceOutcome.winner.value, SourceOutcome.loser.value}:
            reset_match_id = match_id
            break

    if reset_match_id is None:
        return

    db_source_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=source_match_id)
    )
    if db_source_result is None or db_source_result.winner_slot is None:
        return

    db_reset_match = db.session.get(DbNetsessionTourneyMatch, reset_match_id)
    if db_reset_match is None:
        return

    db_reset_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=reset_match_id)
    )
    now = datetime.utcnow()

    should_skip_reset_match = db_source_result.winner_slot == 1
    if should_skip_reset_match:
        if (
            db_reset_result is not None
            and not _is_grand_final_reset_skipped_score(db_reset_result.score_json)
        ):
            return

        if db_reset_result is None:
            db_reset_result = DbNetsessionTourneyMatchResult(
                MatchResultID(generate_uuid7()),
                reset_match_id,
                now,
                winner_slot=None,
                score_json={
                    'display': '-',
                    DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG: True,
                },
                ranking_json={},
                submitted_by_user_id=None,
            )
            db.session.add(db_reset_result)
        else:
            db_reset_result.winner_slot = None
            db_reset_result.score_json = {
                **(db_reset_result.score_json or {}),
                DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG: True,
            }
            db_reset_result.updated_at = now

        db_reset_match.state = MatchState.completed.value
        db_reset_match.updated_at = now
        return

    if db_reset_result and _is_grand_final_reset_skipped_score(
        db_reset_result.score_json
    ):
        db.session.delete(db_reset_result)

    db_reset_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=reset_match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    db_reset_match.state = _calculate_match_state_for_slots(
        tournament_status=_get_tournament_status_value(db_reset_match.tournament_id),
        db_match_slots=db_reset_slots,
    ).value
    db_reset_match.updated_at = now


def _append_notification_for_match_report(
    db_match: DbNetsessionTourneyMatch, stage: Stage, actor_user_id: UserID
) -> None:
    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_match.tournament_id
    )
    _append_notifications_for_match(
        db_match,
        actor_user_id=actor_user_id,
        kind='result_submitted',
        payload={
            'stage_id': str(stage.id),
            'match_id': str(db_match.id),
            'state': db_match.state,
            'url': (
                _build_site_match_path(
                    db_tournament.slug, db_match.id
                )
                if db_tournament is not None
                else None
            ),
        },
    )
    db.session.commit()


def _activate_prepared_stages_for_live_tournament(
    tournament_id: TournamentID, stages: list[Stage]
) -> StageID | None:
    stage_ids_with_matches = set(
        db.session.scalars(
            select(DbNetsessionTourneyMatch.stage_id)
            .filter_by(tournament_id=tournament_id)
            .distinct()
        ).all()
    )
    if not stage_ids_with_matches:
        return None

    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()
    db_stage_by_id = {db_stage.id: db_stage for db_stage in db_stages}

    first_live_stage_id = None
    for stage in stages:
        if stage.id not in stage_ids_with_matches:
            continue

        db_stage = db_stage_by_id.get(stage.id)
        if db_stage is None:
            continue

        if db_stage.status == StageStatus.draft.value:
            db_stage.status = StageStatus.live.value
            db_stage.updated_at = datetime.utcnow()

        if first_live_stage_id is None:
            first_live_stage_id = stage.id

    return first_live_stage_id


def _activate_prepared_matches_for_live_tournament(
    tournament_id: TournamentID,
) -> list[DbNetsessionTourneyMatch]:
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyMatch.stage_id.asc(),
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return []

    match_ids = [db_match.id for db_match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        _get_participant_status_value_by_participant_id_for_slots(db_slots)
    )

    ready_matches: list[DbNetsessionTourneyMatch] = []
    for db_match in db_matches:
        if db_match.state == MatchState.completed.value:
            continue

        next_state = _calculate_match_state_for_slots(
            tournament_status=TournamentStatus.live.value,
            db_match_slots=slots_by_match_id.get(db_match.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        )
        db_match.state = next_state.value
        db_match.updated_at = datetime.utcnow()
        if next_state == MatchState.ready:
            ready_matches.append(db_match)

    return ready_matches


def _demote_prepared_matches_for_draft_tournament(
    tournament_id: TournamentID,
) -> None:
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch).filter_by(tournament_id=tournament_id)
    ).all()
    if not db_matches:
        return

    match_ids = [db_match.id for db_match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        _get_participant_status_value_by_participant_id_for_slots(db_slots)
    )

    for db_match in db_matches:
        if db_match.state == MatchState.completed.value:
            continue

        db_match.state = _calculate_match_state_for_slots(
            tournament_status=TournamentStatus.draft.value,
            db_match_slots=slots_by_match_id.get(db_match.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        ).value
        db_match.updated_at = datetime.utcnow()


def _get_tournament_status_value(tournament_id: TournamentID) -> str:
    return (
        db.session.scalar(
            select(DbNetsessionTourneyTournament.status).filter_by(
                id=tournament_id
            )
        )
        or TournamentStatus.draft.value
    )


def _calculate_match_state_for_slots(
    *,
    tournament_status: str,
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
    participant_status_value_by_participant_id: dict[ParticipantID, str] | None = None,
) -> MatchState:
    if not db_match_slots:
        return MatchState.pending

    participant_ids = [
        db_slot.participant_id
        for db_slot in db_match_slots
        if db_slot.participant_id is not None
    ]
    if len(participant_ids) != len(db_match_slots):
        return MatchState.pending

    if participant_status_value_by_participant_id is None:
        participant_status_value_by_participant_id = (
            _get_participant_status_value_by_participant_id(participant_ids)
        )

    if any(
        participant_status_value_by_participant_id.get(participant_id)
        not in BRACKET_READY_PARTICIPANT_STATUS_VALUES
        for participant_id in participant_ids
    ):
        return MatchState.pending

    if tournament_status == TournamentStatus.live.value:
        return MatchState.ready

    return MatchState.pending


def _get_participant_status_value_by_participant_id_for_slots(
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
) -> dict[ParticipantID, str]:
    participant_ids = {
        db_slot.participant_id
        for db_slot in db_match_slots
        if db_slot.participant_id is not None
    }
    return _get_participant_status_value_by_participant_id(participant_ids)


def _get_participant_status_value_by_participant_id(
    participant_ids: Iterable[ParticipantID],
) -> dict[ParticipantID, str]:
    participant_ids = set(participant_ids)
    if not participant_ids:
        return {}

    rows = db.session.execute(
        select(
            DbNetsessionTourneyParticipant.id,
            DbNetsessionTourneyParticipant.status,
        ).filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
    ).all()
    return {participant_id: status for participant_id, status in rows}


def _enqueue_match_ready_notifications(
    db_match: DbNetsessionTourneyMatch,
) -> None:
    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_match.tournament_id
    )
    if db_tournament is None:
        return

    if db_tournament.status != TournamentStatus.live.value:
        return

    _append_audit_log(
        actor_user_id=None,
        object_type='match',
        object_id=db_match.id,
        action='match_ready',
        payload={'stage_id': str(db_match.stage_id)},
        created_at=datetime.utcnow(),
    )

    _append_notifications_for_match(
        db_match,
        actor_user_id=None,
        kind='match_ready',
        payload={
            'match_id': str(db_match.id),
            'stage_id': str(db_match.stage_id),
            'url': _build_site_match_path(db_tournament.slug, db_match.id),
        },
    )

    _enqueue_flatout2_host_assignment_notifications(db_match)


def _enqueue_flatout2_host_assignment_notifications(
    db_match: DbNetsessionTourneyMatch,
) -> None:
    payload = _build_flatout2_host_notification_payload(db_match)
    if payload is None:
        return

    recipient_user_ids = _get_selected_host_user_ids(db_match)
    if not recipient_user_ids:
        return

    now = datetime.utcnow()
    for user_id in recipient_user_ids:
        _append_notification(
            tournament_id=db_match.tournament_id,
            user_id=user_id,
            kind='flatout2_host_assigned',
            payload=payload,
            created_at=now,
        )


def _build_flatout2_host_notification_payload(
    db_match: DbNetsessionTourneyMatch,
) -> dict[str, Any] | None:
    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None or db_stage.type != StageType.ffa_flatout2_single_elimination.value:
        return None

    host_participant_id = _get_match_host_participant_id(db_match)
    if host_participant_id is None:
        return None

    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_match.tournament_id
    )
    if db_tournament is None or db_tournament.status != TournamentStatus.live.value:
        return None

    round_races = _get_flatout2_round_races(db_match.settings_json or {})

    return {
        'match_id': str(db_match.id),
        'stage_id': str(db_match.stage_id),
        'title': db_tournament.title,
        'round_no': db_match.round_no,
        'url': _build_site_match_path(db_tournament.slug, db_match.id),
        'flatout2_round_races': round_races,
    }


def _get_flatout2_round_races(
    match_settings: dict[str, Any]
) -> list[dict[str, str]]:
    if not isinstance(match_settings, dict):
        return []

    raw_round_races = match_settings.get('flatout2_races')
    if not isinstance(raw_round_races, list):
        return []

    normalized_races = []
    for race in raw_round_races:
        if not isinstance(race, dict):
            continue
        mode = str(race.get('mode') or '').strip() or 'single_race'
        track = str(race.get('track') or '').strip()
        vehicle = str(race.get('vehicle') or '').strip()
        if not track or not vehicle:
            continue
        normalized_races.append(
            {'mode': mode, 'track': track, 'vehicle': vehicle}
        )

    return normalized_races


def _get_match_host_participant_id(
    db_match: DbNetsessionTourneyMatch,
) -> ParticipantID | None:
    raw_value = (db_match.settings_json or {}).get('host_participant_id')
    if not raw_value:
        return None

    try:
        return ParticipantID(UUID(str(raw_value)))
    except (TypeError, ValueError):
        return None


def _get_selected_host_user_ids(
    db_match: DbNetsessionTourneyMatch,
) -> set[UserID]:
    participant_id = _get_match_host_participant_id(db_match)
    if participant_id is None:
        return set()

    db_participant = db.session.get(DbNetsessionTourneyParticipant, participant_id)
    if (
        db_participant is None
        or db_participant.status not in ACTIVE_PARTICIPANT_STATUS_VALUES
    ):
        return set()

    user_ids = {
        db_participant.user_id,
        db_participant.manager_user_id,
    } - {None}
    user_ids.update(
        db.session.scalars(
            select(DbNetsessionTourneyTeamMember.user_id).filter_by(
                participant_id=participant_id
            )
        ).all()
    )
    return user_ids


def _append_notifications_for_match(
    db_match: DbNetsessionTourneyMatch,
    *,
    actor_user_id: UserID | None,
    kind: str,
    payload: dict[str, Any],
) -> None:
    recipients = _get_match_involved_user_ids(db_match.id)
    if actor_user_id is not None:
        recipients.discard(actor_user_id)

    now = datetime.utcnow()
    for user_id in recipients:
        _append_notification(
            tournament_id=db_match.tournament_id,
            user_id=user_id,
            kind=kind,
            payload=payload,
            created_at=now,
        )


def _append_notifications_for_tournament(
    tournament_id: TournamentID,
    *,
    actor_user_id: UserID | None,
    kind: str,
    payload: dict[str, Any],
) -> None:
    recipients = _get_active_user_ids_for_tournament(tournament_id)
    if actor_user_id is not None:
        recipients.discard(actor_user_id)

    now = datetime.utcnow()
    for user_id in recipients:
        _append_notification(
            tournament_id=tournament_id,
            user_id=user_id,
            kind=kind,
            payload=payload,
            created_at=now,
        )


def _get_match_involved_user_ids(match_id: MatchID) -> set[UserID]:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
    ).all()
    participant_ids = [slot.participant_id for slot in db_slots if slot.participant_id]
    if not participant_ids:
        return set()

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    participant_ids = [participant.id for participant in db_participants]
    user_ids = {
        participant.user_id
        for participant in db_participants
        if participant.user_id is not None
    }
    user_ids.update(
        participant.manager_user_id
        for participant in db_participants
        if participant.manager_user_id is not None
    )
    user_ids.update(
        db.session.scalars(
            select(DbNetsessionTourneyTeamMember.user_id).filter(
                DbNetsessionTourneyTeamMember.participant_id.in_(participant_ids)
            )
        ).all()
    )
    return user_ids


def _get_active_user_ids_for_tournament(
    tournament_id: TournamentID,
) -> set[UserID]:
    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    participant_ids = [participant.id for participant in db_participants]
    user_ids = {
        participant.user_id
        for participant in db_participants
        if participant.user_id is not None
    }
    user_ids.update(
        participant.manager_user_id
        for participant in db_participants
        if participant.manager_user_id is not None
    )
    if participant_ids:
        user_ids.update(
            db.session.scalars(
                select(DbNetsessionTourneyTeamMember.user_id).filter(
                    DbNetsessionTourneyTeamMember.participant_id.in_(
                        participant_ids
                    )
                )
            ).all()
        )
    return user_ids


def _append_audit_log(
    *,
    actor_user_id: UserID | None,
    object_type: str,
    object_id,
    action: str,
    payload: dict[str, Any],
    created_at: datetime,
) -> None:
    db.session.add(
        DbNetsessionTourneyAuditLog(
            AuditLogID(generate_uuid7()),
            object_type,
            object_id,
            action,
            created_at,
            actor_user_id=actor_user_id,
            payload_json=payload,
        )
    )


def _append_notification(
    *,
    tournament_id: TournamentID,
    user_id: UserID,
    kind: str,
    payload: dict[str, Any],
    created_at: datetime,
) -> None:
    db_notification = DbNetsessionTourneyNotification(
        generate_uuid7(),
        tournament_id,
        user_id,
        kind,
        payload,
        created_at,
    )
    db.session.add(db_notification)

    db_tournament = db.session.get(DbNetsessionTourneyTournament, tournament_id)
    if (
        db_tournament is not None
        and kind in BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS
        and is_browser_push_enabled_for_party(db_tournament.party_id)
        and has_active_browser_push_subscription_for_user(
            db_tournament.party_id, user_id
        )
    ):
        db.session.add(
            DbNetsessionTourneyBrowserPushOutbox(
                BrowserPushOutboxID(generate_uuid7()),
                db_notification.id,
                created_at,
            )
        )

    if (
        db_tournament is not None
        and kind in DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS
        and is_discord_dm_enabled_for_party(db_tournament.party_id)
        and db_tournament.discord_dm_enabled
        and kind in (db_tournament.discord_dm_event_mask or [])
        and has_active_discord_dm_subscription_for_user(
            db_tournament.party_id, user_id
        )
    ):
        connected_account = (
            external_accounts_service.find_connected_external_account_for_user_and_service(
                user_id, 'discord'
            )
        )
        if connected_account is not None and connected_account.external_id:
            db.session.add(
                DbNetsessionTourneyDiscordDmOutbox(
                    DiscordDmOutboxID(generate_uuid7()),
                    db_notification.id,
                    created_at,
                )
            )


def _mark_browser_push_outbox_dead_letter(
    db_row: DbNetsessionTourneyBrowserPushOutbox,
    reason: str,
    now: datetime,
) -> None:
    db_row.status = BrowserPushOutboxStatus.dead_letter.value
    db_row.next_attempt_at = None
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _schedule_browser_push_outbox_retry(
    db_row: DbNetsessionTourneyBrowserPushOutbox,
    reason: str,
    now: datetime,
) -> None:
    if db_row.attempt_count >= BROWSER_PUSH_MAX_ATTEMPTS:
        _mark_browser_push_outbox_dead_letter(
            db_row,
            f'Delivery failed repeatedly. Last error: {reason}',
            now,
        )
        return

    backoff_minutes = 2 ** min(db_row.attempt_count, 6)
    db_row.status = BrowserPushOutboxStatus.failed.value
    db_row.next_attempt_at = now + timedelta(minutes=backoff_minutes)
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _build_browser_push_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_notification: DbNetsessionTourneyNotification,
) -> dict[str, Any]:
    payload = dict(db_notification.payload_json or {})
    kind = db_notification.kind
    match_label = _build_browser_push_match_label(payload)
    title = str(payload.get('title') or '').strip() or db_tournament.title

    if kind == 'tournament_live':
        body = 'Turnier ist jetzt live.'
    elif kind == 'tournament_closed':
        body = 'Turnier wurde beendet.'
    elif kind == 'tournament_canceled':
        body = 'Turnier wurde abgesagt.'
    elif kind == 'manual_announcement':
        body = str(payload.get('body') or '').strip() or 'Es gibt ein neues Turnier-Update.'
    elif kind == 'match_ready':
        body = (
            f'{match_label} ist spielbereit.'
            if match_label
            else 'Dein Match ist spielbereit.'
        )
    elif kind == 'flatout2_host_assigned':
        first_race_summary = _build_flatout2_first_race_summary(payload)
        base_body = (
            f'Du wurdest als Host für {match_label} ausgewählt.'
            if match_label
            else 'Du wurdest als Host für ein Match ausgewählt.'
        )
        body = (
            f'{base_body} {first_race_summary}'
            if first_race_summary
            else base_body
        )
    elif kind == 'result_submitted':
        body = (
            f'{match_label}: Ergebnis wurde übermittelt.'
            if match_label
            else 'Für dein Match wurde ein Ergebnis übermittelt.'
        )
    elif kind == 'schedule_changed':
        body = (
            f'{match_label}: Matchzeit wurde geändert.'
            if match_label
            else 'Die Matchzeit wurde geändert.'
        )
    elif kind == 'dispute_opened':
        body = (
            f'{match_label}: Streitfall wurde geöffnet.'
            if match_label
            else 'Für dein Match wurde ein Streitfall geöffnet.'
        )
    elif kind == 'chat_message_posted':
        body_preview = str(payload.get('body_preview') or '').strip()
        body = (
            (
                f'{match_label}: Neue Nachricht - {body_preview}'
                if match_label
                else f'Neue Match-Nachricht: {body_preview}'
            )
            if body_preview
            else (
                f'{match_label}: Neue Match-Nachricht.'
                if match_label
                else 'Neue Match-Nachricht.'
            )
        )
    else:
        body = 'Es gibt ein neues Update.'

    url = payload.get('url')
    if not isinstance(url, str) or not url:
        url = f'/ns-tourneys/{db_tournament.slug}'

    if kind == 'manual_announcement':
        tag_suffix = db_notification.id
        renotify = True
    else:
        tag_suffix = (
            payload.get('match_id') or payload.get('slug') or db_tournament.id
        )
        renotify = False

    icon_url, image_url = _build_browser_push_logo_urls(db_tournament)
    return {
        'title': title,
        'body': body[:180],
        'url': url,
        'tag': f'netsession-tourney-{kind}-{tag_suffix}',
        'renotify': renotify,
        'icon': icon_url,
        'badge': _build_browser_push_badge_url(),
        'image': image_url,
    }


def _mark_discord_dm_outbox_dead_letter(
    db_row: DbNetsessionTourneyDiscordDmOutbox,
    reason: str,
    now: datetime,
) -> None:
    db_row.status = DiscordDmOutboxStatus.dead_letter.value
    db_row.next_attempt_at = None
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _schedule_discord_dm_outbox_retry(
    db_row: DbNetsessionTourneyDiscordDmOutbox,
    reason: str,
    now: datetime,
) -> None:
    if db_row.attempt_count >= DISCORD_DM_MAX_ATTEMPTS:
        _mark_discord_dm_outbox_dead_letter(
            db_row,
            f'Zustellung wiederholt fehlgeschlagen. Letzter Fehler: {reason}',
            now,
        )
        return

    backoff_minutes = 2 ** min(db_row.attempt_count, 6)
    db_row.status = DiscordDmOutboxStatus.failed.value
    db_row.next_attempt_at = now + timedelta(minutes=backoff_minutes)
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _build_discord_dm_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_notification: DbNetsessionTourneyNotification,
) -> dict[str, Any]:
    browser_payload = _build_browser_push_message_payload(
        db_tournament, db_notification
    )
    payload = dict(db_notification.payload_json or {})
    kind = db_notification.kind
    match_label = _build_browser_push_match_label(payload)
    title = str(browser_payload.get('title') or '').strip() or db_tournament.title
    body = str(browser_payload.get('body') or '').strip() or 'Es gibt ein neues Update.'
    url = _build_absolute_notification_url(
        db_tournament.party_id,
        str(browser_payload.get('url') or f'/ns-tourneys/{db_tournament.slug}'),
    )
    icon_url, _image_url = _build_browser_push_logo_urls(db_tournament)
    brand_icon_url = (
        _build_absolute_notification_url(db_tournament.party_id, icon_url)
        if icon_url
        else None
    )
    thumbnail_source_url = db_tournament.logo_url or icon_url
    thumbnail_url = (
        _build_absolute_notification_url(
            db_tournament.party_id, thumbnail_source_url
        )
        if thumbnail_source_url
        else None
    )

    event_meta_by_kind = {
        'tournament_live': {
            'emoji': '🟢',
            'label': 'Turnier live',
            'headline': 'Turnier ist jetzt live',
        },
        'tournament_canceled': {
            'emoji': '⛔',
            'label': 'Turnier abgesagt',
            'headline': 'Turnier wurde abgesagt',
        },
        'match_ready': {
            'emoji': '🎮',
            'label': 'Match spielbereit',
            'headline': 'Match ist spielbereit',
        },
        'flatout2_host_assigned': {
            'emoji': '🏁',
            'label': 'Host ausgewählt',
            'headline': 'Du bist Host für das nächste Rennen',
        },
        'result_submitted': {
            'emoji': '📝',
            'label': 'Ergebnis übermittelt',
            'headline': 'Ergebnis wurde übermittelt',
        },
    }
    event_meta = event_meta_by_kind.get(
        kind,
        {
            'emoji': '🔔',
            'label': 'Benachrichtigung',
            'headline': 'Neues Update',
        },
    )

    description_lines = [f'**{db_tournament.title}**', body]
    fields = [
        {
            'name': 'Ereignis',
            'value': str(event_meta['label'])[:1024],
            'inline': True,
        },
        {
            'name': 'Turnier',
            'value': db_tournament.title[:1024],
            'inline': True,
        },
    ]

    if match_label:
        fields.append(
            {
                'name': 'Spiel',
                'value': match_label[:1024],
                'inline': True,
            }
        )

    if kind == 'flatout2_host_assigned':
        round_no = payload.get('round_no')
        if round_no:
            fields.append(
                {
                    'name': 'Runde',
                    'value': str(round_no)[:1024],
                    'inline': True,
                }
            )
        race_lines = _build_flatout2_round_race_lines(payload)
        if race_lines:
            fields.append(
                {
                    'name': 'Rennen-Setup',
                    'value': '\n'.join(race_lines)[:1024],
                    'inline': False,
                }
            )

    if url:
        fields.append(
            {
                'name': 'Oeffnen',
                'value': f'[Direkt zur Seite]({url})',
                'inline': False,
            }
        )

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': f"{event_meta['emoji']} {event_meta['headline']}"[:256],
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': db_notification.created_at.replace(microsecond=0).isoformat() + 'Z',
    }

    if url:
        embed['url'] = url

    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    if thumbnail_url:
        embed['thumbnail'] = {'url': thumbnail_url}

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }


def _build_flatout2_round_race_lines(payload: dict[str, Any]) -> list[str]:
    raw_races = payload.get('flatout2_round_races')
    if not isinstance(raw_races, list):
        return []

    lines = []
    for index, race in enumerate(raw_races, start=1):
        if not isinstance(race, dict):
            continue
        mode = str(race.get('mode') or '').strip() or 'single_race'
        track = str(race.get('track') or '').strip()
        vehicle = str(race.get('vehicle') or '').strip()
        if not track or not vehicle:
            continue
        lines.append(
            f'{index}. {get_flatout2_mode_label(mode)} / {track} / {vehicle}'
        )
    return lines


def _build_flatout2_first_race_summary(payload: dict[str, Any]) -> str:
    race_lines = _build_flatout2_round_race_lines(payload)
    if not race_lines:
        return ''

    return f'Erstes Rennen: {race_lines[0][3:]}'


def _build_test_discord_dm_message_payload(
    party_id: PartyID,
) -> dict[str, Any]:
    url = _build_absolute_notification_url(party_id, '/ns-tourneys/')
    brand_icon_url = _build_absolute_notification_url(
        party_id, '/static_sites/netsession/icon-192.png'
    )

    description_lines = [
        '**Counter-Strike 2 (5on5)**',
        'Upper Bracket • Spiel #2 ist jetzt spielbereit.',
        '',
        'So sehen künftige Turnier- und Match-Benachrichtigungen als Karte aus.',
    ]

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': '🧪 Discord-Testnachricht',
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': [
            {
                'name': 'Ereignis',
                'value': 'Match spielbereit',
                'inline': True,
            },
            {
                'name': 'Turnier',
                'value': 'Counter-Strike 2 (5on5)',
                'inline': True,
            },
            {
                'name': 'Spiel',
                'value': 'WB #2',
                'inline': True,
            },
            {
                'name': 'Status',
                'value': 'Discord-DM-Zustellung aktiv',
                'inline': True,
            },
        ],
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    }

    if url:
        embed['url'] = url
        embed['fields'].append(
            {
                'name': 'Oeffnen',
                'value': f'[Turnieruebersicht oeffnen]({url})',
                'inline': False,
            }
        )

    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }


def _build_absolute_notification_url(
    party_id: PartyID, url_path: str
) -> str | None:
    path = (url_path or '').strip()
    if not path:
        return None

    if path.startswith('http://') or path.startswith('https://'):
        return path

    server_name = _find_browser_push_site_server_name(party_id)
    if not server_name:
        return path if path.startswith('/') else f'/{path}'

    normalized_path = path if path.startswith('/') else f'/{path}'
    return f'https://{server_name}{normalized_path}'


def _send_discord_dm(
    *,
    application_id: str,
    bot_token: str,
    discord_user_id: str,
    payload: dict[str, Any],
) -> None:
    if not application_id.strip():
        raise ValueError('Discord Application ID fehlt.')

    headers = {
        'Authorization': f'Bot {bot_token}',
        'Content-Type': 'application/json',
        'User-Agent': f'BYCEPS Netsession/{application_id}',
    }

    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_DM_TIMEOUT_SECONDS,
        headers=headers,
    ) as client:
        dm_response = client.post(
            '/users/@me/channels',
            json={'recipient_id': discord_user_id},
        )
        dm_response.raise_for_status()
        channel_id = str(dm_response.json().get('id') or '').strip()
        if not channel_id:
            raise ValueError('Discord-DM-Kanal konnte nicht erstellt werden.')

        message_response = client.post(
            f'/channels/{channel_id}/messages',
            json=payload,
        )
        message_response.raise_for_status()


def _parse_source_outcome(raw_value: str | None) -> SourceOutcome:
    if not raw_value:
        return SourceOutcome.winner

    try:
        return SourceOutcome(raw_value)
    except ValueError:
        return SourceOutcome.winner


def _validate_team_size_for_registration_mode(
    *,
    registration_mode: RegistrationMode,
    team_size: int | None,
) -> Result[None, str]:
    if team_size is None:
        return Err('Team size is required.')

    if team_size < 1 or team_size > 20:
        return Err('Team size must be between 1 and 20.')

    if registration_mode == RegistrationMode.solo and team_size != 1:
        return Err('Team size must be 1 for solo registration mode.')

    return Ok(None)


def _validate_substitute_count_for_registration_mode(
    *,
    registration_mode: RegistrationMode,
    substitute_count: int | None,
) -> Result[None, str]:
    if substitute_count is None:
        return Err('Substitute count is required.')

    if substitute_count < 0 or substitute_count > 20:
        return Err('Substitute count must be between 0 and 20.')

    if registration_mode == RegistrationMode.solo and substitute_count != 0:
        return Err('Substitute count must be 0 for solo registration mode.')

    return Ok(None)


def _get_max_team_member_count(tournament: Tournament) -> int | None:
    if tournament.team_size is None:
        return None

    return tournament.team_size + (tournament.substitute_count or 0)


def _validate_participant_limit(participant_limit: int | None) -> Result[None, str]:
    if participant_limit is None:
        return Ok(None)

    if participant_limit < 2:
        return Err('Participant limit must be at least 2.')

    return Ok(None)


def _validate_coin_cost(coin_cost: int) -> Result[None, str]:
    if coin_cost < 0:
        return Err('Coin cost must not be negative.')

    return Ok(None)


def _validate_mode_for_registration_mode(
    *,
    mode: TournamentMode,
    registration_mode: RegistrationMode,
) -> Result[None, str]:
    _ = mode
    _ = registration_mode
    return Ok(None)


def _is_stage_type_compatible_with_tournament_mode(
    stage_family: StageFamily,
    tournament_mode: TournamentMode,
) -> bool:
    if tournament_mode == TournamentMode.duel:
        return stage_family == StageFamily.duel

    if tournament_mode == TournamentMode.ffa:
        return stage_family == StageFamily.ffa

    return False


def _is_stage_type_compatible_with_registration_mode(
    stage_type: StageType,
    registration_mode: RegistrationMode,
) -> bool:
    _ = stage_type
    _ = registration_mode
    return True


def _validate_bracket_ready_team_sizes(
    tournament: Tournament, participants: list[Participant]
) -> Result[None, str]:
    if tournament.team_size is None:
        return Ok(None)

    bracket_ready_teams = [
        participant
        for participant in domain_service.select_bracket_ready_participants(
            participants
        )
        if participant.type == ParticipantType.team
    ]
    if not bracket_ready_teams:
        return Ok(None)

    team_members_by_participant_id = get_team_members_for_participants(
        {participant.id for participant in bracket_ready_teams}
    )
    invalid_team_names = [
        participant.name
        for participant in bracket_ready_teams
        if len(team_members_by_participant_id.get(participant.id, []))
        != tournament.team_size
    ]
    if not invalid_team_names:
        return Ok(None)

    shown_names = ', '.join(invalid_team_names[:3])
    if len(invalid_team_names) > 3:
        shown_names += ', ...'

    return Err(
        f'Team size requirement is not met for: {shown_names}. '
        f'Required team size: {tournament.team_size}.'
    )


def _schedule_generated_matches(
    *,
    tournament_starts_at: datetime | None,
    stage: Stage,
    match_ids: list[MatchID],
    round_starts_at_by_round_no: dict[int, datetime] | None = None,
) -> None:
    if not match_ids:
        return

    round_starts_at_overrides = {
        round_no: starts_at
        for round_no, starts_at in (round_starts_at_by_round_no or {}).items()
        if round_no > 0
    }

    match_duration_minutes = _get_stage_setting_int(
        stage.settings, 'match_duration_minutes', minimum=1
    )
    max_matches_per_round = _get_stage_setting_int(
        stage.settings, 'max_matches_per_round', minimum=1
    )
    break_between_rounds_minutes = _get_stage_setting_int(
        stage.settings,
        'break_between_rounds_minutes',
        minimum=0,
        fallback=0,
    )

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter(DbNetsessionTourneyMatch.id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return

    db_matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = defaultdict(
        list
    )
    for db_match in db_matches:
        db_matches_by_round_no[db_match.round_no].append(db_match)

    if (
        tournament_starts_at is None
        and not round_starts_at_overrides
        and match_duration_minutes is None
    ):
        return
    if match_duration_minutes is None and not round_starts_at_overrides:
        return
    if tournament_starts_at is None and not round_starts_at_overrides:
        return

    round_starts_at = tournament_starts_at
    for round_no in sorted(db_matches_by_round_no.keys()):
        db_round_matches = db_matches_by_round_no[round_no]
        round_override_starts_at = round_starts_at_overrides.get(round_no)
        if round_override_starts_at is not None:
            round_starts_at = round_override_starts_at
        if round_starts_at is None:
            continue

        if match_duration_minutes is None:
            if round_override_starts_at is None:
                continue
            for db_match in db_round_matches:
                db_match.scheduled_at = round_starts_at
            continue

        max_concurrent_matches = max_matches_per_round or len(db_round_matches)

        wave_count = 0
        for index, db_match in enumerate(db_round_matches):
            wave_no = index // max_concurrent_matches
            db_match.scheduled_at = round_starts_at + timedelta(
                minutes=wave_no * match_duration_minutes
            )
            wave_count = max(wave_count, wave_no + 1)

        round_starts_at += timedelta(
            minutes=(wave_count * match_duration_minutes)
            + break_between_rounds_minutes
        )


def _build_round_starts_at_schedule(
    *,
    tournament_starts_at: datetime | None,
    stage: Stage,
    round_match_counts: dict[int, int],
) -> dict[int, datetime]:
    if tournament_starts_at is None or not round_match_counts:
        return {}

    match_duration_minutes = _get_stage_setting_int(
        stage.settings, 'match_duration_minutes', minimum=1
    )
    if match_duration_minutes is None:
        return {}

    max_matches_per_round = _get_stage_setting_int(
        stage.settings, 'max_matches_per_round', minimum=1
    )
    break_between_rounds_minutes = _get_stage_setting_int(
        stage.settings,
        'break_between_rounds_minutes',
        minimum=0,
        fallback=0,
    )

    schedule: dict[int, datetime] = {}
    round_starts_at = tournament_starts_at
    for round_no in sorted(round_match_counts.keys()):
        match_count = round_match_counts[round_no]
        if match_count < 1:
            continue

        schedule[round_no] = round_starts_at
        max_concurrent_matches = max_matches_per_round or match_count
        wave_count = (
            (match_count + max_concurrent_matches - 1)
            // max_concurrent_matches
        )
        round_starts_at += timedelta(
            minutes=(wave_count * match_duration_minutes)
            + break_between_rounds_minutes
        )

    return schedule


def _get_stage_setting_int(
    settings: dict[str, Any],
    key: str,
    *,
    minimum: int,
    fallback: int | None = None,
) -> int | None:
    raw_value = settings.get(key, fallback)
    if raw_value is None:
        return None

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return fallback

    if value < minimum:
        return fallback

    return value


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
            return Err('Unknown category.')

        return Ok(db_category.id)

    db_category = _ensure_default_tournament_category_for_party(party_id)
    if db_category is None:
        return Err('Unknown party.')

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


def _find_db_tournament_rule_template(
    rule_template_id: TournamentRuleTemplateID,
) -> DbNetsessionTourneyTournamentRuleTemplate | None:
    return db.session.get(
        DbNetsessionTourneyTournamentRuleTemplate, rule_template_id
    )


def _find_db_tournament_prize(
    prize_id: TournamentPrizeID,
) -> DbNetsessionTourneyTournamentPrize | None:
    return db.session.get(DbNetsessionTourneyTournamentPrize, prize_id)


def _find_db_tournament_for_party(
    party_id: PartyID, tournament_id: TournamentID
) -> DbNetsessionTourneyTournament | None:
    return db.session.scalar(
        select(DbNetsessionTourneyTournament).filter_by(
            id=tournament_id, party_id=party_id
        )
    )


def _is_user_already_active_participant(
    tournament_id: TournamentID, user_id: UserID
) -> bool:
    direct_assignment_exists = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyParticipant.id))
        .filter_by(tournament_id=tournament_id, user_id=user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if direct_assignment_exists:
        return True

    team_membership_exists = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyTeamMember.id))
        .join(
            DbNetsessionTourneyParticipant,
            DbNetsessionTourneyTeamMember.participant_id
            == DbNetsessionTourneyParticipant.id,
        )
        .filter(DbNetsessionTourneyTeamMember.user_id == user_id)
        .filter(DbNetsessionTourneyParticipant.tournament_id == tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    return bool(team_membership_exists)


def _is_tournament_full(
    tournament: Tournament, active_participant_count: int
) -> bool:
    return (
        tournament.participant_limit is not None
        and active_participant_count >= tournament.participant_limit
    )


def _find_db_active_participant_for_user(
    tournament_id: TournamentID, user_id: UserID
) -> DbNetsessionTourneyParticipant | None:
    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id, user_id=user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is not None:
        return db_participant

    return db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .join(
            DbNetsessionTourneyTeamMember,
            DbNetsessionTourneyTeamMember.participant_id
            == DbNetsessionTourneyParticipant.id,
        )
        .filter(DbNetsessionTourneyParticipant.tournament_id == tournament_id)
        .filter(DbNetsessionTourneyTeamMember.user_id == user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )


def _set_registration_state_for_user(
    tournament_id: TournamentID, user_id: UserID, state: RegistrationState
) -> None:
    db_registration = db.session.scalar(
        select(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id, user_id=user_id
        )
    )
    if db_registration is None:
        return

    db_registration.state = state.value


def _ensure_registration_is_registered(
    tournament_id: TournamentID, user_id: UserID
) -> None:
    db_registration = db.session.scalar(
        select(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id,
            user_id=user_id,
        )
    )
    if db_registration is None:
        db.session.add(
            DbNetsessionTourneyRegistration(
                RegistrationID(generate_uuid7()),
                tournament_id,
                user_id,
                RegistrationState.registered,
                datetime.utcnow(),
            )
        )
        return

    db_registration.state = RegistrationState.registered.value


def _validate_user_uses_ticket_for_party(
    user_id: UserID, party_id: PartyID
) -> Result[None, str]:
    if ticket_service.uses_any_ticket_for_party(user_id, party_id):
        return Ok(None)

    return Err(
        'Using a ticket for this party is required to register for tournaments.'
    )


def _find_db_managed_team_participant(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    manager_user_id: UserID,
) -> DbNetsessionTourneyParticipant | None:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return None

    return db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            id=participant_id,
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
            manager_user_id=manager_user_id,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )


def _get_team_member_user_ids_for_participant(
    participant_id: ParticipantID,
) -> list[UserID]:
    return db.session.scalars(
        select(DbNetsessionTourneyTeamMember.user_id).filter_by(
            participant_id=participant_id
        )
    ).all()


def _generate_unique_invite_code_for_tournament(
    tournament_id: TournamentID,
) -> str:
    for _ in range(64):
        # Use strong random bytes instead of UUIDv7 prefix (timestamp-heavy),
        # which can collide frequently for short invite codes.
        invite_code = secrets.token_hex(4)
        existing_participant_id = db.session.scalar(
            select(DbNetsessionTourneyParticipant.id).filter_by(
                tournament_id=tournament_id, invite_code=invite_code
            )
        )
        if existing_participant_id is None:
            return invite_code

    raise RuntimeError(
        'Could not generate unique invite code after 64 attempts.'
    )


def _get_discord_dm_fernet() -> Fernet:
    secret_key = current_app.config['SECRET_KEY']
    if isinstance(secret_key, str):
        raw = secret_key.encode('utf-8')
    else:
        raw = bytes(secret_key)

    key = urlsafe_b64encode(sha256(raw + b'discord-dm').digest())
    return Fernet(key)


def _get_browser_push_fernet() -> Fernet:
    secret_key = current_app.config['SECRET_KEY']
    if isinstance(secret_key, str):
        raw = secret_key.encode('utf-8')
    else:
        raw = bytes(secret_key)

    key = urlsafe_b64encode(sha256(raw + b'browser-push').digest())
    return Fernet(key)

def _get_browser_push_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(
        current_app.config['SECRET_KEY'], salt='netsession_tourney.browser_push'
    )

def _encrypt_discord_dm_bot_token(bot_token: str) -> str:
    token = _get_discord_dm_fernet().encrypt(bot_token.encode('utf-8'))
    return token.decode('ascii')


def _generate_browser_push_private_key_pem() -> str:
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode('ascii')


def _derive_browser_push_public_key(private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode('ascii'), password=None
    )
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return (
        urlsafe_b64encode(public_key_bytes).decode('ascii').rstrip('=')
    )


def _encrypt_browser_push_private_key(private_key_pem: str) -> str:
    token = _get_browser_push_fernet().encrypt(
        private_key_pem.encode('utf-8')
    )
    return token.decode('ascii')


def _decrypt_browser_push_private_key(token: str) -> str | None:
    try:
        decrypted = _get_browser_push_fernet().decrypt(token.encode('ascii'))
        return decrypted.decode('utf-8')
    except (InvalidToken, UnicodeDecodeError):
        try:
            data = _get_browser_push_serializer().loads(token)
        except BadSignature:
            return None

        private_key_pem = data.get('private_key_pem')
        return private_key_pem if isinstance(private_key_pem, str) else None


def _build_browser_push_private_key_for_pywebpush(private_key: str) -> str:
    """Return a pywebpush-compatible VAPID private key string.

    Stored keys are PEM strings. `pywebpush` expects a PEM file path or a
    DER/base64 representation, not PEM contents directly.
    """
    normalized = private_key.strip()
    if 'BEGIN PRIVATE KEY' not in normalized:
        return normalized

    loaded_private_key = serialization.load_pem_private_key(
        normalized.encode('ascii'),
        password=None,
    )
    der = loaded_private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return urlsafe_b64encode(der).decode('ascii').rstrip('=')


def _build_browser_push_vapid_subject(
    party_id: PartyID, endpoint: str | None = None
) -> str:
    site_server_name = _find_browser_push_site_server_name(party_id)
    if site_server_name:
        return f'https://{site_server_name}'

    server_name = str(current_app.config.get('SERVER_NAME') or '').strip()
    if server_name:
        host = server_name.split(':', 1)[0].strip()
        if host and host != 'localhost':
            return f'https://{host}'

    endpoint_host = _get_browser_push_endpoint_host(endpoint)
    if endpoint_host:
        return f'mailto:noreply@{endpoint_host}'

    return 'mailto:noreply@byceps.invalid'


def _find_browser_push_site_server_name(party_id: PartyID) -> str | None:
    primary_party_site_id = party_setting_service.find_setting_value(
        party_id, 'primary_party_site_id'
    )
    if primary_party_site_id:
        site = site_service.find_site(SiteID(primary_party_site_id))
        if site and site.server_name:
            return site.server_name.strip()

    for site in site_service.get_all_sites():
        if (
            site.party_id == party_id
            and site.enabled
            and not site.archived
            and site.server_name
        ):
            return site.server_name.strip()

    return None


def _get_browser_push_endpoint_host(endpoint: str | None) -> str | None:
    if not endpoint:
        return None

    try:
        return httpx.URL(endpoint).host
    except Exception:  # pragma: no cover - defensive fallback
        return None


def _build_browser_push_logo_urls(
    db_tournament: DbNetsessionTourneyTournament,
) -> tuple[str, str | None]:
    fallback_icon_url = _to_browser_push_asset_url(
        '/static_sites/netsession/icon-192.png'
    )
    return fallback_icon_url, None


def _build_browser_push_badge_url() -> str:
    return _to_browser_push_asset_url('/static_sites/netsession/icon-192.png')


def _to_browser_push_asset_url(url_or_path: str) -> str:
    normalized = url_or_path.strip()
    if normalized.startswith(('http://', 'https://')):
        return normalized
    if not normalized.startswith('/'):
        normalized = '/' + normalized
    return normalized


def _build_browser_push_match_label(payload: dict[str, Any]) -> str | None:
    match_id = payload.get('match_id')
    if not isinstance(match_id, str) or not match_id:
        return None

    try:
        parsed_match_id = MatchID(UUID(match_id))
    except ValueError:
        return None

    db_match = db.session.get(DbNetsessionTourneyMatch, parsed_match_id)
    if db_match is None:
        return None

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None:
        return f'M #{db_match.match_no}'

    if db_stage.type in {
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return _build_double_elimination_notification_match_label(
            db_match, db_stage.id
        )

    generic_stage_names = {'match', 'matches'}
    stage_settings = db_stage.settings_json or {}
    builder_display_title = str(stage_settings.get('builder_display_title') or '').strip()
    if builder_display_title:
        return f'{builder_display_title} • M #{db_match.match_no}'

    if db_stage.name:
        stage_name = db_stage.name.strip()
        if stage_name.lower() not in generic_stage_names:
            return f'{stage_name} • M #{db_match.match_no}'

    return f'M #{db_match.match_no}'


def _build_double_elimination_notification_match_label(
    db_match: DbNetsessionTourneyMatch,
    stage_id: StageID,
) -> str:
    db_stage_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(stage_id=stage_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_stage_matches:
        return f'M #{db_match.match_no}'

    stage_match_ids = [db_stage_match.id for db_stage_match in db_stage_matches]
    db_stage_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(stage_match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()

    source_match_id_by_slot_id = {
        db_slot.id: db_slot.match_id for db_slot in db_stage_slots
    }
    incoming_by_match_id: dict[MatchID, list[tuple[MatchID, Any]]] = (
        defaultdict(list)
    )
    for db_slot in db_stage_slots:
        if db_slot.source_match_slot_id is None:
            continue
        source_match_id = source_match_id_by_slot_id.get(
            db_slot.source_match_slot_id
        )
        if source_match_id is None:
            continue
        incoming_by_match_id[db_slot.match_id].append(
            (source_match_id, db_slot.source_outcome)
        )

    labels_by_match_id = _build_double_elimination_notification_match_labels(
        db_stage_matches,
        incoming_by_match_id,
    )
    return labels_by_match_id.get(db_match.id, f'M #{db_match.match_no}')


def _build_double_elimination_notification_match_labels(
    db_stage_matches: list[DbNetsessionTourneyMatch],
    incoming_by_match_id: dict[MatchID, list[tuple[MatchID, Any]]],
) -> dict[MatchID, str]:
    sorted_matches = sorted(
        db_stage_matches,
        key=lambda match: (match.round_no, match.match_no),
    )
    stage_match_ids = {match.id for match in db_stage_matches}
    bracket_by_match_id: dict[MatchID, str] = {}

    changed = True
    while changed:
        changed = False
        for match in sorted_matches:
            incoming = [
                (source_match_id, outcome)
                for source_match_id, outcome in incoming_by_match_id.get(
                    match.id, []
                )
                if source_match_id in stage_match_ids
            ]
            bracket = bracket_by_match_id.get(match.id)
            next_bracket = bracket
            if not incoming:
                next_bracket = 'WB'
            else:
                source_brackets = {
                    bracket_by_match_id.get(source_match_id)
                    for source_match_id, _ in incoming
                }
                source_brackets.discard(None)

                if 'GF' in source_brackets:
                    next_bracket = 'GF'
                elif any(
                    _is_loser_notification_outcome(outcome)
                    for _, outcome in incoming
                ):
                    next_bracket = 'LB'
                elif source_brackets == {'WB'}:
                    next_bracket = 'WB'
                elif source_brackets == {'LB'}:
                    next_bracket = 'LB'
                elif source_brackets == {'WB', 'LB'}:
                    next_bracket = 'GF'

            if next_bracket != bracket:
                bracket_by_match_id[match.id] = next_bracket
                changed = True

    labels_by_match_id = {match.id: f'M #{match.match_no}' for match in db_stage_matches}

    gf_matches = sorted(
        [
            match
            for match in sorted_matches
            if bracket_by_match_id.get(match.id) == 'GF'
        ],
        key=lambda match: (match.round_no, match.match_no),
    )
    if gf_matches:
        if len(gf_matches) == 1:
            labels_by_match_id[gf_matches[0].id] = 'Grand Final'
        elif len(gf_matches) == 2:
            labels_by_match_id[gf_matches[0].id] = 'Grand Final'
            labels_by_match_id[gf_matches[1].id] = 'Double Grand Final'
        else:
            for index, match in enumerate(gf_matches, start=1):
                labels_by_match_id[match.id] = f'Grand Final #{index}'

    wb_matches = [
        match
        for match in sorted_matches
        if bracket_by_match_id.get(match.id) == 'WB'
    ]
    lb_matches = [
        match
        for match in sorted_matches
        if bracket_by_match_id.get(match.id) == 'LB'
    ]

    labels_by_match_id.update(
        _label_notification_bracket_matches(
            wb_matches,
            prefix='WB',
            semi_prefix='WB Semi',
            final_label='WB Final',
        )
    )
    labels_by_match_id.update(
        _label_notification_bracket_matches(
            lb_matches,
            prefix='LB',
            semi_prefix='LB Semi',
            final_label='LB Final',
        )
    )

    return labels_by_match_id


def _is_loser_notification_outcome(outcome: Any) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'


def _label_notification_bracket_matches(
    matches: list[DbNetsessionTourneyMatch],
    *,
    prefix: str,
    semi_prefix: str,
    final_label: str,
) -> dict[MatchID, str]:
    if not matches:
        return {}

    labels_by_match_id: dict[MatchID, str] = {}
    matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = (
        defaultdict(list)
    )
    for match in matches:
        matches_by_round_no[match.round_no].append(match)

    sorted_round_nos = sorted(matches_by_round_no.keys())
    final_round_no = sorted_round_nos[-1]
    final_round_matches = sorted(
        matches_by_round_no[final_round_no],
        key=lambda match: match.match_no,
    )
    for index, match in enumerate(final_round_matches, start=1):
        labels_by_match_id[match.id] = (
            final_label
            if len(final_round_matches) == 1
            else f'{final_label} #{index}'
        )

    semi_round_no = sorted_round_nos[-2] if len(sorted_round_nos) >= 2 else None
    if semi_round_no is not None:
        semi_matches = sorted(
            matches_by_round_no[semi_round_no],
            key=lambda match: match.match_no,
        )
        for index, match in enumerate(semi_matches, start=1):
            labels_by_match_id[match.id] = f'{semi_prefix} #{index}'

    running_no = 1
    for round_no in sorted_round_nos:
        for match in sorted(
            matches_by_round_no[round_no],
            key=lambda current_match: current_match.match_no,
        ):
            if match.id in labels_by_match_id:
                continue
            labels_by_match_id[match.id] = f'{prefix} #{running_no}'
            running_no += 1

    return labels_by_match_id


def _build_site_tournament_overview_path(slug: str) -> str:
    return f'/ns-tourneys/{slug}'


def _build_site_match_path(slug: str, match_id: MatchID | UUID) -> str:
    return f'/ns-tourneys/{slug}/matches/{match_id}'


def _decrypt_discord_dm_bot_token(token: str | None) -> str | None:
    if not token:
        return None

    try:
        decrypted = _get_discord_dm_fernet().decrypt(token.encode('ascii'))
    except (InvalidToken, ValueError):
        return None

    return decrypted.decode('utf-8')


def _mask_discord_dm_bot_token(bot_token: str | None) -> str:
    if not bot_token:
        return ''
    if len(bot_token) < 10:
        return '***'
    return bot_token[:6] + '***' + bot_token[-4:]


def _db_tournament_category_to_model(
    db_category: DbNetsessionTourneyTournamentCategory,
) -> TournamentCategory:
    return TournamentCategory(
        id=db_category.id,
        party_id=db_category.party_id,
        position=db_category.position,
        title=db_category.title,
    )


def _db_tournament_rule_template_to_model(
    db_rule_template: DbNetsessionTourneyTournamentRuleTemplate,
) -> TournamentRuleTemplate:
    return TournamentRuleTemplate(
        id=db_rule_template.id,
        party_id=db_rule_template.party_id,
        slug=db_rule_template.slug,
        title=db_rule_template.title,
        body_format=RuleTemplateBodyFormat(db_rule_template.body_format),
        body=db_rule_template.body,
        created_at=db_rule_template.created_at,
        updated_at=db_rule_template.updated_at,
    )


def _db_tournament_prize_to_model(
    db_prize: DbNetsessionTourneyTournamentPrize,
) -> TournamentPrize:
    return TournamentPrize(
        id=db_prize.id,
        tournament_id=db_prize.tournament_id,
        position=db_prize.position,
        body_format=RuleTemplateBodyFormat(db_prize.body_format),
        body=db_prize.body,
        created_at=db_prize.created_at,
        updated_at=db_prize.updated_at,
    )


def _db_browser_push_config_to_model(
    db_config: DbNetsessionTourneyBrowserPushConfig,
) -> BrowserPushConfig:
    return BrowserPushConfig(
        party_id=db_config.party_id,
        enabled=db_config.enabled,
        vapid_public_key=db_config.vapid_public_key,
        created_at=db_config.created_at,
        updated_at=db_config.updated_at,
    )


def _db_discord_dm_config_to_model(
    db_config: DbNetsessionTourneyDiscordDmConfig,
) -> DiscordDmConfig:
    return DiscordDmConfig(
        party_id=db_config.party_id,
        enabled=db_config.enabled,
        application_id=db_config.application_id,
        default_event_mask=list(db_config.default_event_mask or []),
        created_at=db_config.created_at,
        updated_at=db_config.updated_at,
    )


def _build_default_browser_push_config(
    party_id: PartyID,
) -> BrowserPushConfig:
    now = datetime.utcnow()
    return BrowserPushConfig(
        party_id=party_id,
        enabled=False,
        vapid_public_key=None,
        created_at=now,
        updated_at=now,
    )


def _build_default_discord_dm_config(
    party_id: PartyID,
) -> DiscordDmConfig:
    now = datetime.utcnow()
    return DiscordDmConfig(
        party_id=party_id,
        enabled=False,
        application_id=None,
        default_event_mask=[],
        created_at=now,
        updated_at=now,
    )


def _is_missing_browser_push_table_error(exc: DBAPIError) -> bool:
    sqlstate = getattr(getattr(exc, 'orig', None), 'sqlstate', None)
    if sqlstate != '42P01':
        return False

    statement = str(getattr(exc, 'statement', '') or '')
    return 'netsession_tourney_browser_push_' in statement


def _is_missing_discord_dm_table_error(exc: DBAPIError) -> bool:
    sqlstate = getattr(getattr(exc, 'orig', None), 'sqlstate', None)
    if sqlstate != '42P01':
        return False

    statement = str(getattr(exc, 'statement', '') or '')
    return 'netsession_tourney_discord_dm_' in statement


def _format_browser_push_delivery_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f'{type(exc).__name__}: {message}'
    return type(exc).__name__


def _build_default_coin_settings(party_id: PartyID) -> CoinSettings:
    now = datetime.utcnow()
    return CoinSettings(
        party_id=party_id,
        enabled=False,
        default_coin_amount=0,
        created_at=now,
        updated_at=now,
    )


def _db_coin_settings_to_model(
    db_settings: DbNetsessionTourneyCoinSettings,
) -> CoinSettings:
    return CoinSettings(
        party_id=db_settings.party_id,
        enabled=db_settings.enabled,
        default_coin_amount=db_settings.default_coin_amount,
        created_at=db_settings.created_at,
        updated_at=db_settings.updated_at,
    )


def _db_ticket_category_coin_settings_to_model(
    db_row: DbNetsessionTourneyTicketCategoryCoinSettings,
) -> TicketCategoryCoinSettings:
    return TicketCategoryCoinSettings(
        party_id=db_row.party_id,
        ticket_category_id=db_row.ticket_category_id,
        coin_amount=db_row.coin_amount,
    )


def _db_coin_ledger_entry_to_model(
    db_row: DbNetsessionTourneyCoinLedgerEntry,
) -> CoinLedgerEntry:
    return CoinLedgerEntry(
        id=db_row.id,
        party_id=db_row.party_id,
        user_id=db_row.user_id,
        amount_delta=db_row.amount_delta,
        kind=CoinLedgerEntryKind(db_row.kind),
        reference_type=db_row.reference_type,
        reference_id=db_row.reference_id,
        note=db_row.note,
        created_by_user_id=db_row.created_by_user_id,
        created_at=db_row.created_at,
    )


def _get_ticket_coin_amount_for_user(party_id: PartyID, user_id: UserID) -> int:
    coin_settings = get_coin_settings(party_id)
    tickets = ticket_service.get_tickets_used_by_user(user_id, party_id)
    if not tickets:
        return 0

    amount_by_category_id = {
        item.ticket_category_id: item.coin_amount
        for item in get_ticket_category_coin_settings_for_party(party_id)
    }

    return max(
        amount_by_category_id.get(ticket.category_id, coin_settings.default_coin_amount)
        for ticket in tickets
    )


def _get_manual_coin_adjustment_amount_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    amount = db.session.scalar(
        select(db.func.coalesce(db.func.sum(DbNetsessionTourneyCoinLedgerEntry.amount_delta), 0))
        .filter_by(
            party_id=party_id,
            user_id=user_id,
            kind=CoinLedgerEntryKind.admin_adjustment.value,
        )
    )
    return int(amount or 0)


def _get_registration_coin_delta_amount_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    amount = db.session.scalar(
        select(db.func.coalesce(db.func.sum(DbNetsessionTourneyCoinLedgerEntry.amount_delta), 0))
        .filter_by(party_id=party_id, user_id=user_id)
        .filter(
            DbNetsessionTourneyCoinLedgerEntry.kind.in_(
                [
                    CoinLedgerEntryKind.tournament_registration_charge.value,
                    CoinLedgerEntryKind.tournament_registration_refund.value,
                ]
            )
        )
    )
    return int(amount or 0)


def _append_coin_ledger_entry(
    party_id: PartyID,
    user_id: UserID,
    amount_delta: int,
    kind: CoinLedgerEntryKind,
    created_at: datetime,
    *,
    reference_type: str | None = None,
    reference_id: str | None = None,
    note: str | None = None,
    created_by_user_id: UserID | None = None,
) -> None:
    db.session.add(
        DbNetsessionTourneyCoinLedgerEntry(
            CoinLedgerEntryID(generate_uuid7()),
            party_id,
            user_id,
            amount_delta,
            kind.value,
            created_at,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            created_by_user_id=created_by_user_id,
        )
    )


def _charge_coins_for_tournament_registration(
    party_id: PartyID,
    tournament: Tournament,
    user_id: UserID,
    *,
    created_by_user_id: UserID | None = None,
) -> Result[None, str]:
    coin_settings = get_coin_settings(party_id)
    if not coin_settings.enabled or tournament.coin_cost <= 0:
        return Ok(None)

    balance = get_user_coin_balance(party_id, user_id)
    if balance.available_coins < tournament.coin_cost:
        return Err(
            f'Nicht genügend Coins. Benötigt: {tournament.coin_cost}, verfügbar: {balance.available_coins}.'
        )

    _append_coin_ledger_entry(
        party_id,
        user_id,
        -tournament.coin_cost,
        CoinLedgerEntryKind.tournament_registration_charge,
        datetime.utcnow(),
        reference_type='tournament',
        reference_id=str(tournament.id),
        note=tournament.title,
        created_by_user_id=created_by_user_id,
    )
    return Ok(None)


def _refund_coins_for_tournament_registration_if_available(
    party_id: PartyID,
    tournament: Tournament,
    user_id: UserID,
    *,
    created_by_user_id: UserID | None = None,
) -> None:
    coin_settings = get_coin_settings(party_id)
    if not coin_settings.enabled or tournament.coin_cost <= 0:
        return

    if not is_tournament_coin_refund_available(tournament):
        return

    _append_coin_ledger_entry(
        party_id,
        user_id,
        tournament.coin_cost,
        CoinLedgerEntryKind.tournament_registration_refund,
        datetime.utcnow(),
        reference_type='tournament',
        reference_id=str(tournament.id),
        note=tournament.title,
        created_by_user_id=created_by_user_id,
    )


def _db_tournament_to_model(db_tournament: DbNetsessionTourneyTournament) -> Tournament:
    sponsor_logo_target_url = _find_sponsor_logo_target_url(
        db_tournament.party_id, db_tournament.sponsor_logo_url
    )

    return Tournament(
        id=db_tournament.id,
        party_id=db_tournament.party_id,
        category_id=db_tournament.category_id,
        slug=db_tournament.slug,
        title=db_tournament.title,
        subtitle=db_tournament.subtitle,
        logo_url=db_tournament.logo_url,
        discord_forum_image_url=db_tournament.discord_forum_image_url,
        is_sponsored=db_tournament.is_sponsored,
        sponsor_logo_url=db_tournament.sponsor_logo_url,
        sponsor_logo_target_url=sponsor_logo_target_url,
        game=db_tournament.game,
        mode=TournamentMode(db_tournament.mode),
        status=TournamentStatus(db_tournament.status),
        starts_at=db_tournament.starts_at,
        visible_on_site=db_tournament.visible_on_site,
        registration_open=db_tournament.registration_open,
        rules_page_slug=db_tournament.rules_page_slug,
        registration_mode=RegistrationMode(db_tournament.registration_mode),
        registration_deadline=db_tournament.registration_deadline,
        roster_lock_at=db_tournament.roster_lock_at,
        checkin_open_at=db_tournament.checkin_open_at,
        checkin_close_at=db_tournament.checkin_close_at,
        team_size=db_tournament.team_size,
        substitute_count=db_tournament.substitute_count,
        participant_limit=db_tournament.participant_limit,
        coin_cost=db_tournament.coin_cost,
        coin_refund_policy=CoinRefundPolicy(db_tournament.coin_refund_policy),
        coin_charge_mode=CoinChargeMode(db_tournament.coin_charge_mode),
        discord_enabled=db_tournament.discord_enabled,
        discord_forum_channel_id=db_tournament.discord_forum_channel_id,
        discord_thread_id=db_tournament.discord_thread_id,
        discord_applied_tag_ids=list(db_tournament.discord_applied_tag_ids or []),
        discord_event_mask=list(db_tournament.discord_event_mask or []),
        discord_dm_enabled=db_tournament.discord_dm_enabled,
        discord_dm_event_mask=list(db_tournament.discord_dm_event_mask or []),
    )


def _find_sponsor_logo_target_url(
    party_id: PartyID, sponsor_logo_url: str | None
) -> str | None:
    if not sponsor_logo_url:
        return None

    normalized_sponsor_logo_url = sponsor_logo_url.strip()
    if not normalized_sponsor_logo_url:
        return None

    effective_party_id = party_id
    filename = normalized_sponsor_logo_url.rsplit('/', 1)[-1].strip()
    path_segments = normalized_sponsor_logo_url.split('/')
    try:
        parties_segment_index = path_segments.index('parties')
        effective_party_id = PartyID(path_segments[parties_segment_index + 1])
    except (ValueError, IndexError):
        pass

    if not filename:
        return None

    return db.session.scalar(
        select(DbNetsessionTourneySponsorLogoAsset.target_url).filter_by(
            party_id=effective_party_id,
            filename=filename,
        )
    )


def _db_stage_to_model(db_stage: DbNetsessionTourneyStage) -> Stage:
    return Stage(
        id=db_stage.id,
        tournament_id=db_stage.tournament_id,
        order_no=db_stage.order_no,
        type=StageType(db_stage.type),
        name=db_stage.name,
        settings=dict(db_stage.settings_json or {}),
        status=StageStatus(db_stage.status),
    )


def _db_stage_to_model_with_effective_status(
    db_stage: DbNetsessionTourneyStage, *, tournament_status: str
) -> Stage:
    stage = _db_stage_to_model(db_stage)
    if (
        tournament_status == TournamentStatus.draft.value
        and stage.status == StageStatus.live
    ):
        return replace(stage, status=StageStatus.draft)

    return stage


def _db_participant_to_model(db_participant: DbNetsessionTourneyParticipant) -> Participant:
    return Participant(
        id=db_participant.id,
        tournament_id=db_participant.tournament_id,
        type=ParticipantType(db_participant.type),
        user_id=db_participant.user_id,
        name=db_participant.name,
        logo_url=db_participant.logo_url,
        manager_user_id=db_participant.manager_user_id,
        checkin_state=CheckinState(db_participant.checkin_state),
        seed=db_participant.seed,
        status=ParticipantStatus(db_participant.status),
    )


def _db_team_member_to_model(db_member: DbNetsessionTourneyTeamMember) -> TeamMember:
    return TeamMember(
        id=db_member.id,
        participant_id=db_member.participant_id,
        user_id=db_member.user_id,
        role=TeamMemberRole(db_member.role),
    )


def _db_match_to_model(db_match: DbNetsessionTourneyMatch) -> Match:
    return Match(
        id=db_match.id,
        tournament_id=db_match.tournament_id,
        stage_id=db_match.stage_id,
        round_no=db_match.round_no,
        match_no=db_match.match_no,
        state=MatchState(db_match.state),
        scheduled_at=db_match.scheduled_at,
        reported_by_user_id=db_match.reported_by_user_id,
        confirmed_by_admin_id=db_match.confirmed_by_admin_id,
        lock_version=db_match.lock_version,
        confirmation_deadline_at=db_match.confirmation_deadline_at,
        settings=dict(db_match.settings_json or {}),
    )


def _db_match_to_model_with_effective_state(
    db_match: DbNetsessionTourneyMatch,
    *,
    tournament_status: str,
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
    participant_status_value_by_participant_id: dict[ParticipantID, str],
) -> Match:
    match = _db_match_to_model(db_match)
    if match.state in {MatchState.pending, MatchState.ready}:
        effective_state = _calculate_match_state_for_slots(
            tournament_status=tournament_status,
            db_match_slots=db_match_slots,
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        )
        if effective_state != match.state:
            return replace(match, state=effective_state)

    return match


def _db_match_slot_to_model(db_slot: DbNetsessionTourneyMatchSlot) -> MatchSlot:
    return MatchSlot(
        id=db_slot.id,
        match_id=db_slot.match_id,
        slot_no=db_slot.slot_no,
        participant_id=db_slot.participant_id,
        source_match_slot_id=db_slot.source_match_slot_id,
        source_outcome=_parse_source_outcome(db_slot.source_outcome),
    )


def _db_match_result_to_model(db_result: DbNetsessionTourneyMatchResult) -> MatchResult:
    return MatchResult(
        id=db_result.id,
        match_id=db_result.match_id,
        winner_slot=db_result.winner_slot,
        score=dict(db_result.score_json or {}),
        ranking=dict(db_result.ranking_json or {}),
        submitted_by_user_id=db_result.submitted_by_user_id,
        confirmed_by_user_id=db_result.confirmed_by_user_id,
        confirmed_by_admin_id=db_result.confirmed_by_admin_id,
        confirmation_comment=db_result.confirmation_comment,
    )


def _db_match_chat_message_to_model(
    db_message: DbNetsessionTourneyMatchChatMessage,
) -> MatchChatMessage:
    return MatchChatMessage(
        id=db_message.id,
        tournament_id=db_message.tournament_id,
        match_id=db_message.match_id,
        actor_user_id=db_message.actor_user_id,
        body=db_message.body,
        created_at=db_message.created_at,
    )


def _db_registration_to_model(db_registration: DbNetsessionTourneyRegistration) -> Registration:
    return Registration(
        id=db_registration.id,
        tournament_id=db_registration.tournament_id,
        user_id=db_registration.user_id,
        state=RegistrationState(db_registration.state),
        created_at=db_registration.created_at,
    )
