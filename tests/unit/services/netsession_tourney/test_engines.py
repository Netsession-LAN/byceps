from dataclasses import replace
from uuid import uuid4

from byceps.services.netsession_tourney.engines.registry import (
    find_stage_engine,
    get_stage_type_spec,
)
from byceps.services.netsession_tourney.models import (
    Stage,
    StageID,
    StageStatus,
    StageType,
    TournamentID,
)


def _create_stage(
    stage_type: StageType, *, round_count: int | None = None
) -> Stage:
    settings = {}
    if round_count is not None:
        settings['round_count'] = round_count

    return Stage(
        id=StageID(uuid4()),
        tournament_id=TournamentID(uuid4()),
        order_no=1,
        type=stage_type,
        name='Stage',
        settings=settings,
        status=StageStatus.draft,
    )


def _create_participant_ids(count: int):
    return [uuid4() for _ in range(count)]


def test_single_elimination_generates_bracket():
    stage = _create_stage(StageType.single_elimination)
    engine = find_stage_engine(stage.type)
    assert engine is not None

    participant_ids = _create_participant_ids(4)

    result = engine.generate(stage, participant_ids)

    assert result.is_ok()
    specs = result.unwrap()
    assert len(specs) == 4
    assert specs[0].round_no == 1
    assert specs[1].round_no == 1
    assert specs[2].round_no == 2
    assert specs[3].round_no == 2
    consolation_match = specs[3]
    assert all(
        slot.source_outcome == 'loser'
        for slot in consolation_match.slots
        if slot.source_match_no is not None
    )


def test_single_elimination_with_5_participants_has_no_empty_first_round_match():
    stage = _create_stage(StageType.single_elimination)
    engine = find_stage_engine(stage.type)
    assert engine is not None

    participant_ids = _create_participant_ids(5)

    result = engine.generate(stage, participant_ids)

    assert result.is_ok()
    specs = result.unwrap()
    round1_specs = [spec for spec in specs if spec.round_no == 1]
    assert len(round1_specs) == 4
    assert all(
        any(slot.participant_id is not None for slot in spec.slots)
        for spec in round1_specs
    )


def test_swiss_generates_multiple_rounds():
    stage = _create_stage(StageType.swiss, round_count=5)
    engine = find_stage_engine(stage.type)
    assert engine is not None
    participant_ids = _create_participant_ids(8)

    result = engine.generate(stage, participant_ids)

    assert result.is_ok()
    specs = result.unwrap()
    assert len(specs) == 20
    assert max(spec.round_no for spec in specs) == 5


def test_swiss_rejects_even_round_count_without_threshold():
    stage = _create_stage(StageType.swiss, round_count=4)
    engine = find_stage_engine(stage.type)
    assert engine is not None

    result = engine.generate(stage, _create_participant_ids(8))

    assert result.is_err()


def test_swiss_distributes_bye_slots_over_rounds_for_odd_participants():
    stage = _create_stage(StageType.swiss, round_count=3)
    engine = find_stage_engine(stage.type)
    assert engine is not None
    participant_ids = _create_participant_ids(5)

    result = engine.generate(stage, participant_ids)

    assert result.is_ok()
    specs = result.unwrap()
    bye_participants_by_round = []
    for round_no in range(1, 4):
        round_specs = [spec for spec in specs if spec.round_no == round_no]
        bye_specs = [
            spec
            for spec in round_specs
            if len([slot for slot in spec.slots if slot.participant_id]) == 1
        ]
        assert len(bye_specs) == 1
        bye_participant = next(
            slot.participant_id
            for slot in bye_specs[0].slots
            if slot.participant_id is not None
        )
        bye_participants_by_round.append(bye_participant)

    assert len(set(bye_participants_by_round)) > 1


def test_ffa_single_elimination_distributes_players_evenly_in_first_round():
    stage = _create_stage(StageType.ffa_single_elimination)
    engine = find_stage_engine(stage.type)
    assert engine is not None

    result = engine.generate(stage, _create_participant_ids(9))

    assert result.is_ok()
    round1_specs = [spec for spec in result.unwrap() if spec.round_no == 1]
    player_counts = sorted(
        len([slot for slot in spec.slots if slot.participant_id])
        for spec in round1_specs
    )
    assert player_counts == [4, 5]


def test_ffa_single_elimination_marks_single_player_match_as_pending_bye():
    stage = _create_stage(StageType.ffa_single_elimination)
    stage = replace(stage, settings={'max_players_per_match': 2})
    engine = find_stage_engine(stage.type)
    assert engine is not None
    participant_ids = _create_participant_ids(3)

    result = engine.generate(stage, participant_ids)

    assert result.is_ok()
    specs = result.unwrap()
    round1_specs = [spec for spec in specs if spec.round_no == 1]
    single_player_specs = [
        spec
        for spec in round1_specs
        if len([slot for slot in spec.slots if slot.participant_id]) == 1
    ]
    assert len(single_player_specs) == 1
    assert single_player_specs[0].state == 'pending'
    assert len(single_player_specs[0].slots) == 2
    assert single_player_specs[0].slots[1].participant_id is None


def test_double_elimination_generates_loser_bracket_feeds():
    stage = _create_stage(StageType.double_elimination)
    engine = find_stage_engine(stage.type)
    assert engine is not None

    participant_ids = _create_participant_ids(8)
    result = engine.generate(stage, participant_ids)

    assert result.is_ok()
    specs = result.unwrap()
    assert len(specs) > 7
    assert any(
        slot.source_outcome == 'loser' for spec in specs for slot in spec.slots
    )


def test_double_elimination_generates_grand_final():
    stage = _create_stage(StageType.double_elimination)
    engine = find_stage_engine(stage.type)
    assert engine is not None

    participant_ids = _create_participant_ids(8)
    result = engine.generate(stage, participant_ids)

    assert result.is_ok()
    specs = result.unwrap()

    max_round_no = max(spec.round_no for spec in specs)
    last_round_matches = [
        spec for spec in specs if spec.round_no == max_round_no
    ]
    assert len(last_round_matches) == 1
    final_match = last_round_matches[0]
    assert len(final_match.slots) == 2
    assert all(slot.source_match_no is not None for slot in final_match.slots)
    assert all(slot.source_outcome == 'winner' for slot in final_match.slots)


def test_double_elimination_with_double_grand_final_generates_reset_match():
    stage = _create_stage(StageType.double_elimination_double_grand_final)
    engine = find_stage_engine(stage.type)
    assert engine is not None

    participant_ids = _create_participant_ids(8)
    result = engine.generate(stage, participant_ids)

    assert result.is_ok()
    specs = result.unwrap()
    specs_by_match_no = {spec.match_no: spec for spec in specs}

    reset_matches = [
        spec
        for spec in specs
        if len(spec.slots) == 2
        and all(slot.source_match_no is not None for slot in spec.slots)
        and {slot.source_outcome for slot in spec.slots} == {'winner', 'loser'}
        and len({slot.source_match_no for slot in spec.slots}) == 1
    ]
    assert len(reset_matches) == 1

    reset_match = reset_matches[0]
    source_match_no = reset_match.slots[0].source_match_no
    assert source_match_no is not None
    grand_final_1 = specs_by_match_no[source_match_no]
    assert all(slot.source_outcome == 'winner' for slot in grand_final_1.slots)


def test_stage_type_specs_mark_enabled_formats():
    enabled_spec = get_stage_type_spec(StageType.single_elimination)
    disabled_spec = get_stage_type_spec(StageType.gauntlet)

    assert enabled_spec.enabled
    assert enabled_spec.publishable
    assert not enabled_spec.beta

    assert not disabled_spec.enabled


def test_all_stage_types_have_an_engine():
    for stage_type in StageType:
        engine = find_stage_engine(stage_type)
        assert engine is not None


def test_all_stage_types_can_generate_matches():
    participant_ids = _create_participant_ids(8)

    for stage_type in StageType:
        stage = _create_stage(stage_type, round_count=3)
        if stage_type.value.startswith('ffa_'):
            stage = Stage(
                id=stage.id,
                tournament_id=stage.tournament_id,
                order_no=stage.order_no,
                type=stage.type,
                name=stage.name,
                settings={
                    **stage.settings,
                    'max_players_per_match': (
                        6
                        if stage_type
                        == StageType.ffa_flatout2_single_elimination
                        else 4
                    ),
                },
                status=stage.status,
            )

        engine = find_stage_engine(stage_type)
        assert engine is not None
        result = engine.generate(stage, participant_ids)
        assert result.is_ok()
        assert result.unwrap()


def test_double_elimination_with_two_participants_has_grand_final():
    stage = _create_stage(StageType.double_elimination)
    engine = find_stage_engine(stage.type)

    specs = engine.generate(stage, _create_participant_ids(2)).unwrap()

    assert [(spec.round_no, spec.match_no) for spec in specs] == [
        (1, 1),
        (2, 2),
    ]
    grand_final = specs[1]
    assert {
        (slot.source_match_no, slot.source_outcome)
        for slot in grand_final.slots
    } == {
        (1, 'winner'),
        (1, 'loser'),
    }


def test_double_grand_final_with_two_participants_has_reset_match():
    stage = _create_stage(StageType.double_elimination_double_grand_final)
    engine = find_stage_engine(stage.type)

    specs = engine.generate(stage, _create_participant_ids(2)).unwrap()

    assert len(specs) == 3
    assert {
        (slot.source_match_no, slot.source_outcome) for slot in specs[2].slots
    } == {
        (2, 'winner'),
        (2, 'loser'),
    }
