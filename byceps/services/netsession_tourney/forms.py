"""
byceps.services.netsession_tourney.forms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

import re

from flask_babel import lazy_gettext
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    FileField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
from wtforms.validators import InputRequired, Length, NumberRange, Optional, Regexp

from byceps.util.l10n import LocalizedForm

from .domain_service import ADMIN_SETTABLE_PARTICIPANT_STATUSES
from .enum_labels import RESULT_REPORT_MODE_LABELS, lazy_enum_label, stage_type_display_name
from .models import (
    CoinChargeMode,
    CoinRefundPolicy,
    RegistrationMode,
    RuleTemplateBodyFormat,
    StageFamily,
    StageType,
    TournamentMode,
)
from .stage_service import get_available_stage_type_specs
from .registration_validation import (
    is_stage_type_compatible_with_registration_mode,
)


SLUG_REGEX = re.compile(r'^[a-z0-9-]+$')
TEAM_ONLY_REGISTRATION_MODES = {
    RegistrationMode.team_captain_managed,
    RegistrationMode.team_preformed_only,
}

PARTICIPANT_LIMIT_CHOICES = [
    ('', '-'),
    ('8', '8'),
    ('16', '16'),
    ('32', '32'),
    ('64', '64'),
    ('128', '128'),
    ('256', '256'),
    ('512', '512'),
    ('1024', '1024'),
]

FFA_MAX_PLAYERS_PER_MATCH_CHOICES = [
    (count, str(count))
    for count in [
        *range(2, 17),
        20,
        24,
        32,
        48,
        64,
    ]
]

SUBSTITUTE_COUNT_CHOICES = [
    (str(count), str(count)) for count in range(0, 21)
]

PARTICIPANT_DISQUALIFY_REASON_CODE_CHOICES = [
    ('admin_disqualification', lazy_gettext('Administrative Disqualifikation')),
    ('rules_violation', lazy_gettext('Regelverstoß')),
    ('cheating', lazy_gettext('Cheating')),
    ('no_show', lazy_gettext('Nicht angetreten')),
    ('unsportsmanlike_conduct', lazy_gettext('Unsportliches Verhalten')),
    ('other', lazy_gettext('Sonstiges')),
]

MATCH_DISPUTE_REASON_CODE_CHOICES = [
    ('admin_dispute', lazy_gettext('Administrativer Streitfall')),
    ('score_conflict', lazy_gettext('Ergebnis-Konflikt')),
    ('rules_issue', lazy_gettext('Regelproblem')),
    ('technical_issue', lazy_gettext('Technisches Problem')),
    ('no_show_claim', lazy_gettext('Nichtantritt')),
    ('other', lazy_gettext('Sonstiges')),
]


def _to_optional_int(value: str | int | None) -> int | None:
    if isinstance(value, int):
        return value

    if value is None:
        return None

    stripped = str(value).strip()
    if not stripped:
        return None

    return int(stripped)


class TournamentForm(LocalizedForm):
    slug = StringField(
        lazy_gettext('Slug'),
        validators=[
            InputRequired(),
            Length(max=60),
            Regexp(
                SLUG_REGEX,
                message=lazy_gettext(
                    'Erlaubt sind Kleinbuchstaben, Ziffern und Bindestrich.'
                ),
            ),
        ],
    )
    title = StringField(
        lazy_gettext('Titel'), validators=[InputRequired(), Length(max=120)]
    )
    subtitle = StringField(
        lazy_gettext('Untertitel'), validators=[Optional(), Length(max=120)]
    )
    tournament_logo_url = SelectField(
        lazy_gettext('Turnierlogo'),
        validators=[Optional()],
        choices=[('', '-')],
    )
    is_sponsored = BooleanField(lazy_gettext('Gesponsert'))
    sponsor_logo_url = SelectField(
        lazy_gettext('Sponsor-Logo'),
        validators=[Optional()],
        choices=[('', '-')],
    )
    game = StringField(
        lazy_gettext('Spiel'), validators=[Optional(), Length(max=120)]
    )
    category_id = SelectField(
        lazy_gettext('Kategorie'),
        validators=[InputRequired()],
        choices=[],
    )
    mode = SelectField(
        lazy_gettext('Modus'),
        validators=[InputRequired()],
        choices=[
            (TournamentMode.duel.value, lazy_enum_label(TournamentMode.duel)),
            (TournamentMode.ffa.value, lazy_enum_label(TournamentMode.ffa)),
        ],
    )
    registration_mode = SelectField(
        lazy_gettext('Anmeldemodus'),
        validators=[InputRequired()],
        choices=[
            ('solo', lazy_enum_label(RegistrationMode.solo)),
            ('team_captain_managed', lazy_enum_label(RegistrationMode.team_captain_managed)),
            ('team_preformed_only', lazy_enum_label(RegistrationMode.team_preformed_only)),
            ('mixed', lazy_enum_label(RegistrationMode.mixed)),
        ],
    )
    starts_at = DateTimeLocalField(lazy_gettext('Start'), validators=[Optional()])
    visible_on_site = BooleanField(
        lazy_gettext('Auf der Website sichtbar'), default=True
    )
    rules_template_slug = SelectField(
        lazy_gettext('Regelvorlage'),
        validators=[Optional()],
        choices=[('', '-')],
    )
    registration_open = BooleanField(lazy_gettext('Anmeldung offen'))
    registration_deadline = DateTimeLocalField(
        lazy_gettext('Anmeldeschluss'), validators=[Optional()]
    )
    roster_lock_at = DateTimeLocalField(
        lazy_gettext('Kader-Sperre'), validators=[Optional()]
    )
    checkin_open_at = DateTimeLocalField(
        lazy_gettext('Check-in beginnt'), validators=[Optional()]
    )
    checkin_close_at = DateTimeLocalField(
        lazy_gettext('Check-in endet'), validators=[Optional()]
    )
    team_size = SelectField(
        lazy_gettext('Teamgröße'),
        validators=[InputRequired()],
        choices=[(str(size), str(size)) for size in range(1, 21)],
        coerce=int,
    )
    substitute_count = SelectField(
        lazy_gettext('Ersatzspieler'),
        validators=[InputRequired()],
        choices=SUBSTITUTE_COUNT_CHOICES,
        coerce=int,
    )
    participant_limit = SelectField(
        lazy_gettext('Teilnehmerlimit (Teams/Spieler)'),
        validators=[Optional()],
        choices=PARTICIPANT_LIMIT_CHOICES,
        coerce=_to_optional_int,
    )
    coin_cost = IntegerField(
        lazy_gettext('Coin-Kosten'),
        validators=[InputRequired(), NumberRange(min=0, max=100000)],
        default=0,
    )
    coin_refund_policy = SelectField(
        lazy_gettext('Rückgabe'),
        validators=[InputRequired()],
        choices=[
            (
                CoinRefundPolicy.until_tournament_end.value,
                lazy_gettext('Rückgabe bis Turnierende'),
            ),
            (
                CoinRefundPolicy.until_end_of_round_1.value,
                lazy_gettext('Rückgabe bis einschließlich Runde 1'),
            ),
        ],
    )
    coin_charge_mode = SelectField(
        lazy_gettext('Wer zahlt?'),
        validators=[InputRequired()],
        choices=[
            (
                CoinChargeMode.captain_only.value,
                lazy_gettext('Captain zahlt'),
            ),
            (
                CoinChargeMode.all_members.value,
                lazy_gettext('Alle Teammitglieder zahlen'),
            ),
        ],
        default=CoinChargeMode.all_members.value,
    )
    admin_user_ids = SelectMultipleField(
        lazy_gettext('Admins'),
        validators=[Optional()],
        choices=[],
    )

    def set_tournament_logo_choices(
        self, logo_choices: list[tuple[str, str]]
    ) -> None:
        choices = [('', '-')]
        choices.extend(logo_choices)
        self.tournament_logo_url.choices = choices

    def set_sponsor_logo_choices(
        self, logo_choices: list[tuple[str, str]]
    ) -> None:
        choices = [('', '-')]
        choices.extend(logo_choices)
        self.sponsor_logo_url.choices = choices

    def set_admin_user_choices(
        self, user_choices: list[tuple[str, str]]
    ) -> None:
        self.admin_user_ids.choices = user_choices

    def set_category_choices(
        self, category_choices: list[tuple[str, str]]
    ) -> None:
        self.category_id.choices = category_choices

    def set_rules_template_choices(
        self, choices: list[tuple[str, str]]
    ) -> None:
        all_choices = [('', '-')]
        all_choices.extend(choices)
        self.rules_template_slug.choices = all_choices


class TournamentCategoryForm(LocalizedForm):
    title = StringField(
        lazy_gettext('Titel'),
        validators=[InputRequired(), Length(max=40)],
    )


class CoinSettingsForm(LocalizedForm):
    enabled = BooleanField(lazy_gettext('Coins aktiviert'))
    default_coin_amount = IntegerField(
        lazy_gettext('Startguthaben pro Ticket'),
        validators=[InputRequired(), NumberRange(min=0, max=100000)],
        default=0,
    )


class CoinAdjustmentForm(LocalizedForm):
    screen_name = StringField(
        lazy_gettext('Benutzer'),
        validators=[InputRequired(), Length(max=40)],
    )
    plus_amount = IntegerField(
        lazy_gettext('Plus-Coins'),
        validators=[Optional(), NumberRange(min=0, max=100000)],
        default=0,
    )
    minus_amount = IntegerField(
        lazy_gettext('Minus-Coins'),
        validators=[Optional(), NumberRange(min=0, max=100000)],
        default=0,
    )
    note = StringField(
        lazy_gettext('Grund'),
        validators=[Optional(), Length(max=200)],
    )


class ManagedLogoUploadForm(LocalizedForm):
    file = FileField(
        lazy_gettext('Datei'),
        validators=[InputRequired()],
    )
    label = StringField(
        lazy_gettext('Name'),
        validators=[Optional(), Length(max=120)],
    )


class ManagedLogoLabelForm(LocalizedForm):
    label = StringField(
        lazy_gettext('Name'),
        validators=[InputRequired(), Length(max=120)],
    )


class SponsorLogoUploadForm(LocalizedForm):
    file = FileField(
        lazy_gettext('Datei'),
        validators=[InputRequired()],
    )
    label = StringField(
        lazy_gettext('Name'),
        validators=[Optional(), Length(max=120)],
    )
    target_url = StringField(
        lazy_gettext('Link-URL'),
        validators=[Optional(), Length(max=500)],
    )


class SponsorLogoForm(LocalizedForm):
    label = StringField(
        lazy_gettext('Name'),
        validators=[InputRequired(), Length(max=120)],
    )
    target_url = StringField(
        lazy_gettext('Link-URL'),
        validators=[Optional(), Length(max=500)],
    )


class TournamentWizardFormatForm(LocalizedForm):
    category_id = SelectField(
        lazy_gettext('Kategorie'),
        validators=[InputRequired()],
        choices=[],
    )
    mode = SelectField(
        lazy_gettext('Modus'),
        validators=[InputRequired()],
        choices=[
            (TournamentMode.duel.value, lazy_enum_label(TournamentMode.duel)),
            (TournamentMode.ffa.value, lazy_enum_label(TournamentMode.ffa)),
        ],
    )
    registration_mode = SelectField(
        lazy_gettext('Anmeldemodus'),
        validators=[InputRequired()],
        choices=[
            ('solo', lazy_enum_label(RegistrationMode.solo)),
            ('team_captain_managed', lazy_enum_label(RegistrationMode.team_captain_managed)),
            ('team_preformed_only', lazy_enum_label(RegistrationMode.team_preformed_only)),
            ('mixed', lazy_enum_label(RegistrationMode.mixed)),
        ],
    )
    team_size = SelectField(
        lazy_gettext('Teamgröße'),
        validators=[InputRequired()],
        choices=[(str(size), str(size)) for size in range(1, 21)],
        coerce=int,
    )
    substitute_count = SelectField(
        lazy_gettext('Ersatzspieler'),
        validators=[InputRequired()],
        choices=SUBSTITUTE_COUNT_CHOICES,
        coerce=int,
    )
    participant_limit = SelectField(
        lazy_gettext('Teilnehmerlimit (Teams/Spieler)'),
        validators=[Optional()],
        choices=PARTICIPANT_LIMIT_CHOICES,
        coerce=_to_optional_int,
    )
    coin_cost = IntegerField(
        lazy_gettext('Coin-Kosten'),
        validators=[InputRequired(), NumberRange(min=0, max=100000)],
        default=0,
    )
    coin_refund_policy = SelectField(
        lazy_gettext('Rückgabe'),
        validators=[InputRequired()],
        choices=[
            (
                CoinRefundPolicy.until_tournament_end.value,
                lazy_gettext('Rückgabe bis Turnierende'),
            ),
            (
                CoinRefundPolicy.until_end_of_round_1.value,
                lazy_gettext('Rückgabe bis einschließlich Runde 1'),
            ),
        ],
    )
    coin_charge_mode = SelectField(
        lazy_gettext('Wer zahlt?'),
        validators=[InputRequired()],
        choices=[
            (
                CoinChargeMode.captain_only.value,
                lazy_gettext('Captain zahlt'),
            ),
            (
                CoinChargeMode.all_members.value,
                lazy_gettext('Alle Teammitglieder zahlen'),
            ),
        ],
        default=CoinChargeMode.all_members.value,
    )
    admin_user_ids = SelectMultipleField(
        lazy_gettext('Admins'),
        validators=[Optional()],
        choices=[],
    )

    def set_category_choices(
        self, category_choices: list[tuple[str, str]]
    ) -> None:
        self.category_id.choices = category_choices

    def set_admin_user_choices(
        self, user_choices: list[tuple[str, str]]
    ) -> None:
        self.admin_user_ids.choices = user_choices


class TournamentWizardDetailsForm(LocalizedForm):
    slug = StringField(
        lazy_gettext('Slug'),
        validators=[
            InputRequired(),
            Length(max=60),
            Regexp(
                SLUG_REGEX,
                message=lazy_gettext(
                    'Erlaubt sind Kleinbuchstaben, Ziffern und Bindestrich.'
                ),
            ),
        ],
    )
    title = StringField(
        lazy_gettext('Titel'), validators=[InputRequired(), Length(max=120)]
    )
    subtitle = StringField(
        lazy_gettext('Untertitel'), validators=[Optional(), Length(max=120)]
    )
    tournament_logo_url = SelectField(
        lazy_gettext('Turnierlogo'),
        validators=[Optional()],
        choices=[('', '-')],
    )
    is_sponsored = BooleanField(lazy_gettext('Gesponsert'))
    sponsor_logo_url = SelectField(
        lazy_gettext('Sponsor-Logo'),
        validators=[Optional()],
        choices=[('', '-')],
    )
    game = StringField(
        lazy_gettext('Spiel'), validators=[Optional(), Length(max=120)]
    )
    rules_template_slug = SelectField(
        lazy_gettext('Regelvorlage'),
        validators=[Optional()],
        choices=[('', '-')],
    )
    discord_enabled = BooleanField(lazy_gettext('Discord-Forum aktiviert'))
    forum_channel_id = StringField(
        lazy_gettext('Forum-Channel-ID'),
        validators=[Optional(), Length(max=120)],
    )
    discord_forum_image_url = SelectField(
        lazy_gettext('Discord-Forum-Bild'),
        validators=[Optional()],
        choices=[('', '-')],
    )
    applied_tag_ids = StringField(
        lazy_gettext('Forum-Tag-IDs (kommagetrennt)'),
        validators=[Optional(), Length(max=500)],
    )
    event_mask = SelectMultipleField(
        lazy_gettext('Discord-Forum-Events'),
        choices=[],
        coerce=str,
    )

    def set_tournament_logo_choices(
        self, logo_choices: list[tuple[str, str]]
    ) -> None:
        choices = [('', '-')]
        choices.extend(logo_choices)
        self.tournament_logo_url.choices = choices

    def set_sponsor_logo_choices(
        self, logo_choices: list[tuple[str, str]]
    ) -> None:
        choices = [('', '-')]
        choices.extend(logo_choices)
        self.sponsor_logo_url.choices = choices

    def set_rules_template_choices(
        self, choices: list[tuple[str, str]]
    ) -> None:
        all_choices = [('', '-')]
        all_choices.extend(choices)
        self.rules_template_slug.choices = all_choices

    def set_discord_forum_image_choices(
        self, image_choices: list[tuple[str, str]]
    ) -> None:
        choices = [('', '-')]
        choices.extend(image_choices)
        self.discord_forum_image_url.choices = choices


class TournamentWizardScheduleForm(LocalizedForm):
    starts_at = DateTimeLocalField(lazy_gettext('Start'), validators=[Optional()])
    visible_on_site = BooleanField(
        lazy_gettext('Auf der Website sichtbar'), default=True
    )
    registration_open = BooleanField(lazy_gettext('Anmeldung offen'))
    registration_deadline = DateTimeLocalField(
        lazy_gettext('Anmeldeschluss'), validators=[Optional()]
    )
    roster_lock_at = DateTimeLocalField(
        lazy_gettext('Kader-Sperre'), validators=[Optional()]
    )
    checkin_open_at = DateTimeLocalField(
        lazy_gettext('Check-in beginnt'), validators=[Optional()]
    )
    checkin_close_at = DateTimeLocalField(
        lazy_gettext('Check-in endet'), validators=[Optional()]
    )


class TournamentRuleTemplateForm(LocalizedForm):
    slug = StringField(
        lazy_gettext('Slug'),
        validators=[
            InputRequired(),
            Length(max=120),
            Regexp(
                SLUG_REGEX,
                message=lazy_gettext(
                    'Erlaubt sind Kleinbuchstaben, Ziffern und Bindestrich.'
                ),
            ),
        ],
    )
    title = StringField(
        lazy_gettext('Titel'),
        validators=[InputRequired(), Length(max=120)],
    )
    body_format = SelectField(
        lazy_gettext('Textformat'),
        validators=[InputRequired()],
        choices=[
            (RuleTemplateBodyFormat.html.value, 'HTML'),
            (RuleTemplateBodyFormat.markdown.value, 'Markdown'),
        ],
    )
    body = TextAreaField(
        lazy_gettext('Text'),
        validators=[InputRequired(), Length(max=40000)],
    )


class TournamentPrizeForm(LocalizedForm):
    position = IntegerField(
        lazy_gettext('Platz'),
        validators=[InputRequired(), NumberRange(min=1, max=999)],
    )
    body_format = SelectField(
        lazy_gettext('Textformat'),
        validators=[InputRequired()],
        choices=[
            (RuleTemplateBodyFormat.markdown.value, 'Markdown'),
            (RuleTemplateBodyFormat.html.value, 'HTML'),
        ],
    )
    body = TextAreaField(
        lazy_gettext('Beschreibung'),
        validators=[InputRequired(), Length(max=40000)],
    )


class StageForm(LocalizedForm):
    type = SelectField(
        lazy_gettext('Phasentyp'),
        validators=[InputRequired()],
    )
    name = StringField(
        lazy_gettext('Name'), validators=[InputRequired(), Length(max=120)]
    )
    round_count = IntegerField(
        lazy_gettext('Rundenanzahl'),
        validators=[Optional(), NumberRange(min=1, max=20)],
    )
    swiss_threshold = SelectField(
        lazy_gettext('Swiss-Schwelle'),
        validators=[Optional()],
        choices=[('', '-')],
        coerce=_to_optional_int,
    )
    max_players_per_match = IntegerField(
        lazy_gettext('Maximale Spieler pro Match'),
        validators=[Optional(), NumberRange(min=2, max=64)],
    )
    group_size = IntegerField(
        lazy_gettext('Gruppengröße'),
        validators=[Optional(), NumberRange(min=2, max=64)],
    )
    placement_points = TextAreaField(
        lazy_gettext('Platzierungspunkte'),
        validators=[Optional(), Length(max=4000)],
    )
    points_per_kill = IntegerField(
        lazy_gettext('Punkte pro Kill'),
        validators=[Optional(), NumberRange(min=0, max=100)],
        default=1,
    )
    match_duration_minutes = IntegerField(
        lazy_gettext('Matchdauer (Minuten)'),
        validators=[Optional(), NumberRange(min=1, max=240)],
    )
    max_matches_per_round = IntegerField(
        lazy_gettext('Maximale Matches pro Runde'),
        validators=[Optional(), NumberRange(min=1, max=256)],
    )
    break_between_rounds_minutes = IntegerField(
        lazy_gettext('Pause zwischen Runden (Minuten)'),
        validators=[Optional(), NumberRange(min=0, max=240)],
    )
    result_report_mode = SelectField(
        lazy_gettext('Ergebnis-Übermittlungsmodus'),
        validators=[Optional()],
        choices=list(RESULT_REPORT_MODE_LABELS.items()),
    )

    def __init__(
        self,
        *args,
        tournament_mode: TournamentMode | None = None,
        registration_mode: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        specs = get_available_stage_type_specs()
        if tournament_mode is not None:
            expected_family = (
                StageFamily.duel
                if tournament_mode == TournamentMode.duel
                else StageFamily.ffa
            )
            specs = [spec for spec in specs if spec.family == expected_family]
        if registration_mode is not None:
            tournament_registration_mode = RegistrationMode(registration_mode)
            specs = [
                spec
                for spec in specs
                if is_stage_type_compatible_with_registration_mode(
                    spec.type,
                    tournament_registration_mode,
                )
            ]

        self.type.choices = [
            (
                spec.type.value,
                (
                    f'{stage_type_display_name(spec.type)} (disabled/beta)'
                    if not spec.publishable
                    else stage_type_display_name(spec.type)
                ),
            )
            for spec in specs
            if spec.enabled
        ]
        self.swiss_threshold.choices = [
            ('', '-'),
            (2, '2'),
            (3, '3'),
            (4, '4'),
        ]


class StageBuilderMainForm(LocalizedForm):
    generation_basis = SelectField(
        lazy_gettext('Generierungsbasis'),
        validators=[InputRequired()],
    )
    main_stage_type = SelectField(
        lazy_gettext('Typ des Hauptturniers'),
        validators=[InputRequired()],
    )
    main_stage_size = SelectField(
        lazy_gettext('Größe des Hauptturniers'),
        validators=[InputRequired()],
    )
    max_players_per_match = SelectField(
        lazy_gettext('Maximale Teilnehmer pro Match'),
        validators=[Optional()],
        choices=[('', '-')],
        coerce=_to_optional_int,
    )

    def __init__(
        self,
        *args,
        tournament_mode: TournamentMode | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.generation_basis.choices = [('ready', 'Bereite Teilnehmer')]
        if tournament_mode == TournamentMode.ffa:
            self.main_stage_type.choices = [
                (
                    StageType.ffa_single_elimination.value,
                    'FFA Single Elimination',
                ),
            ]
        else:
            self.main_stage_type.choices = [
                (StageType.single_elimination.value, 'Single Elimination'),
                (StageType.double_elimination.value, 'Double Elimination'),
                (
                    StageType.double_elimination_double_grand_final.value,
                    'Double Elimination + Double Grand Final',
                ),
            ]
        self.main_stage_size.choices = [
            choice for choice in PARTICIPANT_LIMIT_CHOICES if choice[0]
        ]
        self.max_players_per_match.choices = FFA_MAX_PLAYERS_PER_MATCH_CHOICES


class StageBuilderPreliminaryForm(LocalizedForm):
    use_preliminary = BooleanField(
        lazy_gettext('Vorrunde automatisch verwenden, falls nötig'),
        default=True,
    )
    preliminary_type = SelectField(
        lazy_gettext('Vorrundenformat'),
        validators=[Optional()],
    )
    round_robin_builder_mode = SelectField(
        lazy_gettext('Round-Robin-Strategie'),
        validators=[Optional()],
    )
    round_robin_group_count = IntegerField(
        lazy_gettext('Gruppenzahl (Expertenoption)'),
        validators=[Optional(), NumberRange(min=2, max=128)],
    )
    swiss_threshold = SelectField(
        lazy_gettext('Swiss-Schwelle'),
        validators=[Optional()],
        choices=[('', '-')],
        coerce=_to_optional_int,
    )

    def __init__(
        self,
        *args,
        tournament_mode: TournamentMode | None = None,
        main_stage_type: StageType | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if tournament_mode == TournamentMode.ffa:
            self.preliminary_type.choices = [
                ('', '-'),
                (
                    StageType.ffa_single_elimination.value,
                    'FFA Single Elimination',
                ),
            ]
        else:
            self.preliminary_type.choices = [
                ('', '-'),
                (StageType.round_robin_groups.value, 'Round Robin Groups'),
                (StageType.swiss.value, 'Swiss'),
            ]
        self.round_robin_builder_mode.choices = [
            ('standard', 'Empfohlener Standard'),
            ('manual_group_count', 'Expertenoption: Gruppenzahl manuell'),
        ]
        self.swiss_threshold.choices = [(2, '2'), (3, '3'), (4, '4')]


class StageBuilderTimingForm(LocalizedForm):
    match_duration_minutes = IntegerField(
        lazy_gettext('Matchdauer (Minuten)'),
        validators=[Optional(), NumberRange(min=1, max=240)],
    )
    max_matches_per_round = IntegerField(
        lazy_gettext('Maximale Matches pro Runde'),
        validators=[Optional(), NumberRange(min=1, max=256)],
    )
    break_between_rounds_minutes = IntegerField(
        lazy_gettext('Pause zwischen Runden (Minuten)'),
        validators=[Optional(), NumberRange(min=0, max=240)],
    )


class TeamCreationForm(LocalizedForm):
    name = StringField(
        lazy_gettext('Teamname'), validators=[InputRequired(), Length(max=120)]
    )
    logo_file = FileField(
        lazy_gettext('Team-Logo-Datei'),
        validators=[Optional()],
    )


class TeamJoinForm(LocalizedForm):
    invite_code = StringField(
        lazy_gettext('Invite-Code'),
        validators=[InputRequired(), Length(min=4, max=32)],
    )


class TeamMemberAddForm(LocalizedForm):
    screen_name = StringField(
        lazy_gettext('Anzeigename'),
        validators=[InputRequired(), Length(min=3, max=40)],
    )


class AdminParticipantAddForm(LocalizedForm):
    screen_name = StringField(
        lazy_gettext('Anzeigename'),
        validators=[InputRequired(), Length(min=3, max=40)],
    )


class AdminTeamCreateForm(LocalizedForm):
    name = StringField(
        lazy_gettext('Teamname'),
        validators=[InputRequired(), Length(max=120)],
    )
    captain_screen_name = StringField(
        lazy_gettext('Teamkapitän (Anzeigename)'),
        validators=[InputRequired(), Length(min=3, max=40)],
    )
    logo_file = FileField(
        lazy_gettext('Team-Logo-Datei'),
        validators=[Optional()],
    )


class AdminTeamMemberAddForm(LocalizedForm):
    screen_name = StringField(
        lazy_gettext('Anzeigename'),
        validators=[InputRequired(), Length(min=3, max=40)],
    )


class ParticipantStatusForm(LocalizedForm):
    status = SelectField(
        lazy_gettext('Status'),
        validators=[InputRequired()],
        choices=[
            (status.value, lazy_enum_label(status))
            for status in ADMIN_SETTABLE_PARTICIPANT_STATUSES
        ],
    )


class ParticipantSeedForm(LocalizedForm):
    seed = IntegerField(
        lazy_gettext('Setzplatz'),
        validators=[InputRequired(), NumberRange(min=1, max=2048)],
    )


class MatchResultForm(LocalizedForm):
    slot_1_points = IntegerField(
        lazy_gettext('Punkte Slot 1'),
        validators=[InputRequired(), NumberRange(min=0, max=999)],
    )
    slot_2_points = IntegerField(
        lazy_gettext('Punkte Slot 2'),
        validators=[InputRequired(), NumberRange(min=0, max=999)],
    )
    idempotency_key = StringField(
        lazy_gettext('Idempotenz-Schlüssel'),
        validators=[Optional(), Length(min=8, max=120)],
    )
    comment = StringField(
        lazy_gettext('Kommentar'),
        validators=[Optional(), Length(max=500)],
    )


class MatchScoreReportForm(LocalizedForm):
    slot_1_points = IntegerField(
        lazy_gettext('Punkte Team 1'),
        validators=[InputRequired(), NumberRange(min=0, max=999)],
    )
    slot_2_points = IntegerField(
        lazy_gettext('Punkte Team 2'),
        validators=[InputRequired(), NumberRange(min=0, max=999)],
    )
    idempotency_key = StringField(
        lazy_gettext('Idempotenz-Schlüssel'),
        validators=[Optional(), Length(min=8, max=120)],
    )
    comment = StringField(
        lazy_gettext('Kommentar'),
        validators=[Optional(), Length(max=500)],
    )


class MatchChatMessageForm(LocalizedForm):
    body = StringField(
        lazy_gettext('Nachricht'),
        validators=[InputRequired(), Length(min=1, max=2000)],
    )


class MatchScheduleForm(LocalizedForm):
    scheduled_at = DateTimeLocalField(
        lazy_gettext('Geplant für'),
        validators=[InputRequired()],
    )
    comment = StringField(
        lazy_gettext('Kommentar'),
        validators=[InputRequired(), Length(max=500)],
    )


class MatchDisputeForm(LocalizedForm):
    reason_code = SelectField(
        lazy_gettext('Begründungscode'),
        validators=[InputRequired()],
        choices=MATCH_DISPUTE_REASON_CODE_CHOICES,
    )
    comment = StringField(
        lazy_gettext('Kommentar'),
        validators=[InputRequired(), Length(max=500)],
    )


class MatchWalkoverForm(LocalizedForm):
    winner_slot = IntegerField(
        lazy_gettext('Gewinner-Slot'),
        validators=[InputRequired(), NumberRange(min=1, max=64)],
    )
    idempotency_key = StringField(
        lazy_gettext('Idempotenz-Schlüssel'),
        validators=[Optional(), Length(min=8, max=120)],
    )
    comment = StringField(
        lazy_gettext('Kommentar'),
        validators=[InputRequired(), Length(max=500)],
    )


class ParticipantDisqualifyForm(LocalizedForm):
    reason_code = SelectField(
        lazy_gettext('Begründungscode'),
        validators=[InputRequired()],
        choices=PARTICIPANT_DISQUALIFY_REASON_CODE_CHOICES,
    )
    comment = StringField(
        lazy_gettext('Kommentar'),
        validators=[InputRequired(), Length(max=500)],
    )


class DiscordConfigForm(LocalizedForm):
    discord_enabled = BooleanField(lazy_gettext('Discord-Forum aktiviert'))
    forum_channel_id = StringField(
        lazy_gettext('Forum-Channel-ID'),
        validators=[Optional(), Length(max=120)],
    )
    discord_forum_image_url = SelectField(
        lazy_gettext('Discord-Forum-Bild'),
        validators=[Optional()],
        choices=[],
    )
    applied_tag_ids = StringField(
        lazy_gettext('Forum-Tag-IDs (kommagetrennt)'),
        validators=[Optional(), Length(max=500)],
    )
    event_mask = SelectMultipleField(
        lazy_gettext('Discord-Forum-Events'),
        choices=[],
        coerce=str,
    )
    discord_dm_enabled = BooleanField(
        lazy_gettext('Discord-DMs aktiviert')
    )
    discord_dm_event_mask = SelectMultipleField(
        lazy_gettext('Discord-DM-Events'),
        choices=[],
        coerce=str,
    )


class BrowserPushConfigForm(LocalizedForm):
    enabled = BooleanField(
        lazy_gettext('Browser-Benachrichtigungen aktiviert')
    )


class DiscordDmConfigForm(LocalizedForm):
    enabled = BooleanField(
        lazy_gettext('Discord-Privatbenachrichtigungen aktiviert')
    )
    application_id = StringField(
        lazy_gettext('Application ID'),
        validators=[Optional(), Length(max=120)],
    )
    bot_token = PasswordField(
        lazy_gettext('Bot Token'), validators=[Optional(), Length(max=500)]
    )
    default_event_mask = StringField(
        lazy_gettext('Standard-Ereignisse (kommagetrennt)'),
        validators=[Optional(), Length(max=500)],
    )


class TournamentNotificationSendForm(LocalizedForm):
    title = StringField(
        lazy_gettext('Titel'),
        validators=[InputRequired(), Length(max=120)],
    )
    body = TextAreaField(
        lazy_gettext('Nachricht'),
        validators=[InputRequired(), Length(max=500)],
    )
    target_url = StringField(
        lazy_gettext('Ziel-URL'),
        validators=[Optional(), Length(max=500)],
    )
