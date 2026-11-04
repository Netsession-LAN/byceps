"""
byceps.services.netsession_tourney.models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, NewType
from uuid import UUID

from byceps.services.party.models import PartyID
from byceps.services.ticketing.models.ticket import TicketCategoryID
from byceps.services.user.models import UserID


TournamentID = NewType('TournamentID', UUID)
TournamentAdminID = NewType('TournamentAdminID', UUID)
StageID = NewType('StageID', UUID)
ParticipantID = NewType('ParticipantID', UUID)
TeamMemberID = NewType('TeamMemberID', UUID)
MatchID = NewType('MatchID', UUID)
MatchSlotID = NewType('MatchSlotID', UUID)
MatchResultID = NewType('MatchResultID', UUID)
MatchChatMessageID = NewType('MatchChatMessageID', UUID)
RegistrationID = NewType('RegistrationID', UUID)
AuditLogID = NewType('AuditLogID', UUID)
DiscordOutboxID = NewType('DiscordOutboxID', UUID)
DiscordDmSubscriptionID = NewType('DiscordDmSubscriptionID', UUID)
DiscordDmOutboxID = NewType('DiscordDmOutboxID', UUID)
BrowserPushSubscriptionID = NewType('BrowserPushSubscriptionID', UUID)
BrowserPushOutboxID = NewType('BrowserPushOutboxID', UUID)
LogoAssetID = NewType('LogoAssetID', UUID)
TournamentCategoryID = NewType('TournamentCategoryID', UUID)
TournamentRuleTemplateID = NewType('TournamentRuleTemplateID', UUID)
TournamentLogoAssetID = NewType('TournamentLogoAssetID', UUID)
SponsorLogoAssetID = NewType('SponsorLogoAssetID', UUID)
DiscordForumImageAssetID = NewType('DiscordForumImageAssetID', UUID)
TournamentPrizeID = NewType('TournamentPrizeID', UUID)
CoinLedgerEntryID = NewType('CoinLedgerEntryID', UUID)


class TournamentStatus(Enum):
    draft = 'draft'
    live = 'live'
    canceled = 'canceled'
    closed = 'closed'


class TournamentMode(Enum):
    duel = 'duel'
    ffa = 'ffa'


class RuleTemplateBodyFormat(Enum):
    html = 'html'
    markdown = 'markdown'


class RegistrationMode(Enum):
    solo = 'solo'
    team_captain_managed = 'team_captain_managed'
    team_preformed_only = 'team_preformed_only'
    mixed = 'mixed'


class StageStatus(Enum):
    draft = 'draft'
    live = 'live'
    closed = 'closed'


class StageType(Enum):
    single_elimination = 'single_elimination'
    double_elimination = 'double_elimination'
    double_elimination_double_grand_final = (
        'double_elimination_double_grand_final'
    )
    gauntlet = 'gauntlet'
    bracket_groups = 'bracket_groups'
    custom_bracket = 'custom_bracket'
    round_robin_groups = 'round_robin_groups'
    league = 'league'
    swiss = 'swiss'
    ffa_simple = 'ffa_simple'
    ffa_single_elimination = 'ffa_single_elimination'
    ffa_flatout2_single_elimination = 'ffa_flatout2_single_elimination'
    ffa_bracket_groups = 'ffa_bracket_groups'
    ffa_league = 'ffa_league'
    ffa_custom_bracket = 'ffa_custom_bracket'


class StageFamily(Enum):
    duel = 'duel'
    ffa = 'ffa'


class ParticipantType(Enum):
    user = 'user'
    team = 'team'


class CheckinState(Enum):
    pending = 'pending'
    checked_in = 'checked_in'
    missed = 'missed'


class ParticipantStatus(Enum):
    forming = 'forming'
    ready = 'ready'
    checked_in = 'checked_in'
    locked = 'locked'
    dropped = 'dropped'
    eliminated = 'eliminated'


class TeamMemberRole(Enum):
    captain = 'captain'
    player = 'player'
    substitute = 'substitute'


class MatchState(Enum):
    pending = 'pending'
    ready = 'ready'
    in_progress = 'in_progress'
    pending_confirmation = 'pending_confirmation'
    needs_admin_review = 'needs_admin_review'
    completed = 'completed'
    disputed = 'disputed'


class SourceOutcome(Enum):
    winner = 'winner'
    loser = 'loser'


class RegistrationState(Enum):
    registered = 'registered'
    canceled = 'canceled'
    checked_in = 'checked_in'


class CoinRefundPolicy(Enum):
    until_tournament_end = 'until_tournament_end'
    until_end_of_round_1 = 'until_end_of_round_1'


class CoinChargeMode(Enum):
    captain_only = 'captain_only'
    all_members = 'all_members'


class CoinLedgerEntryKind(Enum):
    tournament_registration_charge = 'tournament_registration_charge'
    tournament_registration_refund = 'tournament_registration_refund'
    admin_adjustment = 'admin_adjustment'


class DiscordOutboxStatus(Enum):
    pending = 'pending'
    sent = 'sent'
    failed = 'failed'
    dead_letter = 'dead_letter'


class BrowserPushOutboxStatus(Enum):
    pending = 'pending'
    sent = 'sent'
    failed = 'failed'
    dead_letter = 'dead_letter'


class DiscordDmOutboxStatus(Enum):
    pending = 'pending'
    sent = 'sent'
    failed = 'failed'
    dead_letter = 'dead_letter'


@dataclass(frozen=True, kw_only=True)
class TournamentCategory:
    id: TournamentCategoryID
    party_id: PartyID
    position: int
    title: str


@dataclass(frozen=True, kw_only=True)
class TournamentLogoAsset:
    id: TournamentLogoAssetID
    party_id: PartyID
    filename: str
    label: str
    url_path: str
    uploaded_by_user_id: UserID
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class SponsorLogoAsset:
    id: SponsorLogoAssetID
    party_id: PartyID
    filename: str
    label: str
    url_path: str
    target_url: str | None
    uploaded_by_user_id: UserID
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class DiscordForumImageAsset:
    id: DiscordForumImageAssetID
    party_id: PartyID
    filename: str
    label: str
    url_path: str
    uploaded_by_user_id: UserID
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class TournamentRuleTemplate:
    id: TournamentRuleTemplateID
    party_id: PartyID
    slug: str
    title: str
    body_format: RuleTemplateBodyFormat
    body: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class TournamentPrize:
    id: TournamentPrizeID
    tournament_id: TournamentID
    position: int
    body_format: RuleTemplateBodyFormat
    body: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class BrowserPushConfig:
    party_id: PartyID
    enabled: bool
    vapid_public_key: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class DiscordDmConfig:
    party_id: PartyID
    enabled: bool
    application_id: str | None
    default_event_mask: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class BrowserPushSubscription:
    id: BrowserPushSubscriptionID
    party_id: PartyID
    user_id: UserID
    endpoint: str
    user_agent: str | None
    enabled: bool
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class DiscordDmSubscription:
    id: DiscordDmSubscriptionID
    party_id: PartyID
    user_id: UserID
    enabled: bool
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class CoinSettings:
    party_id: PartyID
    enabled: bool
    default_coin_amount: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class TicketCategoryCoinSettings:
    party_id: PartyID
    ticket_category_id: TicketCategoryID
    coin_amount: int


@dataclass(frozen=True, kw_only=True)
class Tournament:
    id: TournamentID
    party_id: PartyID
    category_id: TournamentCategoryID
    slug: str
    title: str
    subtitle: str | None
    logo_url: str | None
    discord_forum_image_url: str | None
    is_sponsored: bool
    sponsor_logo_url: str | None
    sponsor_logo_target_url: str | None
    game: str | None
    mode: TournamentMode
    status: TournamentStatus
    starts_at: datetime | None
    visible_on_site: bool
    registration_open: bool
    rules_page_slug: str | None
    registration_mode: RegistrationMode
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
    discord_enabled: bool
    discord_forum_channel_id: str | None
    discord_thread_id: str | None
    discord_applied_tag_ids: list[str]
    discord_event_mask: list[str]
    discord_dm_enabled: bool
    discord_dm_event_mask: list[str]


@dataclass(frozen=True, kw_only=True)
class Stage:
    id: StageID
    tournament_id: TournamentID
    order_no: int
    type: StageType
    name: str
    settings: dict[str, Any]
    status: StageStatus


@dataclass(frozen=True, kw_only=True)
class Participant:
    id: ParticipantID
    tournament_id: TournamentID
    type: ParticipantType
    user_id: UserID | None
    name: str
    logo_url: str | None
    manager_user_id: UserID | None
    checkin_state: CheckinState
    seed: int | None
    status: ParticipantStatus


@dataclass(frozen=True, kw_only=True)
class TeamMember:
    id: TeamMemberID
    participant_id: ParticipantID
    user_id: UserID
    role: TeamMemberRole


@dataclass(frozen=True, kw_only=True)
class Match:
    id: MatchID
    tournament_id: TournamentID
    stage_id: StageID
    round_no: int
    match_no: int
    state: MatchState
    scheduled_at: datetime | None
    reported_by_user_id: UserID | None
    confirmed_by_admin_id: UserID | None
    lock_version: int
    confirmation_deadline_at: datetime | None
    settings: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class MatchSlot:
    id: MatchSlotID
    match_id: MatchID
    slot_no: int
    participant_id: ParticipantID | None
    source_match_slot_id: MatchSlotID | None
    source_outcome: SourceOutcome


@dataclass(frozen=True, kw_only=True)
class MatchResult:
    id: MatchResultID
    match_id: MatchID
    winner_slot: int | None
    score: dict[str, Any]
    ranking: dict[str, Any]
    submitted_by_user_id: UserID | None
    confirmed_by_user_id: UserID | None
    confirmed_by_admin_id: UserID | None
    confirmation_comment: str | None


@dataclass(frozen=True, kw_only=True)
class MatchChatMessage:
    id: MatchChatMessageID
    tournament_id: TournamentID
    match_id: MatchID
    actor_user_id: UserID
    body: str
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class Registration:
    id: RegistrationID
    tournament_id: TournamentID
    user_id: UserID
    state: RegistrationState
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class CoinLedgerEntry:
    id: CoinLedgerEntryID
    party_id: PartyID
    user_id: UserID
    amount_delta: int
    kind: CoinLedgerEntryKind
    reference_type: str | None
    reference_id: str | None
    note: str | None
    created_by_user_id: UserID | None
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class UserCoinBalance:
    party_id: PartyID
    user_id: UserID
    ticket_coin_amount: int
    manual_adjustment_amount: int
    registration_delta_amount: int
    available_coins: int


@dataclass(frozen=True, kw_only=True)
class StageTypeSpec:
    type: StageType
    family: StageFamily
    enabled: bool
    beta: bool
    publishable: bool


@dataclass(frozen=True, kw_only=True)
class LogoAsset:
    id: LogoAssetID
    party_id: PartyID
    filename: str
    label: str
    uploaded_by_user_id: UserID
    created_at: datetime
