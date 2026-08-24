"""Turning a database rejection into something safe to hand back to a caller.

A ``DataError`` is the database refusing a value for its column — too long, out
of range, not a valid uuid — so it is a bad request rather than a server fault,
and the driver's own reason is the actionable part. Reporting it as an internal
error tells a client nothing it can fix.

The driver's text cannot be passed through as it stands. Postgres quotes the
rejected literal into the message for several of these (``invalid input syntax
for type uuid: "..."``, ``value "..." is out of range for type integer``), so
the reason carries the caller's own submitted data. That is fine in a log and
wrong in an HTTP response: these handlers are global, the value may be
somebody's personal data, and a response travels further than a log line.

So the shape of the failure is kept and everything from the first quote to the
last is redacted. What survives — "value too long for type character
varying(100)", "invalid input syntax for type uuid" — is what a client needs to
correct the call, and the full text stays in the log for whoever is debugging
it.
"""

import re

from sqlalchemy.exc import DataError

# Postgres quotes the offending value into its message, but it interpolates the
# text verbatim, so a submitted value containing a double quote produces
# unbalanced quoting: prefix"secret becomes ... "prefix"secret". Pairing the
# quotes off would redact "prefix" and hand back secret.
#
# So this spans the first quote to the last rather than matching pairs. Only
# text outside every quote survives, and Postgres always closes the value's
# quote before the rest of its message, so nothing submitted can get past it.
# The cost is a message carrying two separate quoted spans losing the words
# between them, which is worth paying to make the guarantee hold by
# construction rather than by the shape of the value.
_QUOTED_LITERAL = re.compile(r'"[\s\S]*"')

_REDACTED = '"..."'

_FALLBACK = "The database rejected a value for its column"


def describe_data_error(error: DataError) -> str:
    """The driver's reason for refusing a value, with any literal redacted.

    Only the first line is used: a ``DataError`` carries the whole statement and
    every bound parameter after it, which would bury the one line that says what
    was wrong and repeat the caller's data back at them.
    """
    original = getattr(error, "orig", None)
    reason = str(original) if original is not None else str(error)

    first_line = reason.strip().splitlines()[0].strip() if reason.strip() else ""
    if not first_line:
        return _FALLBACK

    return _QUOTED_LITERAL.sub(_REDACTED, first_line)
