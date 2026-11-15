"""Fail-closed merge and simulated version activation. Never writes real S3."""

from dataclasses import dataclass
import json

from memory_s3 import MemoryS3, MissingObject, PreconditionFailed
from schema import Catalog, ValidationError, canonical_bytes, digest


CURRENT_KEY = "research-catalog/current.json"
SNAPSHOT_PREFIX = "research-catalog/snapshots/"


class EmptyBatch(ValidationError):
    pass


class CatalogConflict(ValidationError):
    pass


def _fake_only(store):
    # A real SDK or compatible-looking network client cannot be passed accidentally.
    if type(store) is not MemoryS3:
        raise TypeError("Only the in-memory test double is supported; no AWS adapter exists")


def merge_catalog(existing, incoming):
    existing.validate()
    incoming.validate()
    if not incoming.passages:
        raise EmptyBatch("No passages in batch: refusing to publish")
    merged = []
    for name, key in (("documents", "document_id"), ("passages", "evidence_id"),
                      ("contexts", "context_id")):
        by_id = {getattr(row, key): row for row in getattr(existing, name)}
        for row in getattr(incoming, name):
            identity = getattr(row, key)
            if identity in by_id and by_id[identity] != row:
                raise CatalogConflict(f"Conflicting {name} metadata; explicit review required")
            by_id[identity] = row
        merged.append(tuple(by_id[k] for k in sorted(by_id)))
    result = Catalog(*merged)
    result.validate()
    return result


@dataclass(frozen=True)
class ActiveCatalog:
    catalog: Catalog
    snapshot_key: str
    snapshot_sha256: str
    pointer_etag: str
    generation: int


@dataclass(frozen=True)
class PublicationPlan:
    parent: ActiveCatalog
    merged: Catalog


def _snapshot(catalog):
    body = catalog.to_bytes()
    content_hash = digest(body)
    return SNAPSHOT_PREFIX + content_hash + ".json", content_hash, body


def _pointer(key, content_hash, generation, previous_key):
    return canonical_bytes({"schema_version": 2, "catalog_kind": "research_only",
                            "snapshot_key": key, "snapshot_sha256": content_hash,
                            "generation": generation, "previous_snapshot_key": previous_key})


def load_active(store):
    _fake_only(store)
    pointer = store.get_object(Key=CURRENT_KEY)  # Missing/unreadable is fatal, never empty.
    try:
        data = json.loads(pointer.body)
        expected = {"schema_version", "catalog_kind", "snapshot_key", "snapshot_sha256",
                    "generation", "previous_snapshot_key"}
        if (set(data) != expected or type(data["schema_version"]) is not int
                or data["schema_version"] != 2 or data["catalog_kind"] != "research_only"
                or type(data["generation"]) is not int or data["generation"] < 0):
            raise ValidationError("Invalid publication pointer")
        expected_key = SNAPSHOT_PREFIX + data["snapshot_sha256"] + ".json"
        if data["snapshot_key"] != expected_key:
            raise ValidationError("Invalid snapshot reference")
        raw = store.get_object(Key=data["snapshot_key"]).body
        if digest(raw) != data["snapshot_sha256"]:
            raise ValidationError("Snapshot digest mismatch")
        catalog = Catalog.from_bytes(raw)
        return ActiveCatalog(catalog, data["snapshot_key"], data["snapshot_sha256"],
                             pointer.etag, data["generation"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Published catalog is invalid; activation blocked") from exc


def seed_demo_store(store, existing):
    """Explicit test fixture setup, not an automatic missing-catalog recovery."""
    _fake_only(store)
    if store.snapshot():
        raise CatalogConflict("Fixture setup requires a completely empty fake store")
    existing.validate()
    if not existing.passages:
        raise EmptyBatch("Seed must contain an explicit existing evidence fixture")
    key, content_hash, body = _snapshot(existing)
    store.put_object(Key=key, Body=body, if_none_match=True)
    store.put_object(Key=CURRENT_KEY, Body=_pointer(key, content_hash, 0, None), if_none_match=True)


def prepare_publication(store, incoming):
    """Read and validate everything before the first simulated write."""
    parent = load_active(store)
    merged = merge_catalog(parent.catalog, incoming)
    return PublicationPlan(parent, merged)


def activate_plan(store, plan):
    """Publish only to MemoryS3; stage immutable data, switch pointer last via CAS.

    The compare-and-swap token prevents two partial batches losing each other's
    changes. A failed activation may leave an unreferenced snapshot, never an
    erased old snapshot or a partially readable active catalog.
    """
    _fake_only(store)
    active = load_active(store)
    if (active.pointer_etag != plan.parent.pointer_etag
            or active.snapshot_sha256 != plan.parent.snapshot_sha256):
        raise CatalogConflict("Stale plan; re-read the published catalog and merge again")
    plan.merged.validate()
    # Defense in depth: even a manually constructed plan cannot remove/alter old rows.
    if merge_catalog(active.catalog, plan.merged).to_bytes() != plan.merged.to_bytes():
        raise CatalogConflict("A publication plan cannot remove existing records")
    key, content_hash, body = _snapshot(plan.merged)
    if content_hash == active.snapshot_sha256:
        return active  # Identical nonempty reimport is idempotent, with no writes.
    try:
        stored = store.get_object(Key=key)
    except MissingObject:
        try:
            store.put_object(Key=key, Body=body, if_none_match=True)
        except PreconditionFailed:
            stored = store.get_object(Key=key)
            if stored.body != body:
                raise CatalogConflict("Snapshot key already contains different bytes")
    else:
        if stored.body != body:
            raise CatalogConflict("Snapshot key already contains different bytes")
    # Read back staged bytes before committing the only active pointer.
    staged = store.get_object(Key=key).body
    if staged != body:
        raise CatalogConflict("Staged snapshot verification failed")
    Catalog.from_bytes(staged)
    store.put_object(Key=CURRENT_KEY,
                     Body=_pointer(key, content_hash, active.generation + 1, active.snapshot_key),
                     if_match=active.pointer_etag)
    return load_active(store)


def publish_research_batch(store, incoming):
    """Simulation only. Not a KB/public-evidence publication or verification step."""
    return activate_plan(store, prepare_publication(store, incoming))
