"""Mention-level weak relations and canonical relationship arcs."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path


RELATION_SCHEMA_VERSION = "1.0"

IDENTITY_SIGNAL_TYPES = {
    "HAS_ALIAS",
    "HAS_TITLE",
    "HAS_FORMER_IDENTITY",
    "TRANSFORMS_INTO",
    "REVEALED_AS",
    "ADDRESSES_AS",
}

RESOLVER_CONTEXT_TYPES = {
    "CO_OCCURS_IN_SCENE",
}

SHARED_CONTEXT_RELATION_TYPES = {
    "CO_PARTICIPATES_IN_EVENT",
    "CO_PRESENT_AT_LOCATION",
    "SHARES_OR_TOUCHES_ARTIFACT_CONTEXT",
}

FINAL_CONTEXT_EVIDENCE_KINDS = {
    "shared_event",
    "shared_location",
    "shared_artifact",
}

CHARACTER_RELATION_TYPES = {
    "HAS_RELATIONSHIP",
    "COMPANION_OF",
    "CHILD_OF",
    "PARENT_OF",
    "DISCIPLE_OF",
    "FIGHTS_WITH",
    "HAS_CONFLICT_WITH",
    "OPPOSES",
    "OFFENDS",
    "ORDERS_CAPTURE_OF",
    "SEEKS_HELP_FROM",
}

EVENT_PARTICIPATION_TYPES = {"PARTICIPATES_IN"}
LOCATION_TYPES = {"LOCATED_IN", "VISITS", "EVENT_OCCURS_AT"}
ARTIFACT_TYPES = {"OWNS_ARTIFACT", "USES_ARTIFACT"}


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def stable_json_hash(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def compact(values, limit=None):
    result = []
    seen = set()
    for value in values:
        marker = stable_json_hash(value) if isinstance(value, (dict, list)) else str(value)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(value)
        if limit and len(result) >= limit:
            break
    return result


def edge_record(edge, nodes, weak_type=None, confidence=0.8, evidence_kind="explicit_edge"):
    source = nodes.get(edge.get("source"), {})
    target = nodes.get(edge.get("target"), {})
    relation_type = weak_type or edge.get("type", "RELATED")
    payload = {
        "weak_relation_type": relation_type,
        "source_mention_id": edge.get("source"),
        "target_mention_id": edge.get("target"),
        "source_type": source.get("type", ""),
        "target_type": target.get("type", ""),
        "source_surface_name": edge.get("source_surface_name") or source.get("surface_name", ""),
        "target_surface_name": edge.get("target_surface_name") or target.get("surface_name", ""),
        "source_chunk_id": edge.get("source_chunk_id"),
        "source_text": clean_text(edge.get("source_text")),
        "relation_summary": clean_text(edge.get("relation_summary")),
        "source_edge_id": edge.get("edge_id"),
        "evidence_kind": evidence_kind,
        "resolver_signal": relation_type in IDENTITY_SIGNAL_TYPES,
        "relationship_signal": (
            relation_type in CHARACTER_RELATION_TYPES
            or evidence_kind
            in FINAL_CONTEXT_EVIDENCE_KINDS
        ),
        "confidence": confidence,
    }
    payload["weak_relation_id"] = "weak_" + stable_json_hash(payload)[:20]
    return payload


def pair_record(left, right, weak_type, chunk_id, source_text, confidence, evidence_kind, anchor=None):
    payload = {
        "weak_relation_type": weak_type,
        "source_mention_id": left["node_id"],
        "target_mention_id": right["node_id"],
        "source_type": left.get("type", ""),
        "target_type": right.get("type", ""),
        "source_surface_name": left.get("surface_name", ""),
        "target_surface_name": right.get("surface_name", ""),
        "source_chunk_id": chunk_id,
        "source_text": clean_text(source_text),
        "relation_summary": clean_text(anchor or weak_type),
        "source_edge_id": "",
        "evidence_kind": evidence_kind,
        "resolver_signal": False,
        "relationship_signal": weak_type not in RESOLVER_CONTEXT_TYPES,
        "confidence": confidence,
    }
    payload["weak_relation_id"] = "weak_" + stable_json_hash(payload)[:20]
    return payload


def pairwise(nodes, limit=80):
    nodes = list(nodes)
    count = 0
    for index, left in enumerate(nodes):
        for right in nodes[index + 1 :]:
            if left["node_id"] == right["node_id"]:
                continue
            yield left, right
            count += 1
            if count >= limit:
                return


def build_mention_weak_relations(raw_graph):
    nodes = {
        node["node_id"]: node
        for chunk in raw_graph.get("results", [])
        for node in chunk.get("nodes", [])
    }
    weak_relations = []
    chunk_nodes = defaultdict(list)
    chunk_edges = defaultdict(list)
    for chunk in raw_graph.get("results", []):
        for node in chunk.get("nodes", []):
            chunk_nodes[chunk["chunk_id"]].append(node)
        for edge in chunk.get("edges", []):
            chunk_edges[chunk["chunk_id"]].append(edge)
            confidence = 0.95 if edge.get("type") in IDENTITY_SIGNAL_TYPES else 0.86
            weak_relations.append(
                edge_record(edge, nodes, confidence=confidence)
            )

    for chunk in raw_graph.get("results", []):
        cid = chunk["chunk_id"]
        text = " ".join(
            clean_text(node.get("source_text"))
            for node in chunk.get("nodes", [])
            if clean_text(node.get("source_text"))
        )
        characters = [
            node for node in chunk.get("nodes", []) if node.get("type") == "Character"
        ]
        for left, right in pairwise(characters, limit=120):
            weak_relations.append(
                pair_record(
                    left,
                    right,
                    "CO_OCCURS_IN_SCENE",
                    cid,
                    text,
                    0.35,
                    "same_scene",
                    "same chunk scene co-presence",
                )
            )

        by_event = defaultdict(list)
        by_location = defaultdict(list)
        by_artifact = defaultdict(list)
        for edge in chunk_edges[cid]:
            relation_type = edge.get("type")
            source = nodes.get(edge.get("source"), {})
            target = nodes.get(edge.get("target"), {})
            if relation_type in EVENT_PARTICIPATION_TYPES:
                if target.get("type") == "Event" and source.get("type") == "Character":
                    by_event[target["node_id"]].append(source)
            if relation_type in LOCATION_TYPES:
                if target.get("type") == "Location" and source.get("type") == "Character":
                    by_location[target["node_id"]].append(source)
                if source.get("type") == "Event" and target.get("type") == "Location":
                    by_location[target["node_id"]].append(source)
            if relation_type in ARTIFACT_TYPES:
                if target.get("type") == "Artifact" and source.get("type") == "Character":
                    by_artifact[target["node_id"]].append(source)

        for event_id, participants in by_event.items():
            event = nodes.get(event_id, {})
            for left, right in pairwise(participants, limit=80):
                weak_relations.append(
                    pair_record(
                        left,
                        right,
                        "CO_PARTICIPATES_IN_EVENT",
                        cid,
                        event.get("source_text", ""),
                        0.7,
                        "shared_event",
                        event.get("surface_name", ""),
                    )
                )
        for location_id, participants in by_location.items():
            chars = [item for item in participants if item.get("type") == "Character"]
            location = nodes.get(location_id, {})
            for left, right in pairwise(chars, limit=80):
                weak_relations.append(
                    pair_record(
                        left,
                        right,
                        "CO_PRESENT_AT_LOCATION",
                        cid,
                        location.get("source_text", ""),
                        0.62,
                        "shared_location",
                        location.get("surface_name", ""),
                    )
                )
        for artifact_id, participants in by_artifact.items():
            artifact = nodes.get(artifact_id, {})
            for left, right in pairwise(participants, limit=50):
                weak_relations.append(
                    pair_record(
                        left,
                        right,
                        "SHARES_OR_TOUCHES_ARTIFACT_CONTEXT",
                        cid,
                        artifact.get("source_text", ""),
                        0.58,
                        "shared_artifact",
                        artifact.get("surface_name", ""),
                    )
                )

    weak_relations = compact(weak_relations)
    output = {
        "schema_version": RELATION_SCHEMA_VERSION,
        "step": "10a",
        "purpose": (
            "Mention-level weak relations extracted before canonical entity "
            "resolution. These are resolver evidence only, not final character relationships."
        ),
        "source_graph_fingerprint": stable_json_hash(raw_graph.get("results", [])),
        "source_chunk_count": raw_graph.get("completed_chunk_count"),
        "weak_relation_count": len(weak_relations),
        "weak_relations": weak_relations,
        "policy": {
            "pre_canonical": True,
            "do_not_treat_as_final_relationship": True,
            "entity_resolution_uses_as_evidence": True,
        },
        "validation": {
            "weak_relation_type_counts": dict(
                Counter(item["weak_relation_type"] for item in weak_relations)
            ),
            "evidence_kind_counts": dict(
                Counter(item["evidence_kind"] for item in weak_relations)
            ),
        },
    }
    output["mention_weak_relation_fingerprint"] = stable_json_hash(
        {
            "weak_relations": weak_relations,
            "source_graph_fingerprint": output["source_graph_fingerprint"],
        }
    )
    return output


def attach_weak_relations_to_mention_index(index, weak_db, per_mention_limit=30):
    index = json.loads(json.dumps(index, ensure_ascii=False))
    by_mention = defaultdict(list)
    for relation in weak_db.get("weak_relations", []):
        for role, mention_key in (
            ("source", relation.get("source_mention_id")),
            ("target", relation.get("target_mention_id")),
        ):
            if not mention_key:
                continue
            by_mention[mention_key].append(
                {
                    "edge_id": relation["weak_relation_id"],
                    "edge_type": "WEAK_" + relation["weak_relation_type"],
                    "role": role,
                    "other_node_id": (
                        relation.get("target_mention_id")
                        if role == "source"
                        else relation.get("source_mention_id")
                    ),
                    "other_type": (
                        relation.get("target_type")
                        if role == "source"
                        else relation.get("source_type")
                    ),
                    "other_surface_name": (
                        relation.get("target_surface_name")
                        if role == "source"
                        else relation.get("source_surface_name")
                    ),
                    "source_chunk_id": relation.get("source_chunk_id"),
                    "source_text": relation.get("source_text"),
                    "weak_relation": True,
                    "evidence_kind": relation.get("evidence_kind"),
                    "confidence": relation.get("confidence"),
                }
            )
    for mention_id, contexts in by_mention.items():
        if mention_id not in index.get("mentions", {}):
            continue
        existing = index["mentions"][mention_id].setdefault("contexts", [])
        existing.extend(
            sorted(
                contexts,
                key=lambda item: (
                    str(item.get("source_chunk_id")),
                    item.get("edge_type", ""),
                    item.get("other_node_id", ""),
                ),
            )[:per_mention_limit]
        )
    index["mention_weak_relation_fingerprint"] = weak_db.get(
        "mention_weak_relation_fingerprint"
    )
    index["weak_relation_count"] = weak_db.get("weak_relation_count", 0)
    index["index_fingerprint"] = stable_json_hash(
        {
            "mentions": index["mentions"],
            "surface_groups": index["surface_groups"],
            "identity_links": index["identity_links"],
            "mention_weak_relation_fingerprint": index.get(
                "mention_weak_relation_fingerprint"
            ),
        }
    )
    return index


def normalize_weak_relations(weak_db, canonical_entities):
    node_map = canonical_entities.get("node_id_to_entity_id", {})
    canonical_by_id = {
        item["entity_id"]: item
        for item in canonical_entities.get("canonical_entities", [])
        + canonical_entities.get("reference_entities", [])
    }
    grouped = {}
    unresolved = []
    for relation in weak_db.get("weak_relations", []):
        source_entity_id = node_map.get(relation.get("source_mention_id"))
        target_entity_id = node_map.get(relation.get("target_mention_id"))
        if not source_entity_id or not target_entity_id:
            unresolved.append(relation)
            continue
        if source_entity_id == target_entity_id and not relation.get("resolver_signal"):
            continue
        key = (
            source_entity_id,
            target_entity_id,
            relation["weak_relation_type"],
        )
        reverse_key = (
            target_entity_id,
            source_entity_id,
            relation["weak_relation_type"],
        )
        if reverse_key in grouped and relation["weak_relation_type"].startswith("CO_"):
            key = reverse_key
        record = grouped.setdefault(
            key,
            {
                "canonical_relationship_id": "canon_rel_"
                + stable_json_hash(key)[:18],
                "source_entity_id": key[0],
                "target_entity_id": key[1],
                "relationship_type": key[2],
                "source_name": canonical_by_id.get(key[0], {}).get(
                    "canonical_name", key[0]
                ),
                "target_name": canonical_by_id.get(key[1], {}).get(
                    "canonical_name", key[1]
                ),
                "source_entity_type": canonical_by_id.get(key[0], {}).get(
                    "entity_type", ""
                ),
                "target_entity_type": canonical_by_id.get(key[1], {}).get(
                    "entity_type", ""
                ),
                "evidence": [],
                "source_chunk_ids": [],
                "confidence": 0.0,
                "final_relationship": False,
            },
        )
        record["evidence"].append(relation)
        record["source_chunk_ids"].append(relation.get("source_chunk_id"))
        record["confidence"] = max(record["confidence"], relation.get("confidence", 0))
        if (
            record["source_entity_type"] == "Character"
            and record["target_entity_type"] == "Character"
            and (
                relation["weak_relation_type"] in CHARACTER_RELATION_TYPES
                or relation.get("evidence_kind")
                in FINAL_CONTEXT_EVIDENCE_KINDS
            )
        ):
            record["final_relationship"] = True
    relationships = []
    for record in grouped.values():
        record["evidence"] = compact(record["evidence"], 24)
        record["source_chunk_ids"] = sorted(
            {str(item) for item in record["source_chunk_ids"] if item is not None}
        )
        record["arc_strength"] = (
            "explicit"
            if record["relationship_type"] in CHARACTER_RELATION_TYPES
            else "shared_context"
            if record["relationship_type"] in SHARED_CONTEXT_RELATION_TYPES
            else "weak_context"
        )
        record["runtime_use"] = (
            "relationship_seed"
            if record["final_relationship"]
            else "resolver_or_retrieval_context"
        )
        relationships.append(record)
    relationships.sort(
        key=lambda item: (
            item["source_name"],
            item["target_name"],
            item["relationship_type"],
        )
    )
    output = {
        "schema_version": RELATION_SCHEMA_VERSION,
        "step": "12a",
        "purpose": (
            "Mention weak relations normalized after canonical entity resolution."
        ),
        "source_weak_relation_fingerprint": weak_db.get(
            "mention_weak_relation_fingerprint"
        ),
        "source_canonical_fingerprint": canonical_entities.get(
            "candidate_fingerprint"
        ),
        "relationship_count": len(relationships),
        "relationships": relationships,
        "unresolved_weak_relation_count": len(unresolved),
        "policy": {
            "canonical_after_resolution": True,
            "weak_context_is_not_identity_merge": True,
            "same_scene_is_not_final_relationship": True,
            "agent_runtime_can_track_relationship_state": True,
        },
    }
    output["canonical_relationships_fingerprint"] = stable_json_hash(
        {
            "relationships": relationships,
            "source_weak_relation_fingerprint": output[
                "source_weak_relation_fingerprint"
            ],
        }
    )
    return output


def build_relationship_arc_db(canonical_relationships):
    arcs = {}
    for relation in canonical_relationships.get("relationships", []):
        if not relation.get("final_relationship"):
            continue
        participants = sorted(
            [relation["source_entity_id"], relation["target_entity_id"]]
        )
        key = tuple(participants)
        arc = arcs.setdefault(
            key,
            {
                "relationship_arc_id": "arc_" + stable_json_hash(key)[:18],
                "participant_ids": participants,
                "participant_names": sorted(
                    [relation["source_name"], relation["target_name"]]
                ),
                "current_status": "established_from_canonical_evidence",
                "arc_events": [],
                "agent_tracking_policy": {
                    "visible_to_participants_only_unless_witnessed": True,
                    "changes_require_runtime_event": True,
                    "do_not_assume_final_relationship": True,
                },
            },
        )
        for evidence in relation.get("evidence", []):
            arc["arc_events"].append(
                {
                    "relationship_type": relation["relationship_type"],
                    "source_chunk_id": evidence.get("source_chunk_id"),
                    "source_text": evidence.get("source_text"),
                    "relation_summary": evidence.get("relation_summary"),
                    "confidence": evidence.get("confidence"),
                    "evidence_kind": evidence.get("evidence_kind"),
                }
            )
    for arc in arcs.values():
        arc["arc_events"].sort(
            key=lambda item: (
                str(item.get("source_chunk_id")),
                item.get("relationship_type", ""),
                item.get("source_text", ""),
            )
        )
    output = {
        "schema_version": RELATION_SCHEMA_VERSION,
        "layer": "Relationship Arc DB",
        "purpose": "Canonical relationship arcs for agent social memory and runtime updates.",
        "source_canonical_relationships_fingerprint": canonical_relationships.get(
            "canonical_relationships_fingerprint"
        ),
        "relationship_arc_count": len(arcs),
        "relationship_arcs": list(arcs.values()),
        "policy": {
            "built_after_entity_resolution": True,
            "weak_mentions_are_evidence_not_final_truth": True,
            "runtime_relationship_changes_are_event_sourced": True,
        },
    }
    output["relationship_arc_db_fingerprint"] = stable_json_hash(
        output["relationship_arcs"]
    )
    return output


def write_relationship_files(base_dir, weak_db=None, canonical_db=None, arc_db=None):
    base_dir = Path(base_dir)
    written = {}
    if weak_db is not None:
        path = base_dir / "graph" / "mention_weak_relations.json"
        atomic_write_json(path, weak_db)
        written["mention_weak_relations"] = str(path)
    if canonical_db is not None:
        path = base_dir / "canonical" / "canonical_relationship_db.json"
        atomic_write_json(path, canonical_db)
        written["canonical_relationship_db"] = str(path)
    if arc_db is not None:
        path = base_dir / "canonical" / "relationship_arc_db.json"
        atomic_write_json(path, arc_db)
        written["relationship_arc_db"] = str(path)
    return written
