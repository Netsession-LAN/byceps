"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_form
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The state of the manual FlatOut 2 generation form as shown to the admin
(see `stage_builder_helpers`; the submitted configuration is parsed in
`stage_builder_flatout2_config`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations


FLATOUT2_MAX_MATCH_COUNT_PER_ROUND = 10


def get_flatout2_max_players_per_match(settings: dict) -> int:
    try:
        max_players_per_match = int(settings.get('max_players_per_match') or 8)
    except TypeError, ValueError:
        max_players_per_match = 8
    return max(2, min(max_players_per_match, 8))


def get_list_setting(settings: dict, key: str) -> list:
    value = settings.get(key)
    return value if isinstance(value, list) else []


def get_dict_setting(settings: dict, key: str) -> dict:
    value = settings.get(key)
    return value if isinstance(value, dict) else {}


def _get_form_value(form, name: str) -> str:
    return (form.get(name) or '').strip()


# form state


def build_flatout2_participant_choices(participants: list) -> list[dict]:
    return [
        {'value': str(participant.id), 'label': participant.name}
        for participant in sorted(
            participants, key=lambda item: item.name.casefold()
        )
    ]


def build_flatout2_round_defaults_by_no(raw_rounds: list) -> dict[int, dict]:
    round_defaults_by_no: dict[int, dict] = {}
    for index, raw_round in enumerate(raw_rounds, start=1):
        if not isinstance(raw_round, dict):
            continue
        round_defaults_by_no[_get_default_round_no(raw_round, index)] = (
            raw_round
        )
    return round_defaults_by_no


def _get_default_round_no(raw_round: dict, index: int) -> int:
    try:
        return int(raw_round.get('round_no') or index)
    except TypeError, ValueError:
        return index
