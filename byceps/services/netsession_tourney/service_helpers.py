"""
byceps.services.netsession_tourney.service_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Helpers shared by the tournament service modules: conversion of database
objects to models and the audit log.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyAuditLog,
    DbNetsessionTourneyBrowserPushConfig,
    DbNetsessionTourneyCoinLedgerEntry,
    DbNetsessionTourneyCoinSettings,
    DbNetsessionTourneyDiscordDmConfig,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchChatMessage,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyRegistration,
    DbNetsessionTourneySponsorLogoAsset,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTeamMember,
    DbNetsessionTourneyTicketCategoryCoinSettings,
    DbNetsessionTourneyTournament,
    DbNetsessionTourneyTournamentCategory,
    DbNetsessionTourneyTournamentPrize,
    DbNetsessionTourneyTournamentRuleTemplate,
)
from .models import (
    AuditLogID,
    BrowserPushConfig,
    CheckinState,
    CoinChargeMode,
    CoinLedgerEntry,
    CoinLedgerEntryKind,
    CoinRefundPolicy,
    CoinSettings,
    DiscordDmConfig,
    Match,
    MatchChatMessage,
    MatchResult,
    MatchSlot,
    MatchState,
    Participant,
    ParticipantStatus,
    ParticipantType,
    Registration,
    RegistrationMode,
    RegistrationState,
    RuleTemplateBodyFormat,
    SourceOutcome,
    Stage,
    StageStatus,
    StageType,
    TeamMember,
    TeamMemberRole,
    TicketCategoryCoinSettings,
    Tournament,
    TournamentCategory,
    TournamentMode,
    TournamentPrize,
    TournamentRuleTemplate,
    TournamentStatus,
)


log = structlog.get_logger()


def append_audit_log(
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
    # Also to the server log, without the payload (comments, personal data).
    log.info(
        'netsession_tourney.audit',
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        actor_user_id=str(actor_user_id) if actor_user_id else None,
    )


def parse_source_outcome(raw_value: str | None) -> SourceOutcome:
    if not raw_value:
        return SourceOutcome.winner

    try:
        return SourceOutcome(raw_value)
    except ValueError:
        return SourceOutcome.winner


def db_tournament_category_to_model(
    db_category: DbNetsessionTourneyTournamentCategory,
) -> TournamentCategory:
    return TournamentCategory(
        id=db_category.id,
        party_id=db_category.party_id,
        position=db_category.position,
        title=db_category.title,
    )


def db_tournament_rule_template_to_model(
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


def db_tournament_prize_to_model(
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


def db_browser_push_config_to_model(
    db_config: DbNetsessionTourneyBrowserPushConfig,
) -> BrowserPushConfig:
    return BrowserPushConfig(
        party_id=db_config.party_id,
        enabled=db_config.enabled,
        vapid_public_key=db_config.vapid_public_key,
        created_at=db_config.created_at,
        updated_at=db_config.updated_at,
    )


def db_discord_dm_config_to_model(
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


def db_coin_settings_to_model(
    db_settings: DbNetsessionTourneyCoinSettings,
) -> CoinSettings:
    return CoinSettings(
        party_id=db_settings.party_id,
        enabled=db_settings.enabled,
        default_coin_amount=db_settings.default_coin_amount,
        created_at=db_settings.created_at,
        updated_at=db_settings.updated_at,
    )


def db_ticket_category_coin_settings_to_model(
    db_row: DbNetsessionTourneyTicketCategoryCoinSettings,
) -> TicketCategoryCoinSettings:
    return TicketCategoryCoinSettings(
        party_id=db_row.party_id,
        ticket_category_id=db_row.ticket_category_id,
        coin_amount=db_row.coin_amount,
    )


def db_coin_ledger_entry_to_model(
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


def db_tournament_to_model(db_tournament: DbNetsessionTourneyTournament) -> Tournament:
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


def db_stage_to_model(db_stage: DbNetsessionTourneyStage) -> Stage:
    return Stage(
        id=db_stage.id,
        tournament_id=db_stage.tournament_id,
        order_no=db_stage.order_no,
        type=StageType(db_stage.type),
        name=db_stage.name,
        settings=dict(db_stage.settings_json or {}),
        status=StageStatus(db_stage.status),
    )


def db_participant_to_model(db_participant: DbNetsessionTourneyParticipant) -> Participant:
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


def db_team_member_to_model(db_member: DbNetsessionTourneyTeamMember) -> TeamMember:
    return TeamMember(
        id=db_member.id,
        participant_id=db_member.participant_id,
        user_id=db_member.user_id,
        role=TeamMemberRole(db_member.role),
    )


def db_match_to_model(db_match: DbNetsessionTourneyMatch) -> Match:
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


def db_match_slot_to_model(db_slot: DbNetsessionTourneyMatchSlot) -> MatchSlot:
    return MatchSlot(
        id=db_slot.id,
        match_id=db_slot.match_id,
        slot_no=db_slot.slot_no,
        participant_id=db_slot.participant_id,
        source_match_slot_id=db_slot.source_match_slot_id,
        source_outcome=parse_source_outcome(db_slot.source_outcome),
    )


def db_match_result_to_model(db_result: DbNetsessionTourneyMatchResult) -> MatchResult:
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


def db_match_chat_message_to_model(
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
