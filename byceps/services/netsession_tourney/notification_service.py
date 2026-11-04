"""
byceps.services.netsession_tourney.notification_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Notifications of users about tournament events (stored, then sent by browser push and Discord), including manual announcements by admins.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from byceps.database import db
from byceps.services.external_accounts import external_accounts_service
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .browser_push_outbox import (  # noqa: F401
    _build_browser_push_match_label,
    _build_browser_push_message_payload,
    _build_browser_push_private_key_for_pywebpush,
    _build_browser_push_vapid_subject,
    _format_browser_push_delivery_error,
    _get_browser_push_endpoint_host,
    _mark_browser_push_outbox_dead_letter,
    _schedule_browser_push_outbox_retry,
    process_browser_push_outbox,
)
from .browser_push_service import (  # noqa: F401
    _build_default_browser_push_config,
    _decrypt_browser_push_private_key,
    _derive_browser_push_public_key,
    _encrypt_browser_push_private_key,
    _generate_browser_push_private_key_pem,
    _get_active_browser_push_subscription_recipients_for_tournament,
    _get_browser_push_fernet,
    _get_browser_push_serializer,
    _is_missing_browser_push_table_error,
    BROWSER_PUSH_MAX_ATTEMPTS,
    BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS,
    configure_browser_push,
    count_active_browser_push_subscriptions_for_user,
    count_browser_push_subscribed_participants_for_tournament,
    disable_browser_push_subscription,
    get_browser_push_config,
    get_browser_push_public_key_for_party,
    get_browser_push_subscribed_user_ids_for_tournament,
    get_recent_browser_push_outbox_entries_for_tournament,
    has_active_browser_push_subscription_for_user,
    is_browser_push_enabled_for_party,
    upsert_browser_push_subscription,
)
from .coin_service import (  # noqa: F401
    _append_coin_ledger_entry,
    _build_default_coin_settings,
    _charge_coins_for_tournament_registration,
    _get_manual_coin_adjustment_amount_for_user,
    _get_registration_coin_delta_amount_for_user,
    _get_ticket_coin_amount_for_user,
    _refund_coins_for_tournament_registration_if_available,
    _validate_coin_cost,
    adjust_user_coins,
    configure_coin_settings,
    get_coin_settings,
    get_recent_coin_ledger_entries_for_user,
    get_ticket_category_coin_settings_for_party,
    get_user_coin_balance,
    get_user_coin_balances,
    is_tournament_coin_refund_available,
)
from .dbmodels import (
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyDiscordDmOutbox,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTournament,
)
from .discord_dm_outbox import (  # noqa: F401
    _build_discord_dm_message_payload,
    _build_test_discord_dm_message_payload,
    _mark_discord_dm_outbox_dead_letter,
    _schedule_discord_dm_outbox_retry,
    _send_discord_dm,
    process_discord_dm_outbox,
    send_test_discord_dm,
)
from .discord_dm_service import (  # noqa: F401
    _build_default_discord_dm_config,
    _decrypt_discord_dm_bot_token,
    _encrypt_discord_dm_bot_token,
    _get_discord_dm_fernet,
    _is_missing_discord_dm_table_error,
    _mask_discord_dm_bot_token,
    configure_discord_dm,
    count_active_discord_dm_subscriptions_for_user,
    disable_discord_dm_subscription,
    DISCORD_DM_MAX_ATTEMPTS,
    DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS,
    DISCORD_DM_TIMEOUT_SECONDS,
    get_configured_discord_bot_credentials,
    get_discord_dm_config,
    get_enabled_discord_dm_bot_credentials,
    get_masked_discord_dm_bot_token,
    has_active_discord_dm_subscription_for_user,
    is_discord_dm_enabled_for_party,
    upsert_discord_dm_subscription,
)
from .discord_forum_api import (  # noqa: F401
    _build_discord_bot_headers,
    _create_discord_forum_thread,
    _get_discord_channel,
    _is_discord_resource_missing,
    _patch_discord_channel,
    _patch_discord_forum_starter_message,
    _post_discord_forum_message,
    DISCORD_FORUM_TIMEOUT_SECONDS,
)
from .discord_forum_threads import (  # noqa: F401
    _clear_discord_thread_reference,
    _ensure_discord_thread_for_tournament,
    _recover_deleted_discord_forum_thread,
    _sync_discord_thread_for_tournament,
    _update_discord_forum_thread,
)
from .discord_payloads import (  # noqa: F401
    _build_discord_forum_thread_payload,
    _build_discord_match_completed_payload,
    _build_discord_message_payload,
    _build_discord_tournament_finished_payload,
)
from .discord_result_summaries import (  # noqa: F401
    _build_discord_match_completed_description,
    _build_discord_match_completed_fields,
    _build_discord_match_result_summary,
    _build_discord_tournament_finished_description,
    _build_discord_tournament_finished_fields,
    _build_discord_tournament_result_summary,
    _format_discord_tournament_placement,
    _normalize_discord_tournament_placements,
)
from .discord_service import (  # noqa: F401
    _mark_discord_outbox_dead_letter,
    _schedule_discord_outbox_retry,
    configure_discord,
    DISCORD_MAX_ATTEMPTS,
    DISCORD_SUPPORTED_EVENTS,
    enqueue_discord_event,
    process_discord_outbox,
)
from .models import (
    BrowserPushOutboxID,
    DiscordDmOutboxID,
    Stage,
    StageType,
    TournamentID,
    TournamentStatus,
)
from .notification_labels import (  # noqa: F401
    _build_double_elimination_notification_match_label,
    _build_double_elimination_notification_match_labels,
    _is_loser_notification_outcome,
    _label_notification_bracket_matches,
)
from .notification_urls import (  # noqa: F401
    _build_absolute_notification_url,
    _build_browser_push_badge_url,
    _build_browser_push_logo_urls,
    _find_browser_push_site_server_name,
    _to_browser_push_asset_url,
)
from .ranking_order import (  # noqa: F401
    _build_swiss_head_to_head_scores,
    _sort_ranked_participant_ids,
)
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
from .stage_ranking import (  # noqa: F401
    _build_stage_ranking_data,
    _get_ranked_participant_ids_for_stage,
    _StageRankingData,
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
from .tournament_prize_service import (  # noqa: F401
    _find_db_tournament_prize,
    create_tournament_prize,
    delete_tournament_prize,
    find_tournament_prize,
    get_tournament_prizes_for_tournament,
    update_tournament_prize,
)
from .tournament_queries import (  # noqa: F401
    _build_flatout2_first_race_summary,
    _build_flatout2_round_race_lines,
    _build_site_match_path,
    _build_site_tournament_overview_path,
    _db_stage_to_model_with_effective_status,
    _find_db_tournament_for_party,
    _get_active_user_ids_for_tournament,
    _get_ffa_points_per_kill,
    _get_flatout2_round_races,
    _get_match_host_participant_id,
    _get_match_involved_user_ids,
    _get_selected_host_user_ids,
    _is_walkover_score_json,
    _parse_match_result_slot_scores,
    _parse_numeric_score_value,
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    get_participants_for_tournament,
    get_stages_for_tournament,
)
from .tournament_rule_template_service import (  # noqa: F401
    _find_db_tournament_rule_template,
    create_tournament_rule_template,
    find_tournament_rule_template,
    find_tournament_rule_template_by_slug_for_party,
    get_tournament_rule_templates_for_party,
    update_tournament_rule_template,
)


@dataclass(frozen=True, kw_only=True)
class ManualNotificationDispatchResult:
    recipient_user_count: int
    subscription_count: int


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
        return Err('Browser-Benachrichtigungen sind ausgeschaltet.')

    title = title.strip()
    body = body.strip()
    target_url = (target_url or '').strip() or None

    if not title:
        return Err('Bitte einen Titel angeben.')
    if not body:
        return Err('Bitte eine Nachricht angeben.')
    if target_url is not None and not target_url.startswith('/'):
        return Err('Die Ziel-Adresse muss relativ sein und mit / beginnen.')

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
