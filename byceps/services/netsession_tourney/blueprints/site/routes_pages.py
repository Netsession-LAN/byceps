"""
byceps.services.netsession_tourney.blueprints.site.routes_pages
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tournament pages: overview, participants, ranking, rules.
"""

from __future__ import annotations


from flask import (
    g,
    redirect,
    url_for,
)
from flask_babel import format_datetime, gettext

from byceps.services.user import user_service
from byceps.util.framework.templating import templated

from ...double_grand_final import get_match_results
from ...match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from ...models import (
    TeamMemberRole,
)
from ...registration_validation import get_team_members_for_participants
from ...tournament_admin_service import get_tournament_admin_user_ids
from ...tournament_prize_service import get_tournament_prizes_for_tournament
from ...tournament_queries import (
    get_participants_for_tournament,
    get_stages_for_tournament,
)
from .body_rendering import (
    render_formatted_body_html as _render_formatted_body_html,
)
from .builder_display_helpers import (
    get_materialized_builder_round_robin_group_stages,
)
from .builder_helpers import get_materialized_builder_container_stages
from .match_helpers import (
    build_match_labels,
)
from .stage_filters import (
    uses_only_ffa_simple_stages,
    uses_only_flatout2_stages,
)
from .tournament_ranking import compute_tournament_ranking
from .user_state_helpers import (
    build_current_user_overview_match_rows,
    format_team_member_role_label,
    get_captain_team_for_current_user,
    get_current_user_coin_balance,
    get_current_user_tournament_membership,
    get_party_coin_settings,
    get_registration_state_for_tournament,
)

from .blueprint import blueprint
from .common import (
    build_public_tournament_status,
    get_main_nav_current_page_id,
    _find_tournament_rule_template,
    render_tournament_rule_template_body_html,
    _get_tournament_or_404,
    build_overview_stage_type_label,
)


@blueprint.get('/<slug>')
@templated
def view_overview(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    stages_by_id = {stage.id: stage for stage in stages}
    hide_bracket_tab = uses_only_ffa_simple_stages(stages, [])
    is_flatout2_tournament = uses_only_flatout2_stages(stages, [])
    stage_type_label = build_overview_stage_type_label(stages)

    participants = get_participants_for_tournament(g.party.id, tournament.id)
    members_by_participant_id = get_team_members_for_participants(
        {participant.id for participant in participants}
    )
    admin_user_ids = get_tournament_admin_user_ids(tournament.id)
    participant_user_ids = {
        participant.user_id for participant in participants if participant.user_id
    }
    member_user_ids = {
        member.user_id
        for members in members_by_participant_id.values()
        for member in members
    }
    users_by_id = user_service.get_users_indexed_by_id(
        participant_user_ids | member_user_ids | admin_user_ids,
        include_avatars=True,
    )
    admin_users = sorted(
        (users_by_id[user_id] for user_id in admin_user_ids if user_id in users_by_id),
        key=lambda user: user.screen_name.lower(),
    )
    registration_state = get_registration_state_for_tournament(tournament)
    coin_settings = get_party_coin_settings()
    current_user_coin_balance = get_current_user_coin_balance()
    captain_team = get_captain_team_for_current_user(tournament.id)
    current_user_tournament_membership = get_current_user_tournament_membership(
        participants,
        members_by_participant_id,
    )
    current_user_team_role_label = None
    current_user_team_role_icon_id = None
    current_user_overview_matches = []
    if current_user_tournament_membership is not None:
        current_user_member = current_user_tournament_membership['member']
        if current_user_member is not None:
            current_user_team_role_label = format_team_member_role_label(
                current_user_member.role
            )
            current_user_team_role_icon_id = (
                'crown'
                if current_user_member.role == TeamMemberRole.captain
                else 'controller'
            )

        matches = get_matches_for_tournament(g.party.id, tournament.id)
        slots_by_match_id = get_match_slots({match.id for match in matches})
        results_by_match_id = get_match_results({match.id for match in matches})
        match_labels_by_id = build_match_labels(
            matches,
            slots_by_match_id,
            stages_by_id,
        )
        participants_by_id = {
            participant.id: participant for participant in participants
        }
        current_user_overview_matches = build_current_user_overview_match_rows(
            tournament,
            matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            stages_by_id,
            match_labels_by_id,
            current_user_tournament_membership['participant'].id,
        )
    starts_at_label = (
        (
            f"{format_datetime(tournament.starts_at, 'EEEE')}, "
            f"{format_datetime(tournament.starts_at, 'd. MMMM y')}, "
            f"{format_datetime(tournament.starts_at, 'HH:mm')} Uhr"
        )
        if tournament.starts_at
        else '-'
    )
    starts_at_mobile_lines = (
        (
            (
                f"{format_datetime(tournament.starts_at, 'EEEE')}, "
                f"{format_datetime(tournament.starts_at, 'd.')}"
            ),
            format_datetime(tournament.starts_at, 'MMMM y'),
            f"{format_datetime(tournament.starts_at, 'HH:mm')} Uhr",
        )
        if tournament.starts_at
        else ('-',)
    )
    rule_template = _find_tournament_rule_template(tournament)
    rules_html = render_tournament_rule_template_body_html(rule_template)
    public_status = build_public_tournament_status(tournament)
    prizes = get_tournament_prizes_for_tournament(tournament.id)
    prizes_with_html = [
        {
            'position': prize.position,
            'body_html': _render_formatted_body_html(
                prize.body, prize.body_format
            ),
        }
        for prize in prizes
    ]
    preliminary_link_rows = [
        {
            'title': stage.name,
            'url': url_for(
                'netsession_tourney.view_preliminaries',
                slug=tournament.slug,
                stage=str(stage.id),
            ),
        }
        for stage in get_materialized_builder_round_robin_group_stages(stages)
    ]
    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'stage_type_label': stage_type_label,
        'starts_at_label': starts_at_label,
        'starts_at_mobile_lines': starts_at_mobile_lines,
        'admin_users': admin_users,
        'participants': participants,
        'members_by_participant_id': members_by_participant_id,
        'users_by_id': users_by_id,
        'registration_state': registration_state,
        'public_status': public_status,
        'coin_settings': coin_settings,
        'current_user_coin_balance': current_user_coin_balance,
        'captain_team': captain_team,
        'current_user_tournament_membership': current_user_tournament_membership,
        'current_user_team_role_label': current_user_team_role_label,
        'current_user_team_role_icon_id': current_user_team_role_icon_id,
        'current_user_overview_matches': current_user_overview_matches,
        'prizes': prizes_with_html,
        'preliminary_link_rows': preliminary_link_rows,
        'rule_template': rule_template,
        'rules_html': rules_html,
        'hide_bracket_tab': hide_bracket_tab,
        'show_preliminaries_tab': bool(preliminary_link_rows)
        and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'overview',
    }


@blueprint.get('/<slug>/participants')
@templated
def view_participants(slug):
    tournament = _get_tournament_or_404(slug)
    participants = get_participants_for_tournament(g.party.id, tournament.id)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    is_flatout2_tournament = uses_only_flatout2_stages(stages, [])
    members_by_participant_id = get_team_members_for_participants(
        {participant.id for participant in participants}
    )
    registration_state = get_registration_state_for_tournament(tournament)
    member_user_ids = {
        member.user_id
        for members in members_by_participant_id.values()
        for member in members
    }
    users_by_id = user_service.get_users_indexed_by_id(member_user_ids)
    captain_team = get_captain_team_for_current_user(tournament.id)
    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'participants': participants,
        'members_by_participant_id': members_by_participant_id,
        'users_by_id': users_by_id,
        'captain_team': captain_team,
        'registration_state': registration_state,
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'participants',
    }


@blueprint.get('/<slug>/ranking')
@templated
def view_ranking(slug):
    tournament = _get_tournament_or_404(slug)
    ranking = compute_tournament_ranking(g.party.id, tournament.id)
    participants = ranking.participants
    stages = ranking.stages
    matches = ranking.matches
    user_ids = {
        participant.user_id
        for participant in participants
        if participant.user_id is not None
    }
    users_by_id = user_service.get_users_indexed_by_id(user_ids)
    if participants and all(participant.type.value == 'team' for participant in participants):
        ranking_subject_label = gettext('Team')
    elif participants and all(participant.user_id is not None for participant in participants):
        ranking_subject_label = gettext('Spieler')
    else:
        ranking_subject_label = gettext('Teilnehmer')

    current_page_id = get_main_nav_current_page_id()

    return {
        'tournament': tournament,
        'ranking_rows': ranking.rows,
        'has_ranking_data': ranking.has_data,
        'is_final_ranking': ranking.is_final,
        'users_by_id': users_by_id,
        'ranking_subject_label': ranking_subject_label,
        'is_ffa_scoring_tournament': ranking.is_ffa_scoring,
        'is_flatout2_tournament': ranking.is_flatout2,
        'is_swiss_tournament': ranking.is_swiss,
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, matches),
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not ranking.is_flatout2,
        'current_page': current_page_id,
        'current_tournament_page': 'ranking',
    }


@blueprint.get('/<slug>/rules')
@templated
def view_rules(slug):
    tournament = _get_tournament_or_404(slug)
    stages = get_stages_for_tournament(g.party.id, tournament.id)
    is_flatout2_tournament = uses_only_flatout2_stages(stages, [])
    rule_template = _find_tournament_rule_template(tournament)
    if rule_template is None:
        return redirect(url_for('netsession_tourney.view_overview', slug=slug))
    rules_html = render_tournament_rule_template_body_html(rule_template)
    current_page_id = get_main_nav_current_page_id()
    return {
        'tournament': tournament,
        'rule_template': rule_template,
        'rules_html': rules_html,
        'hide_bracket_tab': uses_only_ffa_simple_stages(stages, []),
        'show_preliminaries_tab': bool(
            get_materialized_builder_container_stages(
                stages, role='preliminary'
            )
        ) and not is_flatout2_tournament,
        'current_page': current_page_id,
        'current_tournament_page': 'rules',
    }
