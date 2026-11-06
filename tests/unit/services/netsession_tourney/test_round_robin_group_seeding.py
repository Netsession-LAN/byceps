"""Round robin groups take the seeds in snake order, so the strongest
players do not all end up in group A."""

from types import SimpleNamespace

from byceps.services.netsession_tourney.engines.bracket_helpers import (
    snake_groups,
)
from byceps.services.netsession_tourney.round_robin_builder import (
    build_round_robin_builder_group_stage_specs,
)


def test_snake_groups_spread_the_seeds():
    assert snake_groups(list(range(1, 9)), 2) == [[1, 4, 5, 8], [2, 3, 6, 7]]
    assert snake_groups(list(range(1, 13)), 4) == [
        [1, 8, 9],
        [2, 7, 10],
        [3, 6, 11],
        [4, 5, 12],
    ]


def test_snake_groups_keep_sizes_even():
    groups = snake_groups(list(range(1, 11)), 3)
    assert sorted(len(group) for group in groups) == [3, 3, 4]
    assert sorted(item for group in groups for item in group) == list(
        range(1, 11)
    )


def test_builder_groups_spread_the_seeds():
    participants = [SimpleNamespace(id=seed) for seed in range(1, 9)]

    specs = build_round_robin_builder_group_stage_specs(
        participants, group_count=2, qualifiers_per_group=2
    )

    assert [spec.participant_ids for spec in specs] == [
        [1, 4, 5, 8],
        [2, 3, 6, 7],
    ]
