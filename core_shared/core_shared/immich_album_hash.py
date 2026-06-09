"""Shared Immich album version-hash computation.

Used by both the Immich worker (album sync, ITER11-004) and the backend
(on-demand album creation, ITER11-006) so the two paths produce identical
``sync_metadata.version_hash`` values for the same album state — a created
album hashes the same way a synced one would, avoiding spurious
``immich_album.updated`` churn.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable


def compute_album_version_hash(
    *,
    name: str,
    asset_count: int,
    description: str = "",
    updated_iso: str = "",
    person_ids: Iterable[str] = (),
    shared_link_url: str | None = None,
) -> str:
    """Return a SHA-256 hash of an album's mutable metadata.

    Name and description are stripped (so ``None``-equivalent empties hash
    identically), tagged person ids are sorted (order-independent), and the
    shared-link URL is folded in so a pure face-tag or share-link change still
    changes the hash. Layout: ``name|description|asset_count|updated|people|link``.

    Args:
        name: Album title.
        asset_count: Number of assets in the album.
        description: Album description (optional).
        updated_iso: Album ``updatedAt`` as ISO-8601, or ``""`` when unknown.
        person_ids: Immich person ids tagged across the album's assets.
        shared_link_url: Public shared-link URL, if any.
    """
    people_part = ",".join(sorted(person_ids))
    data = (
        f"{name.strip()}|{description.strip()}|{asset_count}|{updated_iso}"
        f"|{people_part}|{shared_link_url or ''}"
    )
    return hashlib.sha256(data.encode()).hexdigest()
