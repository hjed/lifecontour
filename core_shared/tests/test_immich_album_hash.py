"""Unit tests for the shared Immich album version-hash helper."""

from __future__ import annotations

import hashlib

from core_shared.immich_album_hash import compute_album_version_hash


def test_known_layout() -> None:
    """Layout is name|description|asset_count|updated|people|link."""
    expected = hashlib.sha256(b"Trip||2|||").hexdigest()
    assert compute_album_version_hash(name="Trip", asset_count=2) == expected


def test_person_ids_order_independent() -> None:
    assert compute_album_version_hash(
        name="Trip", asset_count=2, person_ids=["p2", "p1"]
    ) == compute_album_version_hash(name="Trip", asset_count=2, person_ids=["p1", "p2"])


def test_name_and_description_stripped() -> None:
    assert compute_album_version_hash(
        name=" Trip ", asset_count=2, description=" d "
    ) == compute_album_version_hash(name="Trip", asset_count=2, description="d")


def test_each_field_changes_the_hash() -> None:
    base = compute_album_version_hash(name="Trip", asset_count=2)
    assert base != compute_album_version_hash(name="Other", asset_count=2)
    assert base != compute_album_version_hash(name="Trip", asset_count=3)
    assert base != compute_album_version_hash(
        name="Trip", asset_count=2, description="d"
    )
    assert base != compute_album_version_hash(
        name="Trip", asset_count=2, updated_iso="2026-01-15T00:00:00+00:00"
    )
    assert base != compute_album_version_hash(
        name="Trip", asset_count=2, person_ids=["p1"]
    )
    assert base != compute_album_version_hash(
        name="Trip", asset_count=2, shared_link_url="https://immich/share/k"
    )


def test_backend_creation_matches_worker_layout_for_equivalent_album() -> None:
    """Backend creation (no description/updated/people) hashes the same as a
    worker would for an album with the same name + count."""
    backend = compute_album_version_hash(name="Trip", asset_count=2)
    worker_equivalent = compute_album_version_hash(
        name="Trip",
        description="",
        asset_count=2,
        updated_iso="",
        person_ids=[],
        shared_link_url=None,
    )
    assert backend == worker_equivalent
