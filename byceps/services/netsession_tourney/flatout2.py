"""
byceps.services.netsession_tourney.flatout2
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from collections import OrderedDict


FLATOUT2_MAX_RACES_PER_ROUND = 10

FLATOUT2_MODE_LABELS = OrderedDict(
    {
        'single_race': 'Single Race',
        'single_event': 'Single Event',
        'single_derby': 'Single Derby',
        'single_stunt': 'Single Stunt',
    }
)

FLATOUT2_TRACK_GROUPS = {
    'normal_race_tracks': [
        'Timberlands 1',
        'Timberlands 2',
        'Timberlands 3',
        'Pinegrove 1',
        'Pinegrove 2',
        'Pinegrove 3',
        'Midwest Ranch 1',
        'Midwest Ranch 2',
        'Midwest Ranch 3',
        'Farmlands 1',
        'Farmlands 2',
        'Farmlands 3',
        'Desert Oil Field',
        'Desert Scrap Yard',
        'Desert Town',
        'Water Canal 1',
        'Water Canal 2',
        'Water Canal 3',
        'City Central 1',
        'City Central 2',
        'City Central 3',
        'Downtown 1',
        'Downtown 2',
        'Downtown 3',
        'Riverbay Circuit 1',
        'Riverbay Circuit 2',
        'Riverbay Circuit 3',
        'Motor Raceway 1',
        'Motor Raceway 2',
        'Motor Raceway 3',
    ],
    'bonus_tracks_and_ovals': [
        'Figure of Eight 1',
        'Triloop Special',
        'Speedbowl',
        'Sand Speedway',
        'Crash Alley',
        'Figure of Eight 2',
        'Speedway Left',
        'Speedway Right',
        'Speedway Special',
    ],
    'derby_arenas': [
        'Gas Station Derby',
        'Parking Lot Derby',
        'Skyscraper Derby',
        'Derby Bowl 1',
        'Derby Bowl 2',
        'Derby Bowl 3',
    ],
    'stunt_events': [
        'High Jump',
        'Bowling',
        'Ski Jump',
        'Curling',
        'Stone-Skipping',
        'Ring of Fire',
        'Field Goal',
        'Royal Flush',
        'Basketball',
        'Darts',
        'Baseball',
        'Soccer',
    ],
}

FLATOUT2_VEHICLE_GROUPS = {
    'derby_class': [
        'Chili',
        'Malice',
        'Roamer',
        'Shaker',
        'Blaster XL',
        'Banger',
        'Splitter',
        'Switchblade',
        'Venom',
    ],
    'race_class': [
        'CTR',
        'Boxer',
        'Mad Rash',
        'Nevada',
        'Lancea',
        'Fortune',
        'Daytana',
        'Bullet',
        'Lentus',
        'Ventura',
        'Insetta',
    ],
    'street_class': [
        'Chili Pepper',
        'Scorpion',
        'Insetta Sport',
        'Sparrowhawk',
        'Crusader',
        'CTR Sport',
        'Vexter XS',
        'Speedshifter',
        'Canyon',
        'Terrator',
        'Sunray',
        'Speedevil',
        'Road King',
        'Bullet GT',
    ],
    'bonus_class': [
        'Pimpster',
        'Flatmobile',
        'Mob Car',
        'School Bus',
        'Rocket',
        'Truck',
    ],
    'stunt_class': [
        'Starflight',
        'Trailblazer',
        'Afterburner',
        'Rocket',
        'Nucleon',
    ],
}

FLATOUT2_MODE_SPECS = {
    'single_race': {
        'label': FLATOUT2_MODE_LABELS['single_race'],
        'track_groups': ['normal_race_tracks'],
        'vehicle_groups': [
            'derby_class',
            'race_class',
            'street_class',
            'bonus_class',
        ],
    },
    'single_event': {
        'label': FLATOUT2_MODE_LABELS['single_event'],
        'track_groups': ['bonus_tracks_and_ovals', 'derby_arenas'],
        'vehicle_groups': [
            'derby_class',
            'race_class',
            'street_class',
            'bonus_class',
        ],
    },
    'single_derby': {
        'label': FLATOUT2_MODE_LABELS['single_derby'],
        'track_groups': ['derby_arenas'],
        'vehicle_groups': ['derby_class'],
    },
    'single_stunt': {
        'label': FLATOUT2_MODE_LABELS['single_stunt'],
        'track_groups': ['stunt_events'],
        'vehicle_groups': ['stunt_class'],
    },
}

FLATOUT2_MODE_CHOICES = [
    {'value': mode, 'label': spec['label']}
    for mode, spec in FLATOUT2_MODE_SPECS.items()
]


def _flatten_unique(values_by_group: list[list[str]]) -> list[str]:
    seen: set[str] = set()
    flattened: list[str] = []
    for values in values_by_group:
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            flattened.append(value)
    return flattened


FLATOUT2_ALL_VEHICLES = _flatten_unique(list(FLATOUT2_VEHICLE_GROUPS.values()))


FLATOUT2_TRACK_CHOICES_BY_MODE = {
    mode: sorted(
        _flatten_unique(
            [FLATOUT2_TRACK_GROUPS[group_name] for group_name in spec['track_groups']]
        ),
        key=str.casefold,
    )
    for mode, spec in FLATOUT2_MODE_SPECS.items()
}

FLATOUT2_VEHICLE_CHOICES_BY_MODE = {
    mode: sorted(FLATOUT2_ALL_VEHICLES, key=str.casefold)
    for mode, spec in FLATOUT2_MODE_SPECS.items()
}

FLATOUT2_TRACK_SET_BY_MODE = {
    mode: set(values) for mode, values in FLATOUT2_TRACK_CHOICES_BY_MODE.items()
}

FLATOUT2_VEHICLE_SET_BY_MODE = {
    mode: set(values)
    for mode, values in FLATOUT2_VEHICLE_CHOICES_BY_MODE.items()
}


def get_flatout2_mode_label(mode: str | None) -> str:
    if not mode:
        return ''

    spec = FLATOUT2_MODE_SPECS.get(mode)
    return str(spec.get('label') or mode) if spec else mode
