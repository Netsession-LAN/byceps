"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import random
from uuid import UUID

from flask import g, request
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney.forms import (
    StageBuilderMainForm,
    StageBuilderPreliminaryForm,
    StageBuilderTimingForm,
    StageForm,
)
from byceps.services.netsession_tourney.generation_participants import (
    get_stage_generation_participants,
)
from byceps.services.netsession_tourney.match_generation import (
    generate_stage_matches,
)
from byceps.services.netsession_tourney.match_queries import (
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.models import (
    Match,
    ParticipantID,
    StageID,
    StageType,
)
from byceps.services.netsession_tourney.seed_service import (
    set_stage_generation_seeds,
)
from byceps.services.netsession_tourney.stage_builder_service import (
    build_stage_builder_plan,
)
from byceps.services.netsession_tourney.stage_generation import (
    preview_stage_match_generation,
)
from byceps.services.netsession_tourney.stage_service import (
    create_stage,
    delete_stage,
    update_stage,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from .datetime_fields import serialize_utc_as_local
from .result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
    get_stage_or_404,
)
from .result_redirects import (
    redirect_to_related_tournament_view,
)
from .stage_builder_helpers import (
    assert_tournament_has_no_stages_for_builder_or_redirect,
    build_current_manual_seed_values_by_participant_id,
    build_flatout2_generation_state,
    build_round_robin_generation_intro,
    build_stage_builder_generation_summary,
    build_stage_builder_main_form,
    build_stage_builder_meta,
    build_stage_builder_preliminary_form,
    build_stage_builder_review_preview,
    build_stage_builder_timing_form,
    build_stage_generation_seed_rows,
    get_ffa_placement_points_row_count,
    get_stage_builder_default_main_stage_size,
    get_stage_generation_block_reason,
    is_builder_main_stage_with_preliminary_source,
    is_builder_round_robin_summary_stage,
    is_ffa_stage_builder_tournament,
    is_flatout2_stage_type,
    is_stage_builder_main_complete,
    is_stage_builder_preliminary_complete,
    is_stage_builder_timing_complete,
    parse_flatout2_generation_configuration,
    parse_stage_generation_auto_seed_participant_ids,
    parse_stage_generation_manual_seed_values_by_participant_id,
    participant_source_settings_from_form,
    stage_builder_steps,
    stage_settings_from_form,
    stage_to_form_data,
)
from .wizard_helpers import (
    clear_stage_builder_wizard_state,
    deserialize_datetime_local,
    get_stage_builder_wizard_state,
    set_stage_builder_wizard_state,
)


def register(blueprint):
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_form(party_id, tournament_id):
        return redirect_to(
            '.stage_builder_wizard_main',
            party_id=party_id,
            tournament_id=tournament_id,
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_create(party_id, tournament_id):
        return redirect_to(
            '.stage_builder_wizard_main',
            party_id=party_id,
            tournament_id=tournament_id,
        )

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

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/review'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage_builder/review')
    def stage_builder_wizard_review(party_id, tournament_id):
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

        return {
            'party': party,
            'tournament': tournament,
            'state': state,
            'wizard_step': 'review',
            'wizard_steps': stage_builder_steps(),
            'stage_builder_preview_summary': build_stage_builder_review_preview(
                party,
                tournament,
                state=state,
            ),
        }

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

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/generate'
    )
    @permission_required('netsession_tourney.manage')
    def stage_generate(party_id, tournament_id, stage_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)
        erroneous_flatout2_generation_form = (
            request.form if is_flatout2_stage_type(stage.type) else None
        )
        stages = get_stages_for_tournament(party.id, tournament.id)
        stages_by_id = {stage_item.id: stage_item for stage_item in stages}
        matches_by_stage: dict[StageID, list[Match]] = defaultdict(list)
        for match in get_matches_for_tournament(party.id, tournament.id):
            matches_by_stage[match.stage_id].append(match)
        generation_block_reason = get_stage_generation_block_reason(
            stage,
            stages_by_id,
            matches_by_stage,
        )
        if generation_block_reason:
            flash_error(generation_block_reason)
            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='stages',
                stage_id=stage.id,
            )

        is_locked_auto_seeding = is_builder_main_stage_with_preliminary_source(
            stage
        )
        existing_stage_match_count = sum(
            1
            for match in get_matches_for_tournament(party.id, tournament.id)
            if match.stage_id == stage.id
        )
        is_incremental_swiss_generation = False

        if is_flatout2_stage_type(stage.type):
            participants_result = get_stage_generation_participants(
                party.id, tournament.id, stage.id
            )
            if participants_result.is_err():
                flash_error(participants_result.unwrap_err())
                return stage_generate_form(
                    party.id,
                    tournament.id,
                    stage.id,
                    erroneous_flatout2_generation_form=request.form,
                )

            flatout2_config_result = parse_flatout2_generation_configuration(
                stage,
                participants_result.unwrap(),
                request.form,
            )
            if flatout2_config_result.is_err():
                flash_error(flatout2_config_result.unwrap_err())
                return stage_generate_form(
                    party.id,
                    tournament.id,
                    stage.id,
                    erroneous_flatout2_generation_form=request.form,
                )

            (
                stage_settings_patch,
                match_settings_by_round_and_match_no,
            ) = flatout2_config_result.unwrap()
            round_starts_at_by_round_no: dict[int, datetime] = {}
            for round_config in stage_settings_patch.get('flatout2_rounds', []):
                round_no = int(round_config.get('round_no') or 0)
                if round_no < 1:
                    continue
                raw_value = (
                    request.form.get(f'round_starts_at_round_{round_no}') or ''
                ).strip()
                if not raw_value:
                    continue
                starts_at_local = deserialize_datetime_local(raw_value)
                if starts_at_local is None:
                    flash_error(
                        gettext(
                            'Ungültiger Startzeitpunkt für Runde %(round_no)s.',
                            round_no=round_no,
                        )
                    )
                    return stage_generate_form(
                        party.id,
                        tournament.id,
                        stage.id,
                        erroneous_flatout2_generation_form=request.form,
                        erroneous_round_start_values_by_round_no={
                            round_no: raw_value
                        },
                    )
                round_starts_at_by_round_no[round_no] = to_utc(starts_at_local)
            correlation_id = request.headers.get('X-Correlation-ID')

            match generate_stage_matches(
                party.id,
                tournament.id,
                stage_id,
                g.user.as_user(),
                correlation_id=correlation_id,
                round_starts_at_by_round_no=round_starts_at_by_round_no or None,
                stage_settings_patch=stage_settings_patch,
                match_settings_by_round_and_match_no=match_settings_by_round_and_match_no,
            ):
                case Ok(matches):
                    flash_success(
                        gettext(
                            '%(count)s Matches wurden erzeugt.',
                            count=len(matches),
                        )
                    )
                case Err(message):
                    flash_error(message)

            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='stages',
                stage_id=stage.id,
            )

        participants_result = get_stage_generation_participants(
            party.id, tournament.id, stage.id
        )
        if participants_result.is_err():
            flash_error(participants_result.unwrap_err())
            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='stages',
                stage_id=stage.id,
            )

        participants = participants_result.unwrap()
        allowed_participant_ids = {
            participant.id for participant in participants
        }
        auto_seed_participant_ids_result = (
            parse_stage_generation_auto_seed_participant_ids(
                request.form, allowed_participant_ids
            )
        )
        if auto_seed_participant_ids_result.is_err():
            flash_error(auto_seed_participant_ids_result.unwrap_err())
            return stage_generate_form(
                party.id,
                tournament.id,
                stage.id,
                erroneous_auto_seed_participant_ids=request.form.getlist(
                    'auto_seed_participant_ids'
                ),
                erroneous_manual_seed_values_by_participant_id=request.form,
                erroneous_flatout2_generation_form=erroneous_flatout2_generation_form,
            )
        auto_seed_participant_ids = auto_seed_participant_ids_result.unwrap()

        if is_locked_auto_seeding:
            manual_seed_values_by_participant_id = {}
        else:
            manual_seed_values_result = (
                parse_stage_generation_manual_seed_values_by_participant_id(
                    request.form, allowed_participant_ids
                )
            )
            if manual_seed_values_result.is_err():
                flash_error(manual_seed_values_result.unwrap_err())
                return stage_generate_form(
                    party.id,
                    tournament.id,
                    stage.id,
                    erroneous_auto_seed_participant_ids=[
                        str(participant_id)
                        for participant_id in auto_seed_participant_ids
                    ],
                    erroneous_manual_seed_values_by_participant_id=request.form,
                    erroneous_flatout2_generation_form=erroneous_flatout2_generation_form,
                )
            manual_seed_values_by_participant_id = (
                manual_seed_values_result.unwrap()
            )

        round_starts_at_by_round_no: dict[int, datetime] = {}
        round_start_values_by_round_no: dict[int, str] = {}
        for key, raw_value in request.form.items():
            if not key.startswith('round_starts_at_round_'):
                continue
            try:
                round_no = int(key.removeprefix('round_starts_at_round_'))
            except ValueError:
                continue
            if round_no < 1:
                continue

            normalized_raw_value = (raw_value or '').strip()
            round_start_values_by_round_no[round_no] = normalized_raw_value
            if not normalized_raw_value:
                continue

            starts_at_local = deserialize_datetime_local(normalized_raw_value)
            if starts_at_local is None:
                flash_error(
                    gettext(
                        'Ungültiger Startzeitpunkt für Runde %(round_no)s.',
                        round_no=round_no,
                    )
                )
                return stage_generate_form(
                    party.id,
                    tournament.id,
                    stage_id,
                    erroneous_auto_seed_participant_ids=[
                        str(participant_id)
                        for participant_id in auto_seed_participant_ids
                    ],
                    erroneous_manual_seed_values_by_participant_id=request.form,
                    erroneous_round_start_values_by_round_no=round_start_values_by_round_no,
                    erroneous_flatout2_generation_form=erroneous_flatout2_generation_form,
                )

            round_starts_at_by_round_no[round_no] = to_utc(starts_at_local)

        seed_assignment_result = set_stage_generation_seeds(
            party.id,
            tournament.id,
            stage.id,
            auto_seed_participant_ids,
            manual_seed_values_by_participant_id,
            g.user.as_user(),
        )
        if seed_assignment_result.is_err():
            flash_error(seed_assignment_result.unwrap_err())
            return stage_generate_form(
                party.id,
                tournament.id,
                stage.id,
                erroneous_auto_seed_participant_ids=[
                    str(participant_id)
                    for participant_id in auto_seed_participant_ids
                ],
                erroneous_manual_seed_values_by_participant_id=request.form,
                erroneous_round_start_values_by_round_no=round_start_values_by_round_no,
                erroneous_flatout2_generation_form=erroneous_flatout2_generation_form,
            )

        correlation_id = request.headers.get('X-Correlation-ID')
        match generate_stage_matches(
            party.id,
            tournament.id,
            stage_id,
            g.user.as_user(),
            correlation_id=correlation_id,
            round_starts_at_by_round_no=round_starts_at_by_round_no or None,
        ):
            case Ok(matches):
                flash_success(
                    gettext(
                        '%(count)s Matches wurden erzeugt.',
                        count=len(matches),
                    )
                )
            case Err(message):
                flash_error(message)

        refreshed_stage = next(
            (
                candidate_stage
                for candidate_stage in get_stages_for_tournament(
                    party.id, tournament.id
                )
                if candidate_stage.id == stage_id
            ),
            None,
        )
        redirect_stage_id = stage_id
        if refreshed_stage is not None:
            materialized_group_stage_ids = (refreshed_stage.settings or {}).get(
                'builder_materialized_group_stage_ids', []
            )
            if materialized_group_stage_ids:
                try:
                    redirect_stage_id = UUID(
                        str(materialized_group_stage_ids[0])
                    )
                except TypeError, ValueError:
                    redirect_stage_id = stage_id

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='stages',
            stage_id=redirect_stage_id,
        )

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/generate'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage/generate_form')
    def stage_generate_form(
        party_id,
        tournament_id,
        stage_id,
        *,
        erroneous_auto_seed_participant_ids: list[str] | None = None,
        erroneous_manual_seed_values_by_participant_id=None,
        erroneous_round_start_values_by_round_no: dict[int, str] | None = None,
        erroneous_flatout2_generation_form=None,
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)
        stages = get_stages_for_tournament(party.id, tournament.id)
        stages_by_id = {stage_item.id: stage_item for stage_item in stages}
        matches_by_stage: dict[StageID, list[Match]] = defaultdict(list)
        for match in get_matches_for_tournament(party.id, tournament.id):
            matches_by_stage[match.stage_id].append(match)
        generation_block_reason = get_stage_generation_block_reason(
            stage,
            stages_by_id,
            matches_by_stage,
        )
        if generation_block_reason:
            flash_error(generation_block_reason)
            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='stages',
                stage_id=stage.id,
            )

        is_locked_auto_seeding = is_builder_main_stage_with_preliminary_source(
            stage
        )
        existing_stage_match_count = sum(
            1
            for match in get_matches_for_tournament(party.id, tournament.id)
            if match.stage_id == stage.id
        )
        is_incremental_swiss_generation = False
        is_incremental_flatout2_generation = False

        participants_result = get_stage_generation_participants(
            party.id, tournament.id, stage.id
        )
        if participants_result.is_err():
            flash_error(participants_result.unwrap_err())
            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='stages',
                stage_id=stage.id,
            )
        participants = participants_result.unwrap()
        participants_by_id = {
            participant.id: participant for participant in participants
        }

        if is_flatout2_stage_type(stage.type):
            flatout2_generation_state = build_flatout2_generation_state(
                stage,
                participants=participants,
                posted_form=erroneous_flatout2_generation_form,
            )
            round_start_values_by_round_no = {
                round_state['round_no']: (
                    erroneous_round_start_values_by_round_no or {}
                ).get(round_state['round_no'], '')
                for round_state in flatout2_generation_state['rounds']
                if round_state['is_active']
            }
            return {
                'party': party,
                'tournament': tournament,
                'stage': stage,
                'preview': None,
                'is_builder_round_robin_summary_stage': False,
                'round_robin_generation_intro': None,
                'stage_builder_preview_summary': None,
                'seed_rows': [],
                'auto_seed_participant_ids': [],
                'is_locked_auto_seeding': False,
                'round_start_values_by_round_no': round_start_values_by_round_no,
                'existing_stage_match_count': existing_stage_match_count,
                'is_incremental_swiss_generation': False,
                'is_incremental_flatout2_generation': is_incremental_flatout2_generation,
                'flatout2_generation_state': flatout2_generation_state,
                'is_flatout2_manual_stage': True,
            }

        preview_result = preview_stage_match_generation(
            party.id, tournament.id, stage.id
        )
        if preview_result.is_err():
            flash_error(preview_result.unwrap_err())
            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='stages',
                stage_id=stage.id,
            )

        preview = preview_result.unwrap()
        if is_locked_auto_seeding:
            auto_seed_participant_ids = [
                participant.id for participant in participants
            ]
        elif erroneous_auto_seed_participant_ids:
            auto_seed_participant_ids = []
            for raw_participant_id in erroneous_auto_seed_participant_ids:
                try:
                    participant_id = ParticipantID(
                        UUID(str(raw_participant_id))
                    )
                except ValueError:
                    continue
                if participant_id in participants_by_id:
                    auto_seed_participant_ids.append(participant_id)
            if set(auto_seed_participant_ids) != set(participants_by_id.keys()):
                auto_seed_participant_ids = list(participants_by_id.keys())
                random.shuffle(auto_seed_participant_ids)
        else:
            auto_seed_participant_ids = list(participants_by_id.keys())
            random.shuffle(auto_seed_participant_ids)

        if is_locked_auto_seeding:
            manual_seed_values_by_participant_id = {}
        elif erroneous_manual_seed_values_by_participant_id is not None:
            manual_seed_values_result = (
                parse_stage_generation_manual_seed_values_by_participant_id(
                    erroneous_manual_seed_values_by_participant_id,
                    set(participants_by_id.keys()),
                )
            )
            manual_seed_values_by_participant_id = (
                manual_seed_values_result.unwrap()
                if manual_seed_values_result.is_ok()
                else build_current_manual_seed_values_by_participant_id(
                    participants
                )
            )
        else:
            manual_seed_values_by_participant_id = (
                build_current_manual_seed_values_by_participant_id(participants)
            )

        seed_rows = build_stage_generation_seed_rows(
            participants,
            auto_seed_participant_ids,
            manual_seed_values_by_participant_id,
        )

        round_start_values_by_round_no: dict[int, str] = {}
        for round_preview in preview.rounds:
            round_start_values_by_round_no[round_preview.round_no] = (
                erroneous_round_start_values_by_round_no or {}
            ).get(
                round_preview.round_no,
                serialize_utc_as_local(round_preview.suggested_starts_at) or '',
            )

        return {
            'party': party,
            'tournament': tournament,
            'stage': stage,
            'preview': preview,
            'is_builder_round_robin_summary_stage': (
                is_builder_round_robin_summary_stage(stage)
            ),
            'round_robin_generation_intro': build_round_robin_generation_intro(
                stage,
                preview.stage,
                preview.participant_count,
            ),
            'stage_builder_preview_summary': build_stage_builder_generation_summary(
                stage,
                preview.stage,
                preview.participant_count,
                match_count=preview.match_count,
            ),
            'seed_rows': seed_rows,
            'auto_seed_participant_ids': auto_seed_participant_ids,
            'is_locked_auto_seeding': is_locked_auto_seeding,
            'round_start_values_by_round_no': round_start_values_by_round_no,
            'existing_stage_match_count': existing_stage_match_count,
            'is_incremental_swiss_generation': is_incremental_swiss_generation,
            'is_incremental_flatout2_generation': is_incremental_flatout2_generation,
            'flatout2_generation_state': None,
            'is_flatout2_manual_stage': False,
        }

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

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/participant-source'
    )
    @permission_required('netsession_tourney.manage')
    def stage_participant_source_update(party_id, tournament_id, stage_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        stage = get_stage_or_404(party.id, tournament.id, stage_id)
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
                return redirect_to(
                    '.view',
                    party_id=party.id,
                    tournament_id=tournament.id,
                    tab='stages',
                    stage_id=stage.id,
                )
            case Ok(participant_source_settings):
                pass

        settings = dict(stage.settings)
        for key in (
            'participant_source_mode',
            'qualifier_source_stage_ids',
            'qualifier_top_n',
        ):
            settings.pop(key, None)
        settings.update(participant_source_settings)

        match update_stage(
            party.id,
            tournament.id,
            stage.id,
            stage.type,
            stage.name,
            settings,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(
                    gettext('Teilnehmerquelle der Phase wurde aktualisiert.')
                )
            case Err(message):
                flash_error(message)

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='stages',
            stage_id=stage.id,
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/<uuid:stage_id>/delete'
    )
    @permission_required('netsession_tourney.manage')
    def stage_delete(party_id, tournament_id, stage_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match delete_stage(
            party.id,
            tournament.id,
            stage_id,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Phase wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)
