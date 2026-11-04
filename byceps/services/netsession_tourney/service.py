"""
byceps.services.netsession_tourney.service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Facade of the tournament service.

The service was split into topic modules (``*_service.py`` and helpers next
to this file). This module only re-exports their public names so existing
callers (``from ...service import x``, ``tourney_service.x``) keep working.
New code should import from the topic modules directly; the facade will be
removed once all callers are switched.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

# ruff: noqa: F401

from .browser_push_outbox import (
    process_browser_push_outbox,
)
from .browser_push_service import (
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
from .coin_service import (
    adjust_user_coins,
    configure_coin_settings,
    get_coin_settings,
    get_recent_coin_ledger_entries_for_user,
    get_ticket_category_coin_settings_for_party,
    get_user_coin_balance,
    is_tournament_coin_refund_available,
)
from .discord_dm_outbox import (
    process_discord_dm_outbox,
    send_test_discord_dm,
)
from .discord_dm_service import (
    configure_discord_dm,
    disable_discord_dm_subscription,
    get_configured_discord_bot_credentials,
    get_discord_dm_config,
    get_masked_discord_dm_bot_token,
    has_active_discord_dm_subscription_for_user,
    is_discord_dm_enabled_for_party,
    upsert_discord_dm_subscription,
)
from .discord_service import (
    configure_discord,
    process_discord_outbox,
)
from .double_grand_final import (
    get_match_results,
)
from .flatout2_rounds import (
    set_flatout2_match_host_by_admin,
)
from .generation_participants import (
    get_stage_generation_participants,
)
from .match_chat_service import (
    can_user_access_match_chat,
    get_match_chat_messages,
    post_match_chat_message,
)
from .match_generation import (
    generate_stage_matches,
)
from .match_queries import (
    find_match_for_tournament,
    get_match_slots,
    get_match_slots_for_match,
    get_match_timeline_entries,
    get_matches_for_tournament,
    get_open_matches_for_party,
)
from .match_schedule import (
    reschedule_match,
)
from .notification_service import (
    send_manual_tournament_notification,
)
from .participant_admin_service import (
    add_user_participant_by_admin,
    disqualify_participant,
    get_active_participant_counts_for_tournaments,
    get_participants_by_ids,
    remove_participant_by_admin,
    set_participant_status,
)
from .participant_state import (
    count_active_participants_for_tournament,
)
from .registration_service import (
    deregister_user,
    register_user,
)
from .registration_validation import (
    get_team_members_for_participants,
    is_stage_type_compatible_with_registration_mode,
)
from .result_deletion import (
    delete_match_result_by_admin,
    open_match_dispute,
)
from .result_report_mode import (
    is_stage_result_reporting_admin_only,
    RESULT_REPORT_MODE_ADMIN_ONLY,
)
from .result_service import (
    apply_walkover_result,
    report_result,
)
from .seed_service import (
    set_participant_seed,
    set_stage_generation_seeds,
)
from .slot_assignment import (
    set_match_slot_participant_by_admin,
)
from .stage_builder_preview import (
    preview_stage_builder_plan,
)
from .stage_builder_service import (
    build_stage_builder_plan,
)
from .stage_builder_settings import (
    STAGE_BUILDER_MAIN_STAGE_SIZES,
)
from .stage_generation import (
    preview_stage_match_generation,
)
from .stage_service import (
    create_stage,
    delete_stage,
    get_available_stage_type_specs,
    update_stage,
)
from .swiss_stage import (
    _build_swiss_round_layout,
)
from .swiss_thresholds import (
    _get_configured_swiss_threshold,
    _get_round_count_for_swiss_stage,
    _get_swiss_round_count_for_threshold,
    _get_swiss_threshold_for_round_count,
    _get_swiss_threshold_for_stage,
)
from .team_admin_service import (
    add_team_member_by_admin,
    assign_team_captain_by_admin,
    create_team_by_admin,
    remove_team_member_by_admin,
)
from .team_captain_service import (
    create_team_for_captain,
    find_managed_team_for_user,
    set_managed_team_ready_state,
    update_managed_team_for_captain,
)
from .team_invite_service import (
    get_team_invite_code_for_manager,
    join_team_by_invite_code,
    regenerate_team_invite_code_for_manager,
)
from .team_member_service import (
    add_team_member_by_captain,
    assign_team_captain_by_captain,
    remove_team_member_by_captain,
)
from .tournament_admin_service import (
    get_tournament_admin_user_ids,
    set_tournament_admin_user_ids,
)
from .tournament_category_service import (
    create_tournament_category,
    find_tournament_category,
    get_tournament_categories_for_party,
    move_tournament_category_down,
    move_tournament_category_up,
    update_tournament_category,
)
from .tournament_lifecycle_service import (
    cancel_tournament,
    close_tournament,
    delete_tournament,
    publish_tournament,
    unpublish_tournament,
)
from .tournament_prize_service import (
    create_tournament_prize,
    delete_tournament_prize,
    find_tournament_prize,
    get_tournament_prizes_for_tournament,
    update_tournament_prize,
)
from .tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
    get_user_active_participation_tournament_ids,
)
from .tournament_rule_template_service import (
    create_tournament_rule_template,
    find_tournament_rule_template,
    find_tournament_rule_template_by_slug_for_party,
    get_tournament_rule_templates_for_party,
    update_tournament_rule_template,
)
from .tournament_service import (
    create_tournament,
    find_tournament_by_slug_for_party,
    find_tournament_for_party,
    get_tournaments_for_party,
    update_tournament,
)
