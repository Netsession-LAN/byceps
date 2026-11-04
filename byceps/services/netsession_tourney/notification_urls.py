"""
byceps.services.netsession_tourney.notification_urls
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Absolute URLs for notifications sent outside the site (browser push, Discord): site host, assets, logos.
"""

from __future__ import annotations

from byceps.services.party import party_setting_service
from byceps.services.party.models import PartyID
from byceps.services.site import site_service
from byceps.services.site.models import SiteID

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
    DbNetsessionTourneyTournament,
)
from .notification_labels import (  # noqa: F401
    _build_double_elimination_notification_match_label,
    _build_double_elimination_notification_match_labels,
    _is_loser_notification_outcome,
    _label_notification_bracket_matches,
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
