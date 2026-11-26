"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask import g, request, url_for
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney import (
    browser_push_service,
    discord_dm_service,
    double_grand_final,
    match_queries,
    notification_service,
    participant_admin_service,
    participant_state,
    registration_validation,
    tournament_admin_service,
    tournament_category_service,
    tournament_lifecycle_service,
    tournament_prize_service,
    tournament_queries,
    tournament_rule_template_service,
    tournament_service,
)
from byceps.services.netsession_tourney.blueprints.site.bracket_helpers import (
    build_bracket_data,
    build_bracket_sections,
)
from byceps.services.netsession_tourney.blueprints.site.match_helpers import (
    build_match_labels,
    build_skipped_double_grand_final_match_ids,
    build_slot_scores_by_match_id,
)
from byceps.services.netsession_tourney.blueprints.site.round_based_public_rendering import (
    build_match_overview_sections,
)
from byceps.services.netsession_tourney.blueprints.site.swiss_public_rendering import (
    build_swiss_bracket_sections,
)
from byceps.services.netsession_tourney.flatout2 import get_flatout2_mode_label
from byceps.services.netsession_tourney.forms import (
    AdminTeamMemberAddForm,
    DiscordConfigForm,
    MatchDisputeForm,
    ParticipantDisqualifyForm,
    ParticipantStatusForm,
    TournamentForm,
    TournamentNotificationSendForm,
)
from byceps.services.netsession_tourney.logo_service import (
    get_discord_forum_image_choices,
    is_known_sponsor_logo_url,
    is_known_tournament_logo_url,
)
from byceps.services.netsession_tourney.models import (
    CoinChargeMode,
    CoinRefundPolicy,
    RegistrationMode,
    StageType,
    TournamentMode,
)
from byceps.services.netsession_tourney.screen_name_suggestions import (
    get_suggested_screen_names_for_party,
)
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from .result_helpers import (
    _get_tournament_or_404,
    get_match_or_404,
    get_participant_or_404,
    get_party_or_404,
)
from .result_redirects import (
    redirect_to_related_tournament_view,
)
from .route_config import (
    DISCORD_DM_EVENT_CHOICES,
    DISCORD_FORUM_EVENT_CHOICES,
    TOURNAMENT_DETAIL_TABS,
)
from .stage_builder_helpers import (
    build_stage_builder_container_preview_meta,
    build_stage_builder_meta,
    build_stage_display_rows,
    build_stage_generation_state,
    build_visible_stage_tabs,
    is_flatout2_stage_type,
)
from .wizard_forms import (
    set_logo_choices_for_form,
    set_rules_template_choices_for_form,
)
from .wizard_helpers import (
    assert_party_has_categories_or_redirect,
    get_available_tournament_admin_users,
    parse_admin_user_ids,
    parse_category_id,
    set_category_choices_for_form,
    update_form_with_categories,
)


def register(blueprint):
    @blueprint.get('/for_party/<party_id>/tournaments/<uuid:tournament_id>')
    @permission_required('netsession_tourney.view')
    @templated
    def view(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        requested_tab = (request.args.get('tab') or 'overview').strip().lower()
        current_subtab = (
            requested_tab
            if requested_tab in TOURNAMENT_DETAIL_TABS
            else 'overview'
        )
        categories_by_id = {
            category.id: category
            for category in tournament_category_service.get_tournament_categories_for_party(
                party.id
            )
        }
        category = categories_by_id.get(tournament.category_id)
        rule_templates_by_slug = {
            template.slug: template
            for template in tournament_rule_template_service.get_tournament_rule_templates_for_party(
                party.id
            )
        }
        selected_rules_template = (
            rule_templates_by_slug.get(tournament.rules_page_slug)
            if tournament.rules_page_slug
            else None
        )
        prizes = tournament_prize_service.get_tournament_prizes_for_tournament(
            tournament.id
        )
        stages = tournament_queries.get_stages_for_tournament(
            party.id, tournament.id
        )
        participants = tournament_queries.get_participants_for_tournament(
            party.id, tournament.id
        )
        participants_by_id = {
            participant.id: participant for participant in participants
        }
        members_by_participant_id = (
            registration_validation.get_team_members_for_participants(
                {participant.id for participant in participants}
            )
        )
        matches = match_queries.get_matches_for_tournament(
            party.id, tournament.id
        )
        slots_by_match_id = match_queries.get_match_slots(
            {match.id for match in matches}
        )
        results_by_match_id = double_grand_final.get_match_results(
            {match.id for match in matches}
        )
        stages_by_id = {stage.id: stage for stage in stages}
        sorted_matches = sorted(
            matches,
            key=lambda item: (
                stages_by_id.get(item.stage_id).order_no
                if stages_by_id.get(item.stage_id) is not None
                else 9999,
                item.round_no,
                item.match_no,
            ),
        )
        stage_ids_in_order = [stage.id for stage in stages]
        matches_by_stage_id: dict[UUID, list] = {}
        for match in sorted_matches:
            matches_by_stage_id.setdefault(match.stage_id, []).append(match)
        matches_by_stage_lookup = {
            stage_id: grouped_matches
            for stage_id, grouped_matches in matches_by_stage_id.items()
        }
        matches_by_stage = []
        for stage in stages:
            grouped_matches = matches_by_stage_id.get(stage.id, [])
            if grouped_matches:
                matches_by_stage.append(
                    {
                        'stage': stage,
                        'matches': grouped_matches,
                    }
                )
        for stage_id, grouped_matches in matches_by_stage_id.items():
            if stage_id in stage_ids_in_order or not grouped_matches:
                continue
            matches_by_stage.append(
                {
                    'stage': stages_by_id.get(stage_id),
                    'matches': grouped_matches,
                }
            )
        match_labels_by_id = build_match_labels(
            matches,
            slots_by_match_id,
            stages_by_id,
        )
        browser_push_config = browser_push_service.get_browser_push_config(
            party.id
        )
        discord_dm_config = discord_dm_service.get_discord_dm_config(party.id)
        browser_push_subscribed_participant_count = browser_push_service.count_browser_push_subscribed_participants_for_tournament(
            party.id, tournament.id
        )
        browser_push_subscribed_user_ids = browser_push_service.get_browser_push_subscribed_user_ids_for_tournament(
            party.id, tournament.id
        )
        browser_push_outbox_entries = browser_push_service.get_recent_browser_push_outbox_entries_for_tournament(
            tournament.id
        )
        browser_push_outbox_user_ids = {
            entry['user_id']
            for entry in browser_push_outbox_entries
            if entry.get('user_id') is not None
        }
        active_participant_count = (
            participant_state.count_active_participants_for_tournament(
                party.id, tournament.id
            )
        )
        admin_users_by_id = user_service.get_users_indexed_by_id(
            tournament_admin_service.get_tournament_admin_user_ids(
                tournament.id
            )
        )
        tournament_admin_users = sorted(
            admin_users_by_id.values(),
            key=lambda user: user.screen_name.lower(),
        )
        browser_push_recipient_user_ids = {
            participant.user_id
            for participant in participants
            if participant.user_id is not None
        }
        browser_push_recipient_user_ids.update(
            participant.manager_user_id
            for participant in participants
            if participant.manager_user_id is not None
        )
        browser_push_recipient_user_ids.update(
            member.user_id
            for members in members_by_participant_id.values()
            for member in members
        )
        browser_push_recipient_users_by_id = (
            user_service.get_users_indexed_by_id(
                browser_push_recipient_user_ids
            )
        )
        browser_push_recipient_rows = sorted(
            [
                {
                    'user_id': user_id,
                    'screen_name': user.screen_name,
                    'subscription_count': browser_push_service.count_active_browser_push_subscriptions_for_user(
                        party.id, user_id
                    ),
                }
                for user_id, user in browser_push_recipient_users_by_id.items()
            ],
            key=lambda item: item['screen_name'].lower(),
        )
        browser_push_outbox_users_by_id = user_service.get_users_indexed_by_id(
            browser_push_outbox_user_ids
        )

        stage_tabs = build_visible_stage_tabs(stages)
        stage_display_rows = build_stage_display_rows(stages)

        requested_stage_id = request.args.get('stage_id')
        selected_stage = (
            stage_tabs[0] if stage_tabs else (stages[0] if stages else None)
        )
        if stages and requested_stage_id:
            try:
                requested_stage_uuid = UUID(requested_stage_id)
            except ValueError:
                requested_stage_uuid = None
            if requested_stage_uuid is not None:
                selected_stage = next(
                    (
                        stage
                        for stage in stages
                        if stage.id == requested_stage_uuid
                    ),
                    selected_stage,
                )

        selected_stage_matches = []
        selected_stage_slots_by_match_id = {}
        selected_stage_results_by_match_id = {}
        selected_stage_match_labels_by_id = {}
        selected_stage_participants_by_id = {}
        selected_stage_users_by_id = {}
        selected_stage_slot_scores_by_match_id = {}
        selected_stage_skipped_double_grand_final_match_ids = set()
        selected_stage_bracket_sections = []
        selected_stage_round_based_sections = []
        selected_stage_swiss_bracket_sections = []
        selected_stage_state_counts = {}
        if selected_stage is not None:
            selected_stage_matches = [
                match
                for match in matches
                if match.stage_id == selected_stage.id
            ]
            selected_stage_match_ids = {
                match.id for match in selected_stage_matches
            }
            selected_stage_slots_by_match_id = {
                match_id: slots_by_match_id.get(match_id, [])
                for match_id in selected_stage_match_ids
            }
            selected_stage_results_by_match_id = {
                match_id: results_by_match_id.get(match_id)
                for match_id in selected_stage_match_ids
                if match_id in results_by_match_id
            }

            selected_stage_match_labels_by_id = build_match_labels(
                selected_stage_matches,
                selected_stage_slots_by_match_id,
                stages_by_id,
            )
            selected_stage_skipped_double_grand_final_match_ids = (
                build_skipped_double_grand_final_match_ids(
                    selected_stage_matches,
                    selected_stage_slots_by_match_id,
                    selected_stage_results_by_match_id,
                    stages_by_id,
                )
            )
            selected_stage_slot_scores_by_match_id = (
                build_slot_scores_by_match_id(
                    selected_stage_matches,
                    selected_stage_slots_by_match_id,
                    selected_stage_results_by_match_id,
                )
            )

            selected_stage_participant_ids = {
                slot.participant_id
                for slots in selected_stage_slots_by_match_id.values()
                for slot in slots
                if slot.participant_id is not None
            }
            if selected_stage_participant_ids:
                selected_stage_participants_by_id = (
                    participant_admin_service.get_participants_by_ids(
                        party.id, selected_stage_participant_ids
                    )
                )
                selected_stage_user_ids = {
                    participant.user_id
                    for participant in selected_stage_participants_by_id.values()
                    if participant.user_id is not None
                }
                selected_stage_users_by_id = (
                    user_service.get_users_indexed_by_id(
                        selected_stage_user_ids,
                        include_avatars=True,
                    )
                )

            selected_stage_bracket = build_bracket_data(
                selected_stage_matches,
                selected_stage_slots_by_match_id,
                selected_stage_participants_by_id,
            )
            selected_stage_bracket_sections = build_bracket_sections(
                selected_stage_bracket,
                selected_stage_match_labels_by_id,
            )
            if selected_stage.type in {
                StageType.swiss,
                StageType.round_robin_groups,
                StageType.league,
            }:
                if selected_stage.type == StageType.swiss:
                    selected_stage_swiss_bracket_sections = (
                        build_swiss_bracket_sections(
                            selected_stage_matches,
                            selected_stage_slots_by_match_id,
                            selected_stage_results_by_match_id,
                            selected_stage_slot_scores_by_match_id,
                            selected_stage_participants_by_id,
                            selected_stage_users_by_id,
                            selected_stage_match_labels_by_id,
                            {selected_stage.id: selected_stage},
                        )
                    )
                else:
                    selected_stage_round_based_sections = (
                        build_match_overview_sections(
                            selected_stage_bracket_sections,
                            {selected_stage.id: selected_stage},
                            selected_stage_results_by_match_id,
                            selected_stage_slot_scores_by_match_id,
                            selected_stage_match_labels_by_id,
                            selected_stage_users_by_id,
                            selected_stage_skipped_double_grand_final_match_ids,
                        )
                    )

            selected_stage_state_counts = {
                'pending': 0,
                'ready': 0,
                'in_progress': 0,
                'pending_confirmation': 0,
                'needs_admin_review': 0,
                'completed': 0,
                'disputed': 0,
            }
            for match in selected_stage_matches:
                key = match.state.value
                selected_stage_state_counts[key] = (
                    selected_stage_state_counts.get(key, 0) + 1
                )

        stage_builder_meta_by_id = {
            stage.id: build_stage_builder_meta(stage) for stage in stages
        }
        stage_generation_state_by_id = {
            stage.id: build_stage_generation_state(
                stage,
                stages_by_id,
                matches_by_stage_lookup,
            )
            for stage in stages
        }
        stage_builder_container_preview_meta_by_id = {
            stage.id: preview_meta
            for stage in stages
            if (
                preview_meta := build_stage_builder_container_preview_meta(
                    party.id, tournament.id, stage
                )
            )
            is not None
        }
        discord_form = DiscordConfigForm(
            data={
                'discord_enabled': tournament.discord_enabled,
                'forum_channel_id': tournament.discord_forum_channel_id,
                'discord_forum_image_url': tournament.discord_forum_image_url
                or '',
                'applied_tag_ids': ', '.join(
                    tournament.discord_applied_tag_ids
                ),
                'event_mask': tournament.discord_event_mask,
                'discord_dm_enabled': tournament.discord_dm_enabled,
                'discord_dm_event_mask': tournament.discord_dm_event_mask,
            }
        )
        discord_form.discord_forum_image_url.choices = [
            ('', gettext('Kein Discord-Forum-Bild ausgewählt'))
        ] + get_discord_forum_image_choices(party.id)
        discord_form.event_mask.choices = DISCORD_FORUM_EVENT_CHOICES
        discord_form.discord_dm_event_mask.choices = DISCORD_DM_EVENT_CHOICES

        return {
            'party': party,
            'tournament': tournament,
            'category': category,
            'selected_rules_template': selected_rules_template,
            'prizes': prizes,
            'current_subtab': current_subtab,
            'stages': stages,
            'stage_tabs': stage_tabs,
            'stage_display_rows': stage_display_rows,
            'participants': participants,
            'participants_by_id': participants_by_id,
            'active_participant_count': active_participant_count,
            'suggested_screen_names': get_suggested_screen_names_for_party(
                party.id
            ),
            'tournament_admin_users': tournament_admin_users,
            'members_by_participant_id': members_by_participant_id,
            'matches': matches,
            'sorted_matches': sorted_matches,
            'matches_by_stage': matches_by_stage,
            'stages_by_id': stages_by_id,
            'match_labels_by_id': match_labels_by_id,
            'slots_by_match_id': slots_by_match_id,
            'results_by_match_id': results_by_match_id,
            'selected_stage': selected_stage,
            'selected_stage_matches': selected_stage_matches,
            'selected_stage_slots_by_match_id': selected_stage_slots_by_match_id,
            'selected_stage_match_labels_by_id': selected_stage_match_labels_by_id,
            'selected_stage_results_by_match_id': selected_stage_results_by_match_id,
            'selected_stage_participants_by_id': selected_stage_participants_by_id,
            'selected_stage_users_by_id': selected_stage_users_by_id,
            'selected_stage_slot_scores_by_match_id': selected_stage_slot_scores_by_match_id,
            'selected_stage_skipped_double_grand_final_match_ids': selected_stage_skipped_double_grand_final_match_ids,
            'selected_stage_bracket_sections': selected_stage_bracket_sections,
            'selected_stage_round_based_sections': selected_stage_round_based_sections,
            'selected_stage_swiss_bracket_sections': (
                selected_stage_swiss_bracket_sections
            ),
            'selected_stage_state_counts': selected_stage_state_counts,
            'stage_builder_meta_by_id': stage_builder_meta_by_id,
            'stage_generation_state_by_id': stage_generation_state_by_id,
            'stage_builder_container_preview_meta_by_id': (
                stage_builder_container_preview_meta_by_id
            ),
            'discord_form': discord_form,
            'discord_forum_thread_id': tournament.discord_thread_id,
            'notification_send_form': TournamentNotificationSendForm(
                data={
                    'title': tournament.title,
                    'target_url': f'/ns-tourneys/{tournament.slug}',
                }
            ),
            'discord_dm_config': discord_dm_config,
            'browser_push_config': browser_push_config,
            'browser_push_subscribed_participant_count': browser_push_subscribed_participant_count,
            'browser_push_subscribed_user_ids': browser_push_subscribed_user_ids,
            'browser_push_recipient_rows': browser_push_recipient_rows,
            'browser_push_outbox_entries': browser_push_outbox_entries,
            'browser_push_outbox_users_by_id': browser_push_outbox_users_by_id,
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/notifications/send'
    )
    @permission_required('netsession_tourney.manage')
    def tournament_notification_send(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        form = TournamentNotificationSendForm(request.form)
        if not form.validate():
            flash_error(
                gettext('Benachrichtigung konnte nicht gesendet werden.')
            )
            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='notifications',
            )

        match notification_service.send_manual_tournament_notification(
            party.id,
            tournament.id,
            g.user.as_user(),
            title=form.title.data or '',
            body=form.body.data or '',
            target_url=form.target_url.data or None,
        ):
            case Err(message):
                flash_error(gettext(message))
            case Ok(dispatch_result):
                flash_success(
                    gettext(
                        'Benachrichtigung wurde an %(user_count)s Teilnehmer mit %(subscription_count)s aktiven Browser-Subscriptions gesendet.',
                        user_count=dispatch_result.recipient_user_count,
                        subscription_count=dispatch_result.subscription_count,
                    )
                )

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='notifications',
        )

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>'
    )
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/participant/view')
    def participant_view(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        participant = get_participant_or_404(
            party.id, tournament.id, participant_id
        )

        members_by_participant_id = (
            registration_validation.get_team_members_for_participants(
                {participant.id}
            )
        )
        members = members_by_participant_id.get(participant.id, [])
        member_user_ids = {member.user_id for member in members}
        user_ids = set(member_user_ids)
        if participant.manager_user_id is not None:
            user_ids.add(participant.manager_user_id)
        users_by_id = user_service.get_users_indexed_by_id(user_ids)

        return {
            'party': party,
            'tournament': tournament,
            'participant': participant,
            'members': members,
            'users_by_id': users_by_id,
            'suggested_screen_names': get_suggested_screen_names_for_party(
                party.id
            ),
            'participant_disqualify_form': ParticipantDisqualifyForm(
                data={'reason_code': 'admin_disqualification'}
            ),
            'status_form': ParticipantStatusForm(),
            'team_member_add_form': AdminTeamMemberAddForm(),
            'active_participant_count': participant_state.count_active_participants_for_tournament(
                party.id, tournament.id
            ),
        }

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>'
    )
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/match/view')
    def match_view(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        match = get_match_or_404(party.id, tournament.id, match_id)

        participants = tournament_queries.get_participants_for_tournament(
            party.id, tournament.id
        )
        participants_by_id = {
            participant.id: participant for participant in participants
        }
        all_matches = match_queries.get_matches_for_tournament(
            party.id, tournament.id
        )
        all_slots_by_match_id = match_queries.get_match_slots(
            {item.id for item in all_matches}
        )
        slots = all_slots_by_match_id.get(match.id, [])
        results_by_match_id = double_grand_final.get_match_results({match.id})
        result = results_by_match_id.get(match.id)
        stages = tournament_queries.get_stages_for_tournament(
            party.id, tournament.id
        )
        stages_by_id = {stage.id: stage for stage in stages}
        stage = stages_by_id.get(match.stage_id)
        is_flatout2_stage = stage is not None and is_flatout2_stage_type(
            stage.type
        )
        current_host_participant_id = (
            str((match.settings or {}).get('host_participant_id') or '').strip()
            if is_flatout2_stage
            else ''
        )
        flatout2_round_races = (
            (match.settings or {}).get('flatout2_races', [])
            if is_flatout2_stage
            else []
        )
        if is_flatout2_stage:
            flatout2_round_races = [
                {
                    **race,
                    'mode_label': get_flatout2_mode_label(
                        str(race.get('mode') or '').strip() or 'single_race'
                    ),
                }
                for race in flatout2_round_races
                if isinstance(race, dict)
            ]
        match_label = build_match_labels(
            all_matches,
            all_slots_by_match_id,
            stages_by_id,
        ).get(match.id, gettext('Match #%(match_no)s', match_no=match.match_no))
        return_to = (request.args.get('return_to') or 'matches').strip().lower()
        if return_to not in {'stages', 'matches'}:
            return_to = 'matches'
        if return_to == 'stages':
            back_stage_id = stage.id if stage is not None else None
            back_url = url_for(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='stages',
                stage_id=back_stage_id,
            )
            back_label = gettext('Zurück zu Phasen')
        else:
            back_stage_id = None
            back_url = url_for(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='matches',
            )
            back_label = gettext('Zurück zu Matches')

        return {
            'party': party,
            'tournament': tournament,
            'stage': stage,
            'match': match,
            'match_label': match_label,
            'participants': participants,
            'participants_by_id': participants_by_id,
            'slots': slots,
            'result': result,
            'is_flatout2_stage': is_flatout2_stage,
            'flatout2_round_races': flatout2_round_races,
            'current_host_participant_id': current_host_participant_id,
            'back_url': back_url,
            'back_label': back_label,
            'parent_return_to': return_to,
            'parent_stage_id': back_stage_id,
            'match_dispute_form': MatchDisputeForm(
                data={'reason_code': 'admin_dispute'}
            ),
        }

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/update'
    )
    @permission_required('netsession_tourney.manage')
    @templated
    def update_form(party_id, tournament_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        tournament = _get_tournament_or_404(party.id, tournament_id)
        available_admin_users = get_available_tournament_admin_users()
        assigned_admin_user_ids = (
            tournament_admin_service.get_tournament_admin_user_ids(
                tournament.id
            )
        )

        if erroneous_form:
            form = update_form_with_categories(
                party.id,
                category_id=tournament.category_id,
                erroneous_form=erroneous_form,
            )
        else:
            data = {
                'slug': tournament.slug,
                'title': tournament.title,
                'subtitle': tournament.subtitle,
                'tournament_logo_url': tournament.logo_url,
                'is_sponsored': tournament.is_sponsored,
                'sponsor_logo_url': tournament.sponsor_logo_url,
                'game': tournament.game,
                'category_id': str(tournament.category_id),
                'mode': tournament.mode.value,
                'registration_mode': tournament.registration_mode.value,
                'starts_at': tournament.starts_at,
                'visible_on_site': tournament.visible_on_site,
                'rules_template_slug': tournament.rules_page_slug,
                'registration_open': tournament.registration_open,
                'registration_deadline': tournament.registration_deadline,
                'roster_lock_at': tournament.roster_lock_at,
                'checkin_open_at': tournament.checkin_open_at,
                'checkin_close_at': tournament.checkin_close_at,
                'team_size': tournament.team_size or 1,
                'substitute_count': tournament.substitute_count or 0,
                'participant_limit': tournament.participant_limit,
                'coin_cost': tournament.coin_cost,
                'coin_refund_policy': tournament.coin_refund_policy.value,
                'coin_charge_mode': tournament.coin_charge_mode.value,
                'admin_user_ids': [
                    str(user_id)
                    for user_id in sorted(assigned_admin_user_ids, key=str)
                ],
            }
            form = update_form_with_categories(
                party.id,
                category_id=tournament.category_id,
                erroneous_form=TournamentForm(data=data),
            )
            form.registration_mode.data = tournament.registration_mode.value
            form.mode.data = tournament.mode.value
            form.category_id.data = str(tournament.category_id)
        form.set_admin_user_choices(
            [(str(user.id), user.screen_name) for user in available_admin_users]
        )
        set_logo_choices_for_form(
            form,
            party.id,
            selected_tournament_logo_url=tournament.logo_url,
            selected_sponsor_logo_url=tournament.sponsor_logo_url,
        )
        set_rules_template_choices_for_form(
            form,
            party.id,
            selected_slug=tournament.rules_page_slug,
        )

        return {
            'party': party,
            'tournament': tournament,
            'stages': tournament_queries.get_stages_for_tournament(
                party.id, tournament.id
            ),
            'form': form,
        }

    @blueprint.post('/for_party/<party_id>/tournaments/<uuid:tournament_id>')
    @permission_required('netsession_tourney.manage')
    def update(party_id, tournament_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = TournamentForm(request.form)
        set_category_choices_for_form(form, party.id)
        available_admin_users = get_available_tournament_admin_users()
        available_admin_user_ids = {
            str(user.id) for user in available_admin_users
        }
        form.set_admin_user_choices(
            [(str(user.id), user.screen_name) for user in available_admin_users]
        )
        set_logo_choices_for_form(
            form,
            party.id,
            selected_tournament_logo_url=tournament.logo_url,
            selected_sponsor_logo_url=tournament.sponsor_logo_url,
        )
        set_rules_template_choices_for_form(
            form,
            party.id,
            selected_slug=tournament.rules_page_slug,
        )
        if not form.validate():
            return update_form(party.id, tournament.id, form)

        tournament_logo_url = (
            form.tournament_logo_url.data.strip()
            if form.tournament_logo_url.data
            else None
        )
        if tournament_logo_url and not is_known_tournament_logo_url(
            party.id, tournament_logo_url
        ):
            flash_error(gettext('Ungültiges Turnierlogo ausgewählt.'))
            return update_form(party.id, tournament.id, form)

        is_sponsored = bool(form.is_sponsored.data)
        sponsor_logo_url = (
            form.sponsor_logo_url.data.strip()
            if form.sponsor_logo_url.data
            else None
        )
        if is_sponsored and not sponsor_logo_url:
            flash_error(gettext('Bitte ein Sponsor-Logo auswählen.'))
            return update_form(party.id, tournament.id, form)
        if sponsor_logo_url and not is_known_sponsor_logo_url(
            party.id, sponsor_logo_url
        ):
            flash_error(gettext('Ungültiges Sponsor-Logo ausgewählt.'))
            return update_form(party.id, tournament.id, form)

        category_id = parse_category_id(form.category_id.data)
        if category_id is None:
            flash_error(gettext('Bitte eine gültige Kategorie auswählen.'))
            return update_form(party.id, tournament.id, form)

        mode_changed = form.mode.data != tournament.mode.value
        registration_mode_changed = (
            form.registration_mode.data != tournament.registration_mode.value
        )

        result = tournament_service.update_tournament(
            party.id,
            tournament.id,
            g.user.as_user(),
            mode=TournamentMode(form.mode.data),
            registration_mode=RegistrationMode(form.registration_mode.data),
            title=form.title.data,
            subtitle=form.subtitle.data,
            logo_url=tournament_logo_url,
            is_sponsored=is_sponsored,
            sponsor_logo_url=sponsor_logo_url,
            game=form.game.data,
            starts_at=form.starts_at.data and to_utc(form.starts_at.data),
            visible_on_site=bool(form.visible_on_site.data),
            rules_page_slug=form.rules_template_slug.data,
            registration_open=bool(form.registration_open.data),
            registration_deadline=form.registration_deadline.data
            and to_utc(form.registration_deadline.data),
            roster_lock_at=form.roster_lock_at.data
            and to_utc(form.roster_lock_at.data),
            checkin_open_at=form.checkin_open_at.data
            and to_utc(form.checkin_open_at.data),
            checkin_close_at=form.checkin_close_at.data
            and to_utc(form.checkin_close_at.data),
            team_size=1
            if form.registration_mode.data == RegistrationMode.solo.value
            else form.team_size.data,
            substitute_count=0
            if form.registration_mode.data == RegistrationMode.solo.value
            else form.substitute_count.data,
            participant_limit=form.participant_limit.data,
            coin_cost=form.coin_cost.data,
            coin_refund_policy=CoinRefundPolicy(form.coin_refund_policy.data),
            coin_charge_mode=CoinChargeMode(
                CoinChargeMode.all_members.value
                if form.registration_mode.data == RegistrationMode.solo.value
                else form.coin_charge_mode.data
            ),
            category_id=category_id,
        )
        match result:
            case Ok(_):
                selected_admin_user_ids = parse_admin_user_ids(
                    form.admin_user_ids.data, available_admin_user_ids
                )
                set_admin_result = (
                    tournament_admin_service.set_tournament_admin_user_ids(
                        party.id,
                        tournament.id,
                        selected_admin_user_ids,
                        g.user.as_user(),
                    )
                )
                if set_admin_result.is_err():
                    flash_error(set_admin_result.unwrap_err())

                flash_success(gettext('Turnier wurde gespeichert.'))
                if mode_changed:
                    flash_success(
                        gettext('Modus geändert, alte Phasen wurden gelöscht.')
                    )
                if registration_mode_changed:
                    flash_success(gettext('Anmeldemodus wurde geändert.'))
            case Err(message):
                flash_error(message)
                return update_form(party.id, tournament.id, form)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/publish'
    )
    @permission_required('netsession_tourney.manage')
    def publish(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.publish_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier wurde veröffentlicht.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/unpublish'
    )
    @permission_required('netsession_tourney.manage')
    def unpublish(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.unpublish_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier ist wieder ein Entwurf.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/close'
    )
    @permission_required('netsession_tourney.manage')
    def close(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.close_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier wurde abgeschlossen.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/cancel'
    )
    @permission_required('netsession_tourney.manage')
    def cancel(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.cancel_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier wurde abgesagt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/delete'
    )
    @permission_required('netsession_tourney.manage')
    def delete(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match tournament_lifecycle_service.delete_tournament(
            party.id, tournament.id, g.user.as_user()
        ):
            case Ok(_):
                flash_success(gettext('Turnier wurde gelöscht.'))
                return redirect_to('.index', party_id=party.id)
            case Err(message):
                flash_error(message)
                return redirect_to_related_tournament_view(
                    party.id, tournament.id
                )
