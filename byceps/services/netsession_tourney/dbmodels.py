"""
byceps.services.netsession_tourney.dbmodels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import Mapped, mapped_column, relationship

from byceps.database import db
from byceps.services.party.dbmodels import DbParty
from byceps.services.party.models import PartyID
from byceps.services.ticketing.dbmodels.category import DbTicketCategory
from byceps.services.ticketing.models.ticket import TicketCategoryID
from byceps.services.user.models import UserID

from .models import (
    AuditLogID,
    BrowserPushOutboxID,
    BrowserPushOutboxStatus,
    BrowserPushSubscriptionID,
    CheckinState,
    CoinChargeMode,
    CoinLedgerEntryID,
    CoinRefundPolicy,
    DiscordDmOutboxID,
    DiscordDmOutboxStatus,
    DiscordDmSubscriptionID,
    DiscordForumImageAssetID,
    DiscordOutboxID,
    DiscordOutboxStatus,
    LogoAssetID,
    MatchID,
    MatchResultID,
    MatchSlotID,
    MatchState,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    RegistrationID,
    RegistrationMode,
    RegistrationState,
    RuleTemplateBodyFormat,
    SourceOutcome,
    SponsorLogoAssetID,
    StageID,
    StageStatus,
    StageType,
    TeamMemberID,
    TeamMemberRole,
    TournamentAdminID,
    TournamentCategoryID,
    TournamentID,
    TournamentLogoAssetID,
    TournamentMode,
    TournamentPrizeID,
    TournamentRuleTemplateID,
    TournamentStatus,
)


class DbNetsessionTourneyLogoAsset(db.Model):
    __tablename__ = 'netsession_tourney_logo_assets'
    __table_args__ = (db.UniqueConstraint('party_id', 'filename'),)

    id: Mapped[LogoAssetID] = mapped_column(db.Uuid, primary_key=True)
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    filename: Mapped[str] = mapped_column(db.UnicodeText)
    label: Mapped[str] = mapped_column(db.UnicodeText)
    uploaded_by_user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    created_at: Mapped[datetime]

    def __init__(
        self,
        logo_asset_id: LogoAssetID,
        party_id: PartyID,
        filename: str,
        label: str,
        uploaded_by_user_id: UserID,
        created_at: datetime,
    ) -> None:
        self.id = logo_asset_id
        self.party_id = party_id
        self.filename = filename
        self.label = label
        self.uploaded_by_user_id = uploaded_by_user_id
        self.created_at = created_at


class DbNetsessionTourneyTournamentLogoAsset(db.Model):
    __tablename__ = 'netsession_tourney_tournament_logo_assets'
    __table_args__ = (db.UniqueConstraint('party_id', 'filename'),)

    id: Mapped[TournamentLogoAssetID] = mapped_column(db.Uuid, primary_key=True)
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    filename: Mapped[str] = mapped_column(db.UnicodeText)
    label: Mapped[str] = mapped_column(db.UnicodeText)
    uploaded_by_user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    created_at: Mapped[datetime]

    def __init__(
        self,
        logo_asset_id: TournamentLogoAssetID,
        party_id: PartyID,
        filename: str,
        label: str,
        uploaded_by_user_id: UserID,
        created_at: datetime,
    ) -> None:
        self.id = logo_asset_id
        self.party_id = party_id
        self.filename = filename
        self.label = label
        self.uploaded_by_user_id = uploaded_by_user_id
        self.created_at = created_at


class DbNetsessionTourneySponsorLogoAsset(db.Model):
    __tablename__ = 'netsession_tourney_sponsor_logo_assets'
    __table_args__ = (db.UniqueConstraint('party_id', 'filename'),)

    id: Mapped[SponsorLogoAssetID] = mapped_column(db.Uuid, primary_key=True)
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    filename: Mapped[str] = mapped_column(db.UnicodeText)
    label: Mapped[str] = mapped_column(db.UnicodeText)
    target_url: Mapped[str | None] = mapped_column(db.UnicodeText)
    uploaded_by_user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    created_at: Mapped[datetime]

    def __init__(
        self,
        logo_asset_id: SponsorLogoAssetID,
        party_id: PartyID,
        filename: str,
        label: str,
        target_url: str | None,
        uploaded_by_user_id: UserID,
        created_at: datetime,
    ) -> None:
        self.id = logo_asset_id
        self.party_id = party_id
        self.filename = filename
        self.label = label
        self.target_url = target_url
        self.uploaded_by_user_id = uploaded_by_user_id
        self.created_at = created_at


class DbNetsessionTourneyDiscordForumImageAsset(db.Model):
    __tablename__ = 'netsession_tourney_discord_forum_image_assets'
    __table_args__ = (db.UniqueConstraint('party_id', 'filename'),)

    id: Mapped[DiscordForumImageAssetID] = mapped_column(
        db.Uuid, primary_key=True
    )
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    filename: Mapped[str] = mapped_column(db.UnicodeText)
    label: Mapped[str] = mapped_column(db.UnicodeText)
    uploaded_by_user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    created_at: Mapped[datetime]

    def __init__(
        self,
        image_asset_id: DiscordForumImageAssetID,
        party_id: PartyID,
        filename: str,
        label: str,
        uploaded_by_user_id: UserID,
        created_at: datetime,
    ) -> None:
        self.id = image_asset_id
        self.party_id = party_id
        self.filename = filename
        self.label = label
        self.uploaded_by_user_id = uploaded_by_user_id
        self.created_at = created_at


class DbNetsessionTourneyTournamentCategory(db.Model):
    __tablename__ = 'netsession_tourney_tournament_categories'
    __table_args__ = (db.UniqueConstraint('party_id', 'title'),)

    id: Mapped[TournamentCategoryID] = mapped_column(db.Uuid, primary_key=True)
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    party: Mapped[DbParty] = relationship(
        backref=db.backref(
            'netsession_tourney_tournament_categories',
            order_by='DbNetsessionTourneyTournamentCategory.position',
            collection_class=ordering_list('position', count_from=1),
        ),
    )
    position: Mapped[int]
    title: Mapped[str] = mapped_column(db.UnicodeText)

    def __init__(
        self,
        category_id: TournamentCategoryID,
        party_id: PartyID,
        title: str,
    ) -> None:
        self.id = category_id
        self.party_id = party_id
        self.title = title


class DbNetsessionTourneyCoinSettings(db.Model):
    __tablename__ = 'netsession_tourney_coin_settings'

    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(default=False)
    default_coin_amount: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        party_id: PartyID,
        created_at: datetime,
        *,
        enabled: bool = False,
        default_coin_amount: int = 0,
    ) -> None:
        self.party_id = party_id
        self.enabled = enabled
        self.default_coin_amount = default_coin_amount
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyTicketCategoryCoinSettings(db.Model):
    __tablename__ = 'netsession_tourney_ticket_category_coin_settings'

    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), primary_key=True
    )
    ticket_category_id: Mapped[TicketCategoryID] = mapped_column(
        db.Uuid,
        db.ForeignKey('ticket_categories.id'),
        primary_key=True,
    )
    ticket_category: Mapped[DbTicketCategory] = relationship()
    coin_amount: Mapped[int]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        party_id: PartyID,
        ticket_category_id: TicketCategoryID,
        coin_amount: int,
        created_at: datetime,
    ) -> None:
        self.party_id = party_id
        self.ticket_category_id = ticket_category_id
        self.coin_amount = coin_amount
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyTournamentRuleTemplate(db.Model):
    __tablename__ = 'netsession_tourney_tournament_rule_templates'
    __table_args__ = (db.UniqueConstraint('party_id', 'slug'),)

    id: Mapped[TournamentRuleTemplateID] = mapped_column(
        db.Uuid, primary_key=True
    )
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    slug: Mapped[str] = mapped_column(db.UnicodeText)
    title: Mapped[str] = mapped_column(db.UnicodeText)
    body_format: Mapped[str] = mapped_column(db.UnicodeText)
    body: Mapped[str] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        rule_template_id: TournamentRuleTemplateID,
        party_id: PartyID,
        slug: str,
        title: str,
        body_format: RuleTemplateBodyFormat,
        body: str,
        created_at: datetime,
    ) -> None:
        self.id = rule_template_id
        self.party_id = party_id
        self.slug = slug
        self.title = title
        self.body_format = body_format.value
        self.body = body
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyTournamentPrize(db.Model):
    __tablename__ = 'netsession_tourney_tournament_prizes'
    __table_args__ = (db.UniqueConstraint('tournament_id', 'position'),)

    id: Mapped[TournamentPrizeID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id', ondelete='CASCADE'),
        index=True,
    )
    position: Mapped[int]
    body_format: Mapped[str] = mapped_column(db.UnicodeText)
    body: Mapped[str] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        prize_id: TournamentPrizeID,
        tournament_id: TournamentID,
        position: int,
        body_format: RuleTemplateBodyFormat,
        body: str,
        created_at: datetime,
    ) -> None:
        self.id = prize_id
        self.tournament_id = tournament_id
        self.position = position
        self.body_format = body_format.value
        self.body = body
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyTournament(db.Model):
    __tablename__ = 'netsession_tourney_tournaments'
    __table_args__ = (db.UniqueConstraint('party_id', 'slug'),)

    id: Mapped[TournamentID] = mapped_column(db.Uuid, primary_key=True)
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    category_id: Mapped[TournamentCategoryID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournament_categories.id'),
        index=True,
        nullable=False,
    )
    category: Mapped[DbNetsessionTourneyTournamentCategory] = relationship()
    slug: Mapped[str] = mapped_column(db.UnicodeText)
    title: Mapped[str] = mapped_column(db.UnicodeText)
    subtitle: Mapped[str | None] = mapped_column(db.UnicodeText)
    logo_url: Mapped[str | None] = mapped_column(db.UnicodeText)
    discord_forum_image_url: Mapped[str | None] = mapped_column(db.UnicodeText)
    is_sponsored: Mapped[bool]
    sponsor_logo_url: Mapped[str | None] = mapped_column(db.UnicodeText)
    game: Mapped[str | None] = mapped_column(db.UnicodeText)
    mode: Mapped[str] = mapped_column(db.UnicodeText)
    status: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    starts_at: Mapped[datetime | None]
    visible_on_site: Mapped[bool]
    registration_open: Mapped[bool]
    rules_page_slug: Mapped[str | None] = mapped_column(db.UnicodeText)
    registration_mode: Mapped[str] = mapped_column(db.UnicodeText)
    registration_deadline: Mapped[datetime | None]
    roster_lock_at: Mapped[datetime | None]
    checkin_open_at: Mapped[datetime | None]
    checkin_close_at: Mapped[datetime | None]
    team_size: Mapped[int | None]
    substitute_count: Mapped[int | None]
    participant_limit: Mapped[int | None]
    coin_cost: Mapped[int] = mapped_column(default=0)
    coin_refund_policy: Mapped[str] = mapped_column(db.UnicodeText)
    coin_charge_mode: Mapped[str] = mapped_column(db.UnicodeText)
    discord_enabled: Mapped[bool]
    discord_forum_channel_id: Mapped[str | None] = mapped_column(db.UnicodeText)
    discord_thread_id: Mapped[str | None] = mapped_column(db.UnicodeText)
    discord_applied_tag_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(db.JSONB), default=list
    )
    discord_event_mask: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(db.JSONB), default=list
    )
    discord_dm_enabled: Mapped[bool]
    discord_dm_event_mask: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(db.JSONB), default=list
    )
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        tournament_id: TournamentID,
        party_id: PartyID,
        category_id: TournamentCategoryID,
        slug: str,
        title: str,
        mode: TournamentMode,
        status: TournamentStatus,
        registration_mode: RegistrationMode,
        created_at: datetime,
        *,
        subtitle: str | None = None,
        logo_url: str | None = None,
        is_sponsored: bool = False,
        sponsor_logo_url: str | None = None,
        game: str | None = None,
        starts_at: datetime | None = None,
        visible_on_site: bool = True,
        registration_open: bool = False,
        rules_page_slug: str | None = None,
        registration_deadline: datetime | None = None,
        roster_lock_at: datetime | None = None,
        checkin_open_at: datetime | None = None,
        checkin_close_at: datetime | None = None,
        team_size: int | None = None,
        substitute_count: int | None = None,
        participant_limit: int | None = None,
        coin_cost: int = 0,
        coin_refund_policy: CoinRefundPolicy = (
            CoinRefundPolicy.until_tournament_end
        ),
        coin_charge_mode: CoinChargeMode = CoinChargeMode.captain_only,
    ) -> None:
        self.id = tournament_id
        self.party_id = party_id
        self.category_id = category_id
        self.slug = slug
        self.title = title
        self.subtitle = subtitle
        self.logo_url = logo_url
        self.discord_forum_image_url = None
        self.is_sponsored = is_sponsored
        self.sponsor_logo_url = sponsor_logo_url
        self.game = game
        self.mode = mode.value
        self.status = status.value
        self.starts_at = starts_at
        self.visible_on_site = visible_on_site
        self.registration_open = registration_open
        self.rules_page_slug = rules_page_slug
        self.registration_mode = registration_mode.value
        self.registration_deadline = registration_deadline
        self.roster_lock_at = roster_lock_at
        self.checkin_open_at = checkin_open_at
        self.checkin_close_at = checkin_close_at
        self.team_size = team_size
        self.substitute_count = substitute_count
        self.participant_limit = participant_limit
        self.coin_cost = coin_cost
        self.coin_refund_policy = coin_refund_policy.value
        self.coin_charge_mode = coin_charge_mode.value
        self.discord_enabled = False
        self.discord_forum_channel_id = None
        self.discord_thread_id = None
        self.discord_applied_tag_ids = []
        self.discord_event_mask = []
        self.discord_dm_enabled = False
        self.discord_dm_event_mask = []
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyTournamentAdmin(db.Model):
    __tablename__ = 'netsession_tourney_tournament_admins'
    __table_args__ = (db.UniqueConstraint('tournament_id', 'user_id'),)

    id: Mapped[TournamentAdminID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id', ondelete='CASCADE'),
        index=True,
    )
    user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    created_at: Mapped[datetime]

    def __init__(
        self,
        tournament_admin_id: TournamentAdminID,
        tournament_id: TournamentID,
        user_id: UserID,
        created_at: datetime,
    ) -> None:
        self.id = tournament_admin_id
        self.tournament_id = tournament_id
        self.user_id = user_id
        self.created_at = created_at


class DbNetsessionTourneyStage(db.Model):
    __tablename__ = 'netsession_tourney_stages'
    __table_args__ = (db.UniqueConstraint('tournament_id', 'order_no'),)

    id: Mapped[StageID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id'),
        index=True,
    )
    order_no: Mapped[int]
    type: Mapped[str] = mapped_column(db.UnicodeText)
    name: Mapped[str] = mapped_column(db.UnicodeText)
    settings_json: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(db.JSONB), default=dict
    )
    status: Mapped[str] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]

    def __init__(
        self,
        stage_id: StageID,
        tournament_id: TournamentID,
        order_no: int,
        type_: StageType,
        name: str,
        created_at: datetime,
        *,
        settings_json: dict[str, Any] | None = None,
        status: StageStatus = StageStatus.draft,
    ) -> None:
        self.id = stage_id
        self.tournament_id = tournament_id
        self.order_no = order_no
        self.type = type_.value
        self.name = name
        self.settings_json = settings_json or {}
        self.status = status.value
        self.created_at = created_at


class DbNetsessionTourneyParticipant(db.Model):
    __tablename__ = 'netsession_tourney_participants'
    __table_args__ = (
        db.UniqueConstraint('tournament_id', 'invite_code'),
        db.Index(
            'netsession_tourney_participants_tournament_user_idx',
            'tournament_id',
            'user_id',
        ),
    )

    id: Mapped[ParticipantID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id'),
        index=True,
    )
    type: Mapped[str] = mapped_column(db.UnicodeText)
    user_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    name: Mapped[str] = mapped_column(db.UnicodeText)
    logo_url: Mapped[str | None] = mapped_column(db.UnicodeText)
    manager_user_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    checkin_state: Mapped[str] = mapped_column(db.UnicodeText)
    seed: Mapped[int | None]
    status: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    invite_code: Mapped[str | None] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]

    def __init__(
        self,
        participant_id: ParticipantID,
        tournament_id: TournamentID,
        type_: ParticipantType,
        name: str,
        created_at: datetime,
        *,
        user_id: UserID | None = None,
        logo_url: str | None = None,
        manager_user_id: UserID | None = None,
        checkin_state: CheckinState = CheckinState.pending,
        seed: int | None = None,
        status: ParticipantStatus = ParticipantStatus.forming,
        invite_code: str | None = None,
    ) -> None:
        self.id = participant_id
        self.tournament_id = tournament_id
        self.type = type_.value
        self.user_id = user_id
        self.name = name
        self.logo_url = logo_url
        self.manager_user_id = manager_user_id
        self.checkin_state = checkin_state.value
        self.seed = seed
        self.status = status.value
        self.invite_code = invite_code
        self.created_at = created_at


class DbNetsessionTourneyTeamMember(db.Model):
    __tablename__ = 'netsession_tourney_team_members'
    __table_args__ = (db.UniqueConstraint('participant_id', 'user_id'),)

    id: Mapped[TeamMemberID] = mapped_column(db.Uuid, primary_key=True)
    participant_id: Mapped[ParticipantID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_participants.id'),
        index=True,
    )
    user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    role: Mapped[str] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]

    def __init__(
        self,
        member_id: TeamMemberID,
        participant_id: ParticipantID,
        user_id: UserID,
        role: TeamMemberRole,
        created_at: datetime,
    ) -> None:
        self.id = member_id
        self.participant_id = participant_id
        self.user_id = user_id
        self.role = role.value
        self.created_at = created_at


class DbNetsessionTourneyMatch(db.Model):
    __tablename__ = 'netsession_tourney_matches'
    __table_args__ = (db.UniqueConstraint('stage_id', 'round_no', 'match_no'),)

    id: Mapped[MatchID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id'),
        index=True,
    )
    stage_id: Mapped[StageID] = mapped_column(
        db.Uuid, db.ForeignKey('netsession_tourney_stages.id'), index=True
    )
    round_no: Mapped[int]
    match_no: Mapped[int]
    state: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    scheduled_at: Mapped[datetime | None]
    reported_by_user_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    confirmed_by_admin_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    lock_version: Mapped[int] = mapped_column(default=0)
    confirmation_deadline_at: Mapped[datetime | None]
    settings_json: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(db.JSONB), default=dict
    )
    dispute_reason_code: Mapped[str | None] = mapped_column(db.UnicodeText)
    dispute_comment: Mapped[str | None] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        match_id: MatchID,
        tournament_id: TournamentID,
        stage_id: StageID,
        round_no: int,
        match_no: int,
        created_at: datetime,
        *,
        state: MatchState = MatchState.pending,
        scheduled_at: datetime | None = None,
        settings_json: dict[str, Any] | None = None,
    ) -> None:
        self.id = match_id
        self.tournament_id = tournament_id
        self.stage_id = stage_id
        self.round_no = round_no
        self.match_no = match_no
        self.state = state.value
        self.scheduled_at = scheduled_at
        self.reported_by_user_id = None
        self.confirmed_by_admin_id = None
        self.lock_version = 0
        self.confirmation_deadline_at = None
        self.settings_json = settings_json or {}
        self.dispute_reason_code = None
        self.dispute_comment = None
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyMatchSlot(db.Model):
    __tablename__ = 'netsession_tourney_match_slots'
    __table_args__ = (db.UniqueConstraint('match_id', 'slot_no'),)

    id: Mapped[MatchSlotID] = mapped_column(db.Uuid, primary_key=True)
    match_id: Mapped[MatchID] = mapped_column(
        db.Uuid, db.ForeignKey('netsession_tourney_matches.id'), index=True
    )
    slot_no: Mapped[int]
    participant_id: Mapped[ParticipantID | None] = mapped_column(
        db.Uuid, db.ForeignKey('netsession_tourney_participants.id')
    )
    source_match_slot_id: Mapped[MatchSlotID | None] = mapped_column(
        db.Uuid, db.ForeignKey('netsession_tourney_match_slots.id')
    )
    source_outcome: Mapped[str] = mapped_column(
        db.UnicodeText, default=SourceOutcome.winner.value
    )

    def __init__(
        self,
        slot_id: MatchSlotID,
        match_id: MatchID,
        slot_no: int,
        *,
        participant_id: ParticipantID | None = None,
        source_match_slot_id: MatchSlotID | None = None,
        source_outcome: SourceOutcome = SourceOutcome.winner,
    ) -> None:
        self.id = slot_id
        self.match_id = match_id
        self.slot_no = slot_no
        self.participant_id = participant_id
        self.source_match_slot_id = source_match_slot_id
        self.source_outcome = source_outcome.value


class DbNetsessionTourneyMatchResult(db.Model):
    __tablename__ = 'netsession_tourney_match_results'

    id: Mapped[MatchResultID] = mapped_column(db.Uuid, primary_key=True)
    match_id: Mapped[MatchID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_matches.id'),
        unique=True,
        index=True,
    )
    winner_slot: Mapped[int | None]
    score_json: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(db.JSONB), default=dict
    )
    ranking_json: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(db.JSONB), default=dict
    )
    submitted_by_user_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    confirmed_by_user_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    confirmed_by_admin_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    confirmation_comment: Mapped[str | None] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        result_id: MatchResultID,
        match_id: MatchID,
        created_at: datetime,
        *,
        winner_slot: int | None = None,
        score_json: dict[str, Any] | None = None,
        ranking_json: dict[str, Any] | None = None,
        submitted_by_user_id: UserID | None = None,
    ) -> None:
        self.id = result_id
        self.match_id = match_id
        self.winner_slot = winner_slot
        self.score_json = score_json or {}
        self.ranking_json = ranking_json or {}
        self.submitted_by_user_id = submitted_by_user_id
        self.confirmed_by_user_id = None
        self.confirmed_by_admin_id = None
        self.confirmation_comment = None
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyMatchChatMessage(db.Model):
    __tablename__ = 'netsession_tourney_match_chat_messages'

    id: Mapped[UUID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id'),
        index=True,
    )
    match_id: Mapped[MatchID] = mapped_column(
        db.Uuid, db.ForeignKey('netsession_tourney_matches.id'), index=True
    )
    actor_user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    body: Mapped[str] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]

    def __init__(
        self,
        message_id: UUID,
        tournament_id: TournamentID,
        match_id: MatchID,
        actor_user_id: UserID,
        body: str,
        created_at: datetime,
    ) -> None:
        self.id = message_id
        self.tournament_id = tournament_id
        self.match_id = match_id
        self.actor_user_id = actor_user_id
        self.body = body
        self.created_at = created_at


class DbNetsessionTourneyResultReportReceipt(db.Model):
    __tablename__ = 'netsession_tourney_result_report_receipts'
    __table_args__ = (db.UniqueConstraint('match_id', 'idempotency_key'),)

    id: Mapped[UUID] = mapped_column(db.Uuid, primary_key=True)
    match_id: Mapped[MatchID] = mapped_column(
        db.Uuid, db.ForeignKey('netsession_tourney_matches.id'), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(db.UnicodeText)
    result_id: Mapped[MatchResultID] = mapped_column(
        db.Uuid, db.ForeignKey('netsession_tourney_match_results.id')
    )
    created_at: Mapped[datetime]

    def __init__(
        self,
        receipt_id: UUID,
        match_id: MatchID,
        idempotency_key: str,
        result_id: MatchResultID,
        created_at: datetime,
    ) -> None:
        self.id = receipt_id
        self.match_id = match_id
        self.idempotency_key = idempotency_key
        self.result_id = result_id
        self.created_at = created_at


class DbNetsessionTourneyRegistration(db.Model):
    __tablename__ = 'netsession_tourney_registrations'
    __table_args__ = (db.UniqueConstraint('tournament_id', 'user_id'),)

    id: Mapped[RegistrationID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id'),
        index=True,
    )
    user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    state: Mapped[str] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]

    def __init__(
        self,
        registration_id: RegistrationID,
        tournament_id: TournamentID,
        user_id: UserID,
        state: RegistrationState,
        created_at: datetime,
    ) -> None:
        self.id = registration_id
        self.tournament_id = tournament_id
        self.user_id = user_id
        self.state = state.value
        self.created_at = created_at


class DbNetsessionTourneyCoinLedgerEntry(db.Model):
    __tablename__ = 'netsession_tourney_coin_ledger'

    id: Mapped[CoinLedgerEntryID] = mapped_column(db.Uuid, primary_key=True)
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    amount_delta: Mapped[int]
    kind: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    reference_type: Mapped[str | None] = mapped_column(db.UnicodeText)
    reference_id: Mapped[str | None] = mapped_column(db.UnicodeText)
    note: Mapped[str | None] = mapped_column(db.UnicodeText)
    created_by_user_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    created_at: Mapped[datetime]

    def __init__(
        self,
        entry_id: CoinLedgerEntryID,
        party_id: PartyID,
        user_id: UserID,
        amount_delta: int,
        kind: str,
        created_at: datetime,
        *,
        reference_type: str | None = None,
        reference_id: str | None = None,
        note: str | None = None,
        created_by_user_id: UserID | None = None,
    ) -> None:
        self.id = entry_id
        self.party_id = party_id
        self.user_id = user_id
        self.amount_delta = amount_delta
        self.kind = kind
        self.reference_type = reference_type
        self.reference_id = reference_id
        self.note = note
        self.created_by_user_id = created_by_user_id
        self.created_at = created_at


class DbNetsessionTourneyAuditLog(db.Model):
    __tablename__ = 'netsession_tourney_audit_log'

    id: Mapped[AuditLogID] = mapped_column(db.Uuid, primary_key=True)
    actor_user_id: Mapped[UserID | None] = mapped_column(
        db.Uuid, db.ForeignKey('users.id')
    )
    object_type: Mapped[str] = mapped_column(db.UnicodeText)
    object_id: Mapped[UUID] = mapped_column(db.Uuid, index=True)
    action: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(db.JSONB), default=dict
    )
    created_at: Mapped[datetime]

    def __init__(
        self,
        log_id: AuditLogID,
        object_type: str,
        object_id: UUID,
        action: str,
        created_at: datetime,
        *,
        actor_user_id: UserID | None = None,
        payload_json: dict[str, Any] | None = None,
    ) -> None:
        self.id = log_id
        self.actor_user_id = actor_user_id
        self.object_type = object_type
        self.object_id = object_id
        self.action = action
        self.payload_json = payload_json or {}
        self.created_at = created_at


class DbNetsessionTourneyNotification(db.Model):
    __tablename__ = 'netsession_tourney_notifications'

    id: Mapped[UUID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id'),
        index=True,
    )
    user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    kind: Mapped[str] = mapped_column(db.UnicodeText)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(db.JSONB), default=dict
    )
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime]

    def __init__(
        self,
        notification_id: UUID,
        tournament_id: TournamentID,
        user_id: UserID,
        kind: str,
        payload_json: dict[str, Any],
        created_at: datetime,
    ) -> None:
        self.id = notification_id
        self.tournament_id = tournament_id
        self.user_id = user_id
        self.kind = kind
        self.payload_json = payload_json
        self.read_at = None
        self.created_at = created_at


class DbNetsessionTourneyDiscordDmConfig(db.Model):
    __tablename__ = 'netsession_tourney_discord_dm_config'

    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), primary_key=True
    )
    enabled: Mapped[bool]
    application_id: Mapped[str | None] = mapped_column(db.UnicodeText)
    bot_token_encrypted: Mapped[str | None] = mapped_column(db.UnicodeText)
    default_event_mask: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(db.JSONB), default=list
    )
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        party_id: PartyID,
        created_at: datetime,
        *,
        enabled: bool = False,
        application_id: str | None = None,
        bot_token_encrypted: str | None = None,
        default_event_mask: list[str] | None = None,
    ) -> None:
        self.party_id = party_id
        self.enabled = enabled
        self.application_id = application_id
        self.bot_token_encrypted = bot_token_encrypted
        self.default_event_mask = list(default_event_mask or [])
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyBrowserPushConfig(db.Model):
    __tablename__ = 'netsession_tourney_browser_push_config'

    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), primary_key=True
    )
    enabled: Mapped[bool]
    vapid_public_key: Mapped[str | None] = mapped_column(db.UnicodeText)
    vapid_private_key_encrypted: Mapped[str | None] = mapped_column(
        db.UnicodeText
    )
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        party_id: PartyID,
        created_at: datetime,
        *,
        enabled: bool = False,
        vapid_public_key: str | None = None,
        vapid_private_key_encrypted: str | None = None,
    ) -> None:
        self.party_id = party_id
        self.enabled = enabled
        self.vapid_public_key = vapid_public_key
        self.vapid_private_key_encrypted = vapid_private_key_encrypted
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyBrowserPushSubscription(db.Model):
    __tablename__ = 'netsession_tourney_browser_push_subscriptions'
    __table_args__ = (db.UniqueConstraint('party_id', 'endpoint'),)

    id: Mapped[BrowserPushSubscriptionID] = mapped_column(
        db.Uuid, primary_key=True
    )
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    endpoint: Mapped[str] = mapped_column(db.UnicodeText)
    endpoint_p256dh: Mapped[str] = mapped_column(db.UnicodeText)
    endpoint_auth: Mapped[str] = mapped_column(db.UnicodeText)
    user_agent: Mapped[str | None] = mapped_column(db.UnicodeText)
    enabled: Mapped[bool]
    last_seen_at: Mapped[datetime]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        subscription_id: BrowserPushSubscriptionID,
        party_id: PartyID,
        user_id: UserID,
        endpoint: str,
        endpoint_p256dh: str,
        endpoint_auth: str,
        created_at: datetime,
        *,
        user_agent: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.id = subscription_id
        self.party_id = party_id
        self.user_id = user_id
        self.endpoint = endpoint
        self.endpoint_p256dh = endpoint_p256dh
        self.endpoint_auth = endpoint_auth
        self.user_agent = user_agent
        self.enabled = enabled
        self.last_seen_at = created_at
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyDiscordDmSubscription(db.Model):
    __tablename__ = 'netsession_tourney_discord_dm_subscriptions'
    __table_args__ = (db.UniqueConstraint('party_id', 'user_id'),)

    id: Mapped[DiscordDmSubscriptionID] = mapped_column(
        db.Uuid, primary_key=True
    )
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    enabled: Mapped[bool]
    last_seen_at: Mapped[datetime]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        subscription_id: DiscordDmSubscriptionID,
        party_id: PartyID,
        user_id: UserID,
        created_at: datetime,
        *,
        enabled: bool = True,
    ) -> None:
        self.id = subscription_id
        self.party_id = party_id
        self.user_id = user_id
        self.enabled = enabled
        self.last_seen_at = created_at
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyBrowserPushOutbox(db.Model):
    __tablename__ = 'netsession_tourney_browser_push_outbox'
    __table_args__ = (db.UniqueConstraint('notification_id'),)

    id: Mapped[BrowserPushOutboxID] = mapped_column(db.Uuid, primary_key=True)
    notification_id: Mapped[UUID] = mapped_column(
        db.Uuid,
        db.ForeignKey(
            'netsession_tourney_notifications.id', ondelete='CASCADE'
        ),
        index=True,
    )
    status: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    attempt_count: Mapped[int]
    next_attempt_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        outbox_id: BrowserPushOutboxID,
        notification_id: UUID,
        created_at: datetime,
    ) -> None:
        self.id = outbox_id
        self.notification_id = notification_id
        self.status = BrowserPushOutboxStatus.pending.value
        self.attempt_count = 0
        self.next_attempt_at = None
        self.last_error = None
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyDiscordDmOutbox(db.Model):
    __tablename__ = 'netsession_tourney_discord_dm_outbox'
    __table_args__ = (db.UniqueConstraint('notification_id'),)

    id: Mapped[DiscordDmOutboxID] = mapped_column(db.Uuid, primary_key=True)
    notification_id: Mapped[UUID] = mapped_column(
        db.Uuid,
        db.ForeignKey(
            'netsession_tourney_notifications.id', ondelete='CASCADE'
        ),
        index=True,
    )
    status: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    attempt_count: Mapped[int]
    next_attempt_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        outbox_id: DiscordDmOutboxID,
        notification_id: UUID,
        created_at: datetime,
    ) -> None:
        self.id = outbox_id
        self.notification_id = notification_id
        self.status = DiscordDmOutboxStatus.pending.value
        self.attempt_count = 0
        self.next_attempt_at = None
        self.last_error = None
        self.created_at = created_at
        self.updated_at = created_at


class DbNetsessionTourneyApiRequestMetric(db.Model):
    __tablename__ = 'netsession_tourney_api_request_metrics'

    id: Mapped[UUID] = mapped_column(db.Uuid, primary_key=True)
    party_id: Mapped[PartyID | None] = mapped_column(db.UnicodeText, index=True)
    endpoint: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    method: Mapped[str] = mapped_column(db.UnicodeText)
    status_code: Mapped[int]
    duration_ms: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(index=True)

    def __init__(
        self,
        metric_id: UUID,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: int,
        created_at: datetime,
        *,
        party_id: PartyID | None = None,
    ) -> None:
        self.id = metric_id
        self.party_id = party_id
        self.endpoint = endpoint
        self.method = method
        self.status_code = status_code
        self.duration_ms = duration_ms
        self.created_at = created_at


class DbNetsessionTourneyDiscordOutbox(db.Model):
    __tablename__ = 'netsession_tourney_discord_outbox'

    id: Mapped[DiscordOutboxID] = mapped_column(db.Uuid, primary_key=True)
    tournament_id: Mapped[TournamentID] = mapped_column(
        db.Uuid,
        db.ForeignKey('netsession_tourney_tournaments.id'),
        index=True,
    )
    event_name: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(db.JSONB), default=dict
    )
    status: Mapped[str] = mapped_column(db.UnicodeText, index=True)
    attempt_count: Mapped[int]
    next_attempt_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(db.UnicodeText)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    def __init__(
        self,
        outbox_id: DiscordOutboxID,
        tournament_id: TournamentID,
        event_name: str,
        payload_json: dict[str, Any],
        created_at: datetime,
    ) -> None:
        self.id = outbox_id
        self.tournament_id = tournament_id
        self.event_name = event_name
        self.payload_json = payload_json
        self.status = DiscordOutboxStatus.pending.value
        self.attempt_count = 0
        self.next_attempt_at = None
        self.last_error = None
        self.created_at = created_at
        self.updated_at = created_at
