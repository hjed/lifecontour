"""The canonical form of a journal participant's email address.

Integrations report participants by email as the provider spells them. Every
place that compares one -- resolving it to a contact, recording it as
unmatched, suggesting, accepting or ignoring it -- uses this form, the same one
``SqlContactRepository.find_by_email`` compares with (``LOWER(BTRIM(value))``).
"""

MAX_PARTICIPANT_EMAIL_LENGTH = 320
"""Longest address that can be recorded (RFC 5321's 64 + 1 + 255)."""

MAX_PARTICIPANT_DISPLAY_NAME_LENGTH = 255
"""Longest reported display name kept; longer ones are truncated."""


def normalise_participant_email(email: str) -> str:
    """``email`` trimmed and lower-cased."""
    return email.strip().lower()
