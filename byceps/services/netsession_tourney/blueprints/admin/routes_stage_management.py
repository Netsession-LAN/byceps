"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.routes_stage_actions import (
    register_stage_builder_review_routes,
    register_stage_builder_start_routes,
    register_stage_delete_routes,
    register_stage_participant_source_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_generation import (
    register_stage_generation_routes,
)
from byceps.services.netsession_tourney.forms import (
    StageBuilderMainForm,
    StageBuilderPreliminaryForm,
    StageBuilderTimingForm,
    StageForm,
)
from byceps.services.netsession_tourney.models import (
    StageType,
)
from byceps.services.netsession_tourney.stage_builder_service import (
    build_stage_builder_plan,
)
from byceps.services.netsession_tourney.stage_generation import (
    preview_stage_match_generation,
)
from byceps.services.netsession_tourney.stage_service import (
    create_stage,
    update_stage,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from .result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
    get_stage_or_404,
)
from .result_redirects import (
    redirect_to_related_tournament_view,
)
from .stage_builder_participant_source import (
    participant_source_settings_from_form,
)
from .stage_builder_stage_form_data import (
    get_ffa_placement_points_row_count,
    stage_to_form_data,
)
from .stage_builder_stage_meta import (
    build_stage_builder_generation_summary,
    build_stage_builder_meta,
)
from .stage_builder_stage_settings import (
    stage_settings_from_form,
)
from .stage_builder_wizard_forms import (
    build_stage_builder_main_form,
    build_stage_builder_preliminary_form,
    build_stage_builder_timing_form,
)
from .stage_builder_wizard_state import (
    assert_tournament_has_no_stages_for_builder_or_redirect,
    get_stage_builder_default_main_stage_size,
    is_ffa_stage_builder_tournament,
    is_stage_builder_main_complete,
    is_stage_builder_preliminary_complete,
    is_stage_builder_timing_complete,
    stage_builder_steps,
)
from .wizard_helpers import (
    clear_stage_builder_wizard_state,
    get_stage_builder_wizard_state,
    set_stage_builder_wizard_state,
)


def register(blueprint):
    register_stage_builder_start_routes(blueprint)

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/main'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage_builder/main')
    def stage_builder_wizard_main(party_id, tournament_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not state:
            if is_ffa_stage_builder_tournament(tournament):
                state = {
                    'generation_basis': 'ready',
                    'main_stage_type': StageType.ffa_single_elimination.value,
                    'main_stage_size': get_stage_builder_default_main_stage_size(
                        tournament
                    ),
                    'max_players_per_match': 8,
                    'use_preliminary': False,
                    'preliminary_type': '',
                    'round_robin_builder_mode': None,
                    'round_robin_group_count': None,
                    'swiss_threshold': None,
                    'break_between_rounds_minutes': 0,
                }
            else:
                state = {
                    'generation_basis': 'ready',
                    'main_stage_type': StageType.double_elimination.value,
                    'main_stage_size': '16',
                    'max_players_per_match': None,
                    'use_preliminary': True,
                    'preliminary_type': StageType.round_robin_groups.value,
                    'round_robin_builder_mode': 'standard',
                    'round_robin_group_count': None,
                    'swiss_threshold': 3,
                    'break_between_rounds_minutes': 0,
                }

        return {
            'party': party,
            'tournament': tournament,
            'form': build_stage_builder_main_form(
                tournament=tournament,
                state=state,
                erroneous_form=erroneous_form,
            ),
            'wizard_step': 'main',
            'wizard_steps': stage_builder_steps(),
            'is_ffa_builder': is_ffa_stage_builder_tournament(tournament),
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/main'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_wizard_main_submit(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        form = build_stage_builder_main_form(
            tournament=tournament,
            state=state,
            erroneous_form=StageBuilderMainForm(
                request.form,
                tournament_mode=tournament.mode,
            ),
        )
        if not form.validate():
            return stage_builder_wizard_main(
                party.id, tournament.id, erroneous_form=form
            )

        if is_ffa_stage_builder_tournament(tournament):
            if form.max_players_per_match.data is None:
                form.max_players_per_match.errors.append(
                    gettext('Bitte eine gültige Heat-Größe angeben.')
                )
                return stage_builder_wizard_main(
                    party.id, tournament.id, erroneous_form=form
                )

            if (
                form.main_stage_type.data
                == StageType.ffa_flatout2_single_elimination.value
                and form.max_players_per_match.data not in {6, 7, 8}
            ):
                form.max_players_per_match.errors.append(
                    gettext(
                        'FlatOut 2 erlaubt hier nur 6, 7 oder 8 Teilnehmer.'
                    )
                )
                return stage_builder_wizard_main(
                    party.id, tournament.id, erroneous_form=form
                )

        state.update(
            {
                'generation_basis': str(
                    form.generation_basis.data or ''
                ).strip(),
                'main_stage_type': str(form.main_stage_type.data or '').strip(),
                'main_stage_size': str(form.main_stage_size.data or '').strip(),
                'max_players_per_match': form.max_players_per_match.data,
            }
        )
        set_stage_builder_wizard_state(party.id, tournament.id, state)
        return redirect_to(
            '.stage_builder_wizard_preliminary',
            party_id=party.id,
            tournament_id=tournament.id,
        )

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/preliminary'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage_builder/preliminary')
    def stage_builder_wizard_preliminary(
        party_id, tournament_id, erroneous_form=None
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        supports_preliminary_builder = True

        return {
            'party': party,
            'tournament': tournament,
            'form': build_stage_builder_preliminary_form(
                tournament=tournament,
                state=state,
                erroneous_form=erroneous_form,
            ),
            'wizard_step': 'preliminary',
            'wizard_steps': stage_builder_steps(),
            'supports_preliminary_builder': supports_preliminary_builder,
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/preliminary'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_wizard_preliminary_submit(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        form = build_stage_builder_preliminary_form(
            tournament=tournament,
            state=state,
            erroneous_form=StageBuilderPreliminaryForm(
                request.form,
                tournament_mode=tournament.mode,
                main_stage_type=(
                    StageType(state['main_stage_type'])
                    if state.get('main_stage_type')
                    in {stage_type.value for stage_type in StageType}
                    else None
                ),
            ),
        )
        if not form.validate():
            return stage_builder_wizard_preliminary(
                party.id, tournament.id, erroneous_form=form
            )

        if is_ffa_stage_builder_tournament(tournament):
            use_preliminary = bool(form.use_preliminary.data)
            state.update(
                {
                    'use_preliminary': use_preliminary,
                    'preliminary_type': (
                        str(form.preliminary_type.data or '').strip()
                        if use_preliminary
                        else ''
                    ),
                    'round_robin_builder_mode': None,
                    'round_robin_group_count': None,
                    'swiss_threshold': None,
                }
            )
        else:
            use_preliminary = bool(form.use_preliminary.data)
            state.update(
                {
                    'use_preliminary': use_preliminary,
                    'preliminary_type': str(
                        form.preliminary_type.data or ''
                    ).strip()
                    if use_preliminary
                    else '',
                    'round_robin_builder_mode': (
                        str(form.round_robin_builder_mode.data or '').strip()
                        if use_preliminary
                        else None
                    ),
                    'round_robin_group_count': (
                        form.round_robin_group_count.data
                        if use_preliminary
                        else None
                    ),
                    'swiss_threshold': (
                        form.swiss_threshold.data if use_preliminary else None
                    ),
                }
            )
        set_stage_builder_wizard_state(party.id, tournament.id, state)
        return redirect_to(
            '.stage_builder_wizard_timing',
            party_id=party.id,
            tournament_id=tournament.id,
        )

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/timing'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage_builder/timing')
    def stage_builder_wizard_timing(
        party_id, tournament_id, erroneous_form=None
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_preliminary_complete(state):
            return redirect_to(
                '.stage_builder_wizard_preliminary',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        return {
            'party': party,
            'tournament': tournament,
            'form': build_stage_builder_timing_form(
                state=state,
                erroneous_form=erroneous_form,
            ),
            'wizard_step': 'timing',
            'wizard_steps': stage_builder_steps(),
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/timing'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_wizard_timing_submit(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_preliminary_complete(state):
            return redirect_to(
                '.stage_builder_wizard_preliminary',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        form = build_stage_builder_timing_form(
            state=state,
            erroneous_form=StageBuilderTimingForm(request.form),
        )
        if not form.validate():
            return stage_builder_wizard_timing(
                party.id, tournament.id, erroneous_form=form
            )

        state.update(
            {
                'match_duration_minutes': form.match_duration_minutes.data,
                'max_matches_per_round': form.max_matches_per_round.data,
                'break_between_rounds_minutes': (
                    form.break_between_rounds_minutes.data or 0
                ),
            }
        )
        set_stage_builder_wizard_state(party.id, tournament.id, state)
        return redirect_to(
            '.stage_builder_wizard_review',
            party_id=party.id,
            tournament_id=tournament.id,
        )

    register_stage_builder_review_routes(blueprint)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/review'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_wizard_review_submit(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_preliminary_complete(state):
            return redirect_to(
                '.stage_builder_wizard_preliminary',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_timing_complete(state):
            return redirect_to(
                '.stage_builder_wizard_timing',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        try:
            generation_basis = str(state.get('generation_basis') or '').strip()
            main_stage_type = StageType(state['main_stage_type'])
            main_stage_size = int(state['main_stage_size'])
        except KeyError, TypeError, ValueError:
            flash_error(gettext('Ungültige Daten des Turnierplaners.'))
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        max_players_per_match = state.get('max_players_per_match')
        if max_players_per_match in {'', None}:
            max_players_per_match = None
        else:
            try:
                max_players_per_match = int(max_players_per_match)
            except TypeError, ValueError:
                flash_error(
                    gettext('Ungültige Matchgröße für den Turnierplaner.')
                )
                return redirect_to(
                    '.stage_builder_wizard_main',
                    party_id=party.id,
                    tournament_id=tournament.id,
                )

        preliminary_type = None
        swiss_threshold = None
        if state.get('use_preliminary'):
            raw_preliminary_type = str(
                state.get('preliminary_type') or ''
            ).strip()
            if not raw_preliminary_type:
                flash_error(gettext('Bitte ein Vorrundenformat auswählen.'))
                return redirect_to(
                    '.stage_builder_wizard_preliminary',
                    party_id=party.id,
                    tournament_id=tournament.id,
                )

            try:
                preliminary_type = StageType(raw_preliminary_type)
            except ValueError:
                flash_error(gettext('Ungültiges Vorrundenformat.'))
                return redirect_to(
                    '.stage_builder_wizard_preliminary',
                    party_id=party.id,
                    tournament_id=tournament.id,
                )

            if preliminary_type == StageType.swiss:
                swiss_threshold = state.get('swiss_threshold')
                if swiss_threshold not in {2, 3, 4}:
                    flash_error(
                        gettext(
                            'Swiss-Vorrunden benötigen eine gültige Schwelle.'
                        )
                    )
                    return redirect_to(
                        '.stage_builder_wizard_preliminary',
                        party_id=party.id,
                        tournament_id=tournament.id,
                    )

        match build_stage_builder_plan(
            party.id,
            tournament.id,
            generation_basis=generation_basis,
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            preliminary_type=preliminary_type,
            round_robin_builder_mode=state.get('round_robin_builder_mode'),
            round_robin_group_count=state.get('round_robin_group_count'),
            swiss_threshold=swiss_threshold,
            match_duration_minutes=state.get('match_duration_minutes'),
            max_matches_per_round=state.get('max_matches_per_round'),
            break_between_rounds_minutes=state.get(
                'break_between_rounds_minutes'
            ),
            initiator=g.user.as_user(),
        ):
            case Ok(created_stages):
                clear_stage_builder_wizard_state(party.id, tournament.id)
                flash_success(
                    gettext(
                        'Phasenplan wurde erstellt. %(count)s Phasen angelegt.',
                        count=len(created_stages),
                    )
                )
                selected_stage_id = (
                    created_stages[-1].id if created_stages else None
                )
                return redirect_to(
                    '.view',
                    party_id=party.id,
                    tournament_id=tournament.id,
                    tab='stages',
                    stage_id=selected_stage_id,
                )
            case Err(message):
                flash_error(message)
                return redirect_to(
                    '.stage_builder_wizard_review',
                    party_id=party.id,
                    tournament_id=tournament.id,
                )

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/create'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage/create_form')
    def stage_create_form(party_id, tournament_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = (
            erroneous_form
            if erroneous_form is not None
            else StageForm(
                data={'result_report_mode': 'both_must_confirm'},
                tournament_mode=tournament.mode,
                registration_mode=tournament.registration_mode.value,
            )
        )
        stages = get_stages_for_tournament(party.id, tournament.id)
        stage_source_mode = 'tournament'
        stage_qualifier_top_n = 1
        stage_qualifier_selection_mode = 'per_stage'
        selected_source_stage_ids: set[str] = set()

        if erroneous_form is not None:
            posted_mode = (
                request.form.get('participant_source_mode') or ''
            ).strip()
            if posted_mode:
                stage_source_mode = posted_mode
            selected_source_stage_ids = {
                source_stage_id
                for source_stage_id in request.form.getlist(
                    'qualifier_source_stage_ids'
                )
                if source_stage_id
            }
            posted_top_n = (request.form.get('qualifier_top_n') or '').strip()
            if posted_top_n:
                try:
                    stage_qualifier_top_n = max(1, int(posted_top_n))
                except ValueError:
                    pass
            posted_selection_mode = (
                request.form.get('qualifier_selection_mode') or ''
            ).strip()
            if posted_selection_mode in {'per_stage', 'per_group'}:
                stage_qualifier_selection_mode = posted_selection_mode

        return {
            'party': party,
            'tournament': tournament,
            'form': form,
            'placement_points_row_count': get_ffa_placement_points_row_count(
                tournament,
                form.placement_points.data,
                stage_type=(
                    StageType(form.type.data)
                    if form.type.data
                    in {stage_type.value for stage_type in StageType}
                    else None
                ),
                max_players_per_match=form.max_players_per_match.data,
            ),
            'show_participant_source_settings': True,
            'stage_source_mode': stage_source_mode,
            'stage_qualifier_top_n': stage_qualifier_top_n,
            'stage_qualifier_selection_mode': stage_qualifier_selection_mode,
            'selected_source_stage_ids': selected_source_stage_ids,
            'available_source_stages': stages,
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages'
    )
    @permission_required('netsession_tourney.manage')
    def stage_create(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = StageForm(
            request.form,
            tournament_mode=tournament.mode,
            registration_mode=tournament.registration_mode.value,
        )
        if not form.validate():
            flash_error(gettext('Ungültige Phasendaten.'))
            return stage_create_form(party.id, tournament.id, form)

        stages = get_stages_for_tournament(party.id, tournament.id)
        eligible_source_stages = {
            stage_item.id: stage_item for stage_item in stages
        }
        match participant_source_settings_from_form(
            request.form, eligible_source_stages=eligible_source_stages
        ):
            case Err(message):
                flash_error(message)
                return stage_create_form(party.id, tournament.id, form)
            case Ok(participant_source_settings):
                pass

        stage_settings_result = stage_settings_from_form(form)
        if stage_settings_result.is_err():
            flash_error(stage_settings_result.unwrap_err())
            return stage_create_form(party.id, tournament.id, form)

        settings = stage_settings_result.unwrap()
        settings.update(participant_source_settings)

        stage_type = StageType(form.type.data)
        match create_stage(
            party.id,
            tournament.id,
            stage_type,
            form.name.data,
            settings,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Phase wurde angelegt.'))
            case Err(message):
                flash_error(message)
                return stage_create_form(party.id, tournament.id, form)

        return redirect_to_related_tournament_view(party.id, tournament.id)

    register_stage_generation_routes(blueprint)

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/update'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage/update_form')
    def stage_update_form(
        party_id, tournament_id, stage_id, erroneous_form=None
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)
        stage_builder_meta = build_stage_builder_meta(stage)
        stage_builder_generation_summary = None
        if stage_builder_meta is not None:
            preview_result = preview_stage_match_generation(
                party.id, tournament.id, stage.id
            )
            if preview_result.is_ok():
                preview = preview_result.unwrap()
                stage_builder_generation_summary = (
                    build_stage_builder_generation_summary(
                        stage,
                        preview.stage,
                        preview.participant_count,
                        match_count=preview.match_count,
                    )
                )

        form = (
            erroneous_form
            if erroneous_form is not None
            else StageForm(
                data=stage_to_form_data(stage),
                tournament_mode=tournament.mode,
                registration_mode=tournament.registration_mode.value,
            )
        )

        stages = get_stages_for_tournament(party.id, tournament.id)
        available_source_stages = [
            stage_item
            for stage_item in stages
            if stage_item.id != stage.id
            and stage_item.order_no < stage.order_no
        ]

        stage_source_mode = str(
            stage.settings.get('participant_source_mode', 'tournament')
        )
        raw_qualifier_top_n = stage.settings.get('qualifier_top_n', 1)
        try:
            stage_qualifier_top_n = max(1, int(raw_qualifier_top_n))
        except TypeError, ValueError:
            stage_qualifier_top_n = 1
        stage_qualifier_selection_mode = str(
            stage.settings.get('qualifier_selection_mode', 'per_stage')
        )
        if stage_qualifier_selection_mode not in {'per_stage', 'per_group'}:
            stage_qualifier_selection_mode = 'per_stage'
        selected_source_stage_ids = {
            str(source_stage_id)
            for source_stage_id in stage.settings.get(
                'qualifier_source_stage_ids', []
            )
            if source_stage_id
        }

        if erroneous_form is not None:
            posted_mode = (
                request.form.get('participant_source_mode') or ''
            ).strip()
            if posted_mode:
                stage_source_mode = posted_mode
            posted_source_stage_ids = {
                source_stage_id
                for source_stage_id in request.form.getlist(
                    'qualifier_source_stage_ids'
                )
                if source_stage_id
            }
            selected_source_stage_ids = posted_source_stage_ids
            posted_top_n = (request.form.get('qualifier_top_n') or '').strip()
            if posted_top_n:
                try:
                    stage_qualifier_top_n = max(1, int(posted_top_n))
                except ValueError:
                    pass
            posted_selection_mode = (
                request.form.get('qualifier_selection_mode') or ''
            ).strip()
            if posted_selection_mode in {'per_stage', 'per_group'}:
                stage_qualifier_selection_mode = posted_selection_mode

        return {
            'party': party,
            'tournament': tournament,
            'stage': stage,
            'form': form,
            'placement_points_row_count': get_ffa_placement_points_row_count(
                tournament,
                form.placement_points.data,
                stage_type=stage.type,
                max_players_per_match=form.max_players_per_match.data,
                existing_settings=stage.settings,
            ),
            'show_participant_source_settings': True,
            'stage_source_mode': stage_source_mode,
            'stage_qualifier_top_n': stage_qualifier_top_n,
            'stage_qualifier_selection_mode': stage_qualifier_selection_mode,
            'selected_source_stage_ids': selected_source_stage_ids,
            'available_source_stages': available_source_stages,
            'stage_builder_meta': stage_builder_meta,
            'stage_builder_generation_summary': stage_builder_generation_summary,
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/update'
    )
    @permission_required('netsession_tourney.manage')
    def stage_update(party_id, tournament_id, stage_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)

        form = StageForm(
            request.form,
            tournament_mode=tournament.mode,
            registration_mode=tournament.registration_mode.value,
        )
        if not form.validate():
            flash_error(gettext('Ungültige Phasendaten.'))
            return stage_update_form(party.id, tournament.id, stage_id, form)

        stages = get_stages_for_tournament(party.id, tournament.id)
        eligible_source_stages = {
            stage_item.id: stage_item
            for stage_item in stages
            if stage_item.id != stage.id
            and stage_item.order_no < stage.order_no
        }
        match participant_source_settings_from_form(
            request.form, eligible_source_stages=eligible_source_stages
        ):
            case Err(message):
                flash_error(message)
                return stage_update_form(
                    party.id, tournament.id, stage_id, form
                )
            case Ok(participant_source_settings):
                pass

        stage_settings_result = stage_settings_from_form(
            form, existing_settings=stage.settings
        )
        if stage_settings_result.is_err():
            flash_error(stage_settings_result.unwrap_err())
            return stage_update_form(party.id, tournament.id, stage_id, form)

        settings = stage_settings_result.unwrap()
        for key in (
            'participant_source_mode',
            'qualifier_source_stage_ids',
            'qualifier_top_n',
        ):
            settings.pop(key, None)
        settings.update(participant_source_settings)

        stage_type = StageType(form.type.data)
        match update_stage(
            party.id,
            tournament.id,
            stage_id,
            stage_type,
            form.name.data,
            settings,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Phase wurde gespeichert.'))
            case Err(message):
                flash_error(message)
                return stage_update_form(
                    party.id, tournament.id, stage_id, form
                )

        return redirect_to_related_tournament_view(party.id, tournament.id)

    register_stage_participant_source_routes(blueprint)
    register_stage_delete_routes(blueprint)
