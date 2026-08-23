"""Apply an activity template to a journal's ``type_data`` on creation.

Selecting a template does more than record which canyon, cave or climb the
journal is about: the template's standard pitches become the journal's pitches
(and, through ``AbseilingService``, its abseil counts), and the template's
type-specific fields (french grade, cave orientation, climbing grade, …) seed
the matching type block. The web create form has always done this client-side; this module
is the server-side equivalent so the MCP create tool can accept a plain
``template_id`` instead of asking the caller to copy everything by hand.

The functions here are pure — no repository access, no transaction — so the
rules can be unit tested without a database. Loading the template (and checking
it belongs to the caller) stays with the caller.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from core_shared.models.journals.activity_template import ActivityTemplate
from core_shared.models.journals.exceptions import JournalValidationError
from core_shared.models.journals.journal_types import JournalType
from core_shared.models.journals.template_pitch import TemplatePitch

from app.core.journal.services.journal_write_service import expand_type_dependencies

# Pitch attributes copied from the template onto the journal. ``id`` and
# ``template_id`` are deliberately excluded: the journal gets its own editable
# copies, not a view onto the template's rows.
_PITCH_FIELDS = (
    "pitch_number",
    "height",
    "anchor_location",
    "anchor_type",
    "did_rescue",
    "did_setup",
    "notes",
    "pitch_type",
)

_JOURNAL_TYPE_NAMES = {journal_type.name for journal_type in JournalType}

# Fields the template's own type contributes, and the type block they land on.
# Mirrors ``templateUtils.ts`` in the frontend.
_TEMPLATE_TYPE_BLOCKS: dict[str, JournalType] = {
    "canyoning": JournalType.CANYONING,
    "caving": JournalType.CAVING,
    "climbing": JournalType.CLIMBING,
}


def apply_template_to_type_data(
    template: ActivityTemplate,
    journal_types: Iterable[str],
    type_data: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Merge ``template``'s contributions into ``type_data`` and return the result.

    ``journal_types`` are the type names requested for the journal; their
    dependency closure is taken here, so ``["CANYONING"]`` counts as carrying
    ABSEILING_TRIP. Only types the journal actually has are seeded, which is why
    a climbing template on a canyoning journal contributes its pitches and its
    reference but no climbing fields.

    Anything the caller already put in ``type_data`` wins field by field, so
    caller-supplied ``pitches`` keep the template's out. The input mapping is
    left untouched.

    Raises:
        JournalValidationError: if the journal carries no abseiling-derived
            type, since the template reference has nowhere to live.
    """
    expanded = expand_type_dependencies(
        {
            JournalType[name.upper()]
            for name in journal_types
            if name.upper() in _JOURNAL_TYPE_NAMES
        }
    )
    if JournalType.ABSEILING_TRIP not in expanded:
        raise JournalValidationError(
            "template_id",
            "A template can only be applied to an abseiling-derived journal. "
            "Include one of ABSEILING_TRIP, CANYONING, CLIMBING or CAVING in types.",
        )

    merged = {key: dict(value) for key, value in (type_data or {}).items()}
    for type_name, seeded in _build_seed(template, expanded, merged).items():
        existing_key = _matching_key(merged, type_name)
        if existing_key is None:
            merged[type_name] = seeded
        else:
            merged[existing_key] = {**seeded, **merged[existing_key]}
    return merged


def _build_seed(
    template: ActivityTemplate,
    journal_types: set[JournalType],
    type_data: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build the type-data blocks the template contributes, keyed by type name."""
    seed: dict[str, dict[str, Any]] = {
        JournalType.ABSEILING_TRIP.name: _abseiling_block(template, type_data)
    }

    block_type = _TEMPLATE_TYPE_BLOCKS.get(template.template_type)
    if block_type is not None and block_type in journal_types:
        fields = _type_specific_fields(template)
        if fields:
            seed[block_type.name] = fields
    return seed


def _abseiling_block(
    template: ActivityTemplate, type_data: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """The consolidated abseiling block: the reference plus the pitch data.

    The abseil counts are deliberately not seeded here. ``AbseilingService``
    already derives them from whichever pitches the journal ends up with, so
    computing them a second time would only give the two answers a chance to
    disagree.
    """
    block: dict[str, Any] = {"template_id": str(template.id)}

    caller_key = _matching_key(type_data, JournalType.ABSEILING_TRIP.name)
    caller_supplied_pitches = (
        caller_key is not None and "pitches" in type_data[caller_key]
    )
    if not template.pitches or caller_supplied_pitches:
        return block

    pitches = sorted(template.pitches, key=lambda pitch: pitch.pitch_number)
    block["pitches"] = [_pitch_fields(pitch) for pitch in pitches]
    return block


def _type_specific_fields(template: ActivityTemplate) -> dict[str, Any]:
    """The fields a template of this type contributes to its own type block."""
    if template.template_type == "canyoning":
        return _canyoning_fields(template)
    if template.template_type == "caving":
        return _caving_fields(template)
    if template.template_type == "climbing":
        return _climbing_fields(template)
    return {}


def _canyoning_fields(template: ActivityTemplate) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if template.french_grade:
        fields["french_grade"] = template.french_grade
    if template.water_gauge_name:
        # The journal column carries the historical spelling.
        fields["water_guage_name"] = template.water_gauge_name
    # A template records vertical-ness as canyon_type. Only an outright
    # vertical canyon implies the flag — a mixed canyon is left to the user,
    # since it can still have significant vertical sections.
    if template.canyon_type == "vertical":
        fields["is_vertical"] = True
    return fields


def _caving_fields(template: ActivityTemplate) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if template.is_vertical is not None:
        fields["is_vertical"] = template.is_vertical
    if template.is_horizontal is not None:
        fields["is_horizontal"] = template.is_horizontal
    return fields


def _climbing_fields(template: ActivityTemplate) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if template.climbing_type:
        fields["climbing_type"] = template.climbing_type
    if template.grade is not None:
        fields["grade"] = template.grade
    if template.length is not None:
        fields["length"] = template.length
    return fields


def _pitch_fields(pitch: TemplatePitch) -> dict[str, Any]:
    return {field: getattr(pitch, field) for field in _PITCH_FIELDS}


def _matching_key(type_data: Mapping[str, Any], type_name: str) -> str | None:
    """Find ``type_name``'s key in ``type_data``, which may use any casing."""
    for key in type_data:
        if key.upper() == type_name:
            return key
    return None
