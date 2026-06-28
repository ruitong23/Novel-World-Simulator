"""Build layered world-state databases for long-running novel simulation."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path


LAYER_SCHEMA_VERSION = "1.0"

RESOURCE_ENTITY_TYPES = {
    "Ability": "ability",
    "Artifact": "artifact",
    "TitleOrIdentity": "identity",
}

RESOURCE_RELATION_TYPES = {
    "Ability": {"USES_ABILITY"},
    "Artifact": {"OWNS_ARTIFACT", "USES_ARTIFACT"},
    "TitleOrIdentity": {
        "HAS_ALIAS",
        "HAS_TITLE",
        "HAS_FORMER_IDENTITY",
        "TRANSFORMS_INTO",
        "ADDRESSES_AS",
    },
}

RELATIONSHIP_TYPES = {
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
}

ORG_CHANGE_TYPES = {"BELONGS_TO", "GOVERNS", "AUTHORIZES", "ACTS_UNDER_ORDERS_OF"}

EXCLUSIVE_MARKERS = {
    "血脉",
    "血统",
    "专属",
    "唯一",
    "本命",
    "天赋",
    "武魂",
    "魂环",
    "魂骨",
    "体内",
    "自身",
    "变异",
    "继承",
}

TRANSFER_TYPES = {
    "OWNS_ARTIFACT",
    "HAS_TITLE",
    "HAS_ALIAS",
    "TRANSFORMS_INTO",
    "ADDRESSES_AS",
}


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


def unique(values):
    result = []
    seen = set()
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def evidence_texts(record):
    texts = []
    for item in record.get("evidence", []):
        for key in ("relation_summary", "source_text"):
            text = clean_text(item.get(key))
            if text:
                texts.append(text)
    texts.extend(clean_text(item) for item in record.get("descriptions", []))
    return unique(texts)


def source_orders(record):
    values = []
    for value in record.get("source_chunk_ids", []):
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            pass
    for item in record.get("evidence", []):
        try:
            values.append(int(item.get("source_chunk_id")))
        except (TypeError, ValueError):
            pass
    return values


def min_order(record):
    values = source_orders(record)
    return min(values) if values else None


def evidence_refs(record):
    refs = []
    for item in record.get("evidence", []):
        refs.append(
            {
                "source_chunk_id": item.get("source_chunk_id"),
                "source_text": clean_text(item.get("source_text")),
                "relation_summary": clean_text(item.get("relation_summary")),
            }
        )
    return refs


def entity_snapshot(entity):
    return {
        "entity_id": entity["entity_id"],
        "entity_type": entity["entity_type"],
        "canonical_name": entity["canonical_name"],
        "aliases": entity.get("aliases", []),
        "titles": entity.get("titles", []),
        "forms": entity.get("forms", []),
        "attributes": entity.get("attributes", {}),
        "descriptions": entity.get("descriptions", []),
        "source_chunk_ids": entity.get("source_chunk_ids", []),
        "first_seen_order": min_order(entity),
        "evidence_refs": evidence_refs(entity),
    }


def relation_snapshot(relation, entity_by_id):
    source = entity_by_id.get(relation.get("source_entity_id"), {})
    target = entity_by_id.get(relation.get("target_entity_id"), {})
    return {
        "relation_id": relation["relation_id"],
        "relation_type": relation["type"],
        "source_entity_id": relation.get("source_entity_id"),
        "source_name": source.get("canonical_name", ""),
        "source_entity_type": source.get("entity_type", ""),
        "target_entity_id": relation.get("target_entity_id"),
        "target_name": target.get("canonical_name", ""),
        "target_entity_type": target.get("entity_type", ""),
        "mention_count": relation.get("mention_count", 0),
        "source_chunk_ids": unique(
            item.get("source_chunk_id") for item in relation.get("evidence", [])
        ),
        "first_seen_order": min_order(relation),
        "evidence_refs": evidence_refs(relation),
    }


def relation_occurrences(relations, entity_by_id):
    rows = []
    for relation in relations:
        base = relation_snapshot(relation, entity_by_id)
        if relation.get("evidence"):
            for index, evidence in enumerate(relation.get("evidence", [])):
                row = dict(base)
                row["occurrence_id"] = f"{relation['relation_id']}:{index}"
                try:
                    row["order_key"] = int(evidence.get("source_chunk_id"))
                except (TypeError, ValueError):
                    row["order_key"] = base["first_seen_order"]
                row["evidence_refs"] = [
                    {
                        "source_chunk_id": evidence.get("source_chunk_id"),
                        "source_text": clean_text(evidence.get("source_text")),
                        "relation_summary": clean_text(
                            evidence.get("relation_summary")
                        ),
                    }
                ]
                rows.append(row)
        else:
            row = dict(base)
            row["occurrence_id"] = relation["relation_id"]
            row["order_key"] = base["first_seen_order"]
            rows.append(row)
    rows.sort(
        key=lambda item: (
            item["order_key"] is None,
            item["order_key"] if item["order_key"] is not None else 10**12,
            item["relation_id"],
        )
    )
    return rows


def infer_access_type(entity, related_relations):
    haystack = " ".join(
        [
            entity.get("canonical_name", ""),
            json.dumps(entity.get("attributes", {}), ensure_ascii=False),
            *evidence_texts(entity),
            *[
                text
                for relation in related_relations
                for text in evidence_texts(relation)
            ],
        ]
    )
    if any(marker in haystack for marker in EXCLUSIVE_MARKERS):
        return "exclusive"
    return "open"


def condition_record(condition_type, description, relation_ids=None, entity_ids=None, orders=None):
    payload = {
        "condition_type": condition_type,
        "description": clean_text(description),
        "required_entity_ids": unique(entity_ids or []),
        "source_relation_ids": unique(relation_ids or []),
        "source_orders": sorted(set(item for item in (orders or []) if item is not None)),
        "evaluation": "must_be_checked_at_runtime",
    }
    payload["condition_id"] = "cond_" + stable_json_hash(payload)[:16]
    return payload


def build_resource_record(entity, relations, entity_by_id):
    resource_type = RESOURCE_ENTITY_TYPES[entity["entity_type"]]
    relation_types = RESOURCE_RELATION_TYPES[entity["entity_type"]]
    related = [
        relation
        for relation in relations
        if relation["type"] in relation_types
        and (
            relation.get("target_entity_id") == entity["entity_id"]
            or relation.get("source_entity_id") == entity["entity_id"]
        )
    ]
    owners = []
    users = []
    transfer_relations = []
    for relation in related:
        source_id = relation.get("source_entity_id")
        if relation["type"] in {"OWNS_ARTIFACT", "HAS_TITLE", "HAS_ALIAS", "TRANSFORMS_INTO", "ADDRESSES_AS"}:
            owners.append(source_id)
            transfer_relations.append(relation)
        if relation["type"] in {"USES_ABILITY", "USES_ARTIFACT"}:
            users.append(source_id)
        if relation["type"] in TRANSFER_TYPES:
            transfer_relations.append(relation)
    canonical_owner_ids = unique(owners or users)
    canonical_user_ids = unique(users)
    access_type = infer_access_type(entity, related)
    first_acquisition_order = min(
        [item for relation in related for item in source_orders(relation)] or [min_order(entity) or 0]
    )
    conditions = {
        "acquisition_conditions": [],
        "loss_conditions": [],
        "use_conditions": [],
        "upgrade_conditions": [],
        "transfer_conditions": [],
    }
    if canonical_owner_ids:
        owner_names = [
            entity_by_id.get(owner_id, {}).get("canonical_name", owner_id)
            for owner_id in canonical_owner_ids
        ]
        conditions["acquisition_conditions"].append(
            condition_record(
                "source_trigger",
                "原著中通过证据事件获得或显露；模拟中必须由触发事件提交，不能按章节自动发放。"
                + " 原著拥有者/使用者：" + "、".join(owner_names),
                [item["relation_id"] for item in related],
                canonical_owner_ids,
                [first_acquisition_order],
            )
        )
    else:
        conditions["acquisition_conditions"].append(
            condition_record(
                "unknown_source",
                "原著证据未给出明确获得者；模拟中需要检索或 GM 裁定后才能获得。",
                [],
                [],
                [first_acquisition_order],
            )
        )
    if access_type == "exclusive":
        conditions["acquisition_conditions"].append(
            condition_record(
                "exclusive_restriction",
                "专属型资源：只有满足原著证据中的角色、血脉、身份、武魂或同等限制时可获得。",
                [item["relation_id"] for item in related],
                canonical_owner_ids,
                [first_acquisition_order],
            )
        )
    else:
        conditions["acquisition_conditions"].append(
            condition_record(
                "open_resource",
                "开放型资源：任何角色理论上可尝试获得，但仍必须满足地点、组织、关系、知识或事件条件。",
                [item["relation_id"] for item in related],
                [],
                [first_acquisition_order],
            )
        )
    conditions["use_conditions"].append(
        condition_record(
            "current_possession_or_mastery",
            "使用前必须在 Simulation State DB 中已经拥有、掌握、被授权或位于可接触状态。",
            [item["relation_id"] for item in related],
            canonical_owner_ids + canonical_user_ids,
            [first_acquisition_order],
        )
    )
    conditions["loss_conditions"].append(
        condition_record(
            "runtime_event_required",
            "失去、封印、遗忘、转移或损坏必须由 Runtime Event DB 中的事件提交。",
            [item["relation_id"] for item in transfer_relations],
            canonical_owner_ids,
            [first_acquisition_order],
        )
    )
    conditions["upgrade_conditions"].append(
        condition_record(
            "explicit_training_or_unlock",
            "升级必须由训练、觉醒、学习、战斗、组织授权或规则允许的触发事件提交。",
            [item["relation_id"] for item in related],
            canonical_owner_ids + canonical_user_ids,
            [first_acquisition_order],
        )
    )
    conditions["transfer_conditions"].append(
        condition_record(
            "transfer_event_required",
            "转移当前拥有者必须通过事件、授权、交易、继承、偷取或战斗结果提交，并保留原著拥有者字段。",
            [item["relation_id"] for item in transfer_relations],
            canonical_owner_ids,
            [first_acquisition_order],
        )
    )
    return {
        "resource_id": entity["entity_id"],
        "resource_type": resource_type,
        "canonical_name": entity["canonical_name"],
        "entity_id": entity["entity_id"],
        "access_type": access_type,
        "canonical_owner_ids": canonical_owner_ids,
        "canonical_user_ids": canonical_user_ids,
        "original_owner_ids": canonical_owner_ids,
        "first_acquisition_order": first_acquisition_order,
        "source_chunk_ids": entity.get("source_chunk_ids", []),
        "trigger_relation_ids": [item["relation_id"] for item in related],
        "evidence_refs": evidence_refs(entity)
        + [ref for relation in related for ref in evidence_refs(relation)],
        "conditions": conditions,
        "current_owner_policy": (
            "current_owner_ids live only in Simulation State DB and runtime branches"
        ),
        "status": "canonical_resource_definition",
    }


def build_relationship_resource(relation, entity_by_id):
    snap = relation_snapshot(relation, entity_by_id)
    participants = [relation.get("source_entity_id"), relation.get("target_entity_id")]
    order = snap["first_seen_order"]
    return {
        "resource_id": "relationship_" + relation["relation_id"],
        "resource_type": "relationship",
        "canonical_name": (
            f"{snap['source_name']}:{relation['type']}:{snap['target_name']}"
        ),
        "relation_id": relation["relation_id"],
        "relationship_type": relation["type"],
        "access_type": "exclusive",
        "canonical_participant_ids": unique(participants),
        "original_owner_ids": [],
        "first_acquisition_order": order if order is not None else 0,
        "trigger_relation_ids": [relation["relation_id"]],
        "evidence_refs": snap["evidence_refs"],
        "conditions": {
            "acquisition_conditions": [
                condition_record(
                    "relationship_event",
                    "关系必须由互动、血缘、师承、冲突、承诺或组织事件建立，不能因原著结局直接绑定。",
                    [relation["relation_id"]],
                    participants,
                    [order],
                )
            ],
            "loss_conditions": [
                condition_record(
                    "relationship_change_event",
                    "关系弱化、破裂、转敌或和解必须由运行时事件提交。",
                    [relation["relation_id"]],
                    participants,
                    [order],
                )
            ],
            "use_conditions": [
                condition_record(
                    "knowledge_and_presence",
                    "角色只能依据其当前知道且可感知的关系采取行动。",
                    [relation["relation_id"]],
                    participants,
                    [order],
                )
            ],
            "upgrade_conditions": [
                condition_record(
                    "relationship_development",
                    "关系成长需要共同经历、持续互动、组织/血缘证明或明确承诺。",
                    [relation["relation_id"]],
                    participants,
                    [order],
                )
            ],
            "transfer_conditions": [],
        },
        "current_state_policy": (
            "relationship current value lives in Simulation State DB and may diverge"
        ),
    }


def build_dependency_graph(resources):
    nodes = []
    edges = []
    for resource in resources:
        node = {
            "node_id": "dep_" + resource["resource_id"],
            "resource_id": resource["resource_id"],
            "resource_type": resource["resource_type"],
            "canonical_name": resource["canonical_name"],
            "access_type": resource.get("access_type", "open"),
            "canonical_owner_ids": resource.get("canonical_owner_ids", []),
            "original_owner_ids": resource.get("original_owner_ids", []),
            "first_acquisition_order": resource.get("first_acquisition_order"),
        }
        nodes.append(node)
        for group_name, conditions in resource.get("conditions", {}).items():
            for condition in conditions:
                condition_node_id = "dep_" + condition["condition_id"]
                nodes.append(
                    {
                        "node_id": condition_node_id,
                        "node_type": "condition",
                        "condition_type": condition["condition_type"],
                        "description": condition["description"],
                        "evaluation": condition["evaluation"],
                    }
                )
                edges.append(
                    {
                        "edge_id": "edge_" + stable_json_hash(
                            [condition_node_id, node["node_id"], group_name]
                        )[:16],
                        "source_node_id": condition_node_id,
                        "target_node_id": node["node_id"],
                        "edge_type": group_name,
                    }
                )
    deduped_nodes = {item["node_id"]: item for item in nodes}
    return {
        "schema_version": LAYER_SCHEMA_VERSION,
        "purpose": "Dependency graph for abilities, artifacts, identities and relationships.",
        "nodes": list(deduped_nodes.values()),
        "edges": edges,
        "policy": {
            "no_auto_grant_by_chapter": True,
            "all_resource_changes_require_event": True,
            "original_owner_is_not_current_owner": True,
        },
    }


def build_acquisition_system(resources):
    records = {
        resource["resource_id"]: {
            "resource_id": resource["resource_id"],
            "resource_type": resource["resource_type"],
            "canonical_name": resource["canonical_name"],
            "access_type": resource.get("access_type", "open"),
            "original_owner_ids": resource.get("original_owner_ids", []),
            "canonical_owner_ids": resource.get("canonical_owner_ids", []),
            "canonical_user_ids": resource.get("canonical_user_ids", []),
            "first_acquisition_order": resource.get("first_acquisition_order"),
            "conditions": resource.get("conditions", {}),
            "exclusive_policy": (
                "only listed or condition-equivalent actors can acquire"
                if resource.get("access_type") == "exclusive"
                else "any actor may attempt if runtime conditions are met"
            ),
            "runtime_fields": [
                "current_owner_ids",
                "current_user_ids",
                "current_holder_ids",
                "status",
                "last_updated_by_event_id",
            ],
        }
        for resource in resources
    }
    return {
        "schema_version": LAYER_SCHEMA_VERSION,
        "purpose": "Conditional acquisition/loss/use/upgrade/transfer system.",
        "resources": records,
        "evaluation_order": [
            "resolve_resource_id",
            "check_access_type",
            "check_acquisition_conditions",
            "check_current_owner_or_user",
            "check_location_organization_relationship_requirements",
            "commit_or_block_runtime_event",
        ],
        "grant_policy": "Never grant by chapter index alone; chapter/order only selects what is already in the simulation checkpoint.",
    }


def build_canonical_novel_db(world_graph, normalized, legacy_world_db=None):
    legacy_world_db = legacy_world_db or {}
    entity_by_id = {item["entity_id"]: item for item in world_graph.get("entities", [])}
    relations = world_graph.get("relations", [])
    relation_rows = relation_occurrences(relations, entity_by_id)
    resources = []
    for entity in world_graph.get("entities", []):
        if entity.get("entity_type") in RESOURCE_ENTITY_TYPES:
            resources.append(build_resource_record(entity, relations, entity_by_id))
    for relation in relations:
        source = entity_by_id.get(relation.get("source_entity_id"), {})
        target = entity_by_id.get(relation.get("target_entity_id"), {})
        if (
            relation.get("type") in RELATIONSHIP_TYPES
            and source.get("entity_type") == "Character"
            and target.get("entity_type") == "Character"
        ):
            resources.append(build_relationship_resource(relation, entity_by_id))

    character_growth_lines = {}
    for entity in world_graph.get("entities", []):
        if entity.get("entity_type") != "Character":
            continue
        character_id = entity["entity_id"]
        facts = [
            item
            for item in relation_rows
            if character_id in {item["source_entity_id"], item["target_entity_id"]}
        ]
        facts.sort(
            key=lambda item: (
                item["order_key"] is None,
                item["order_key"] if item["order_key"] is not None else 10**12,
                item["relation_id"],
            )
        )
        character_growth_lines[character_id] = {
            "character_id": character_id,
            "canonical_name": entity["canonical_name"],
            "first_seen_order": min_order(entity),
            "growth_facts": facts,
            "ability_resource_ids": unique(
                item["target_entity_id"]
                for item in facts
                if item["relation_type"] == "USES_ABILITY"
            ),
            "artifact_resource_ids": unique(
                item["target_entity_id"]
                for item in facts
                if item["relation_type"] in {"OWNS_ARTIFACT", "USES_ARTIFACT"}
            ),
            "identity_resource_ids": unique(
                item["target_entity_id"]
                for item in facts
                if item["target_entity_type"] == "TitleOrIdentity"
            ),
        }

    relationship_development_lines = [
        item
        for item in relation_rows
        if item["relation_type"] in RELATIONSHIP_TYPES
        and item["source_entity_type"] == "Character"
        and item["target_entity_type"] == "Character"
    ]

    item_flow = {
        resource["resource_id"]: {
            "resource_id": resource["resource_id"],
            "canonical_name": resource["canonical_name"],
            "access_type": resource["access_type"],
            "original_owner_ids": resource["original_owner_ids"],
            "canonical_owner_ids": resource.get("canonical_owner_ids", []),
            "canonical_user_ids": resource.get("canonical_user_ids", []),
            "flow_events": [
                item
                for item in relation_rows
                if item["target_entity_id"] == resource["resource_id"]
                and item["relation_type"] in {"OWNS_ARTIFACT", "USES_ARTIFACT"}
            ],
        }
        for resource in resources
        if resource["resource_type"] == "artifact"
    }

    ability_unlock_paths = {
        resource["resource_id"]: {
            "resource_id": resource["resource_id"],
            "canonical_name": resource["canonical_name"],
            "access_type": resource["access_type"],
            "original_owner_ids": resource["original_owner_ids"],
            "canonical_user_ids": resource.get("canonical_user_ids", []),
            "unlock_order": resource["first_acquisition_order"],
            "conditions": resource["conditions"],
            "usage_events": [
                item
                for item in relation_rows
                if item["target_entity_id"] == resource["resource_id"]
                and item["relation_type"] == "USES_ABILITY"
            ],
        }
        for resource in resources
        if resource["resource_type"] == "ability"
    }

    organization_changes = [
        item for item in relation_rows if item["relation_type"] in ORG_CHANGE_TYPES
    ]
    event_chain = []
    for event in legacy_world_db.get("event_ledger", {}).get("historical_events", []):
        orders = [
            int(value)
            for value in event.get("source_chunk_ids", [])
            if str(value).isdigit()
        ]
        event_chain.append(
            {
                "event_id": event["event_id"],
                "canonical_name": event.get("canonical_name", ""),
                "event_type": event.get("event_type", ""),
                "status": event.get("status", "unknown"),
                "order_key": min(orders) if orders else None,
                "participants": event.get("participants", []),
                "locations": event.get("locations", []),
                "preconditions": event.get("preconditions", []),
                "state_changes": event.get("state_changes", []),
                "outcomes": event.get("outcomes", []),
                "caused_by": event.get("caused_by", []),
                "source_chunk_ids": event.get("source_chunk_ids", []),
                "evidence_refs": event.get("evidence_refs", []),
            }
        )
    if not event_chain:
        for entity in world_graph.get("entities", []):
            if entity.get("entity_type") == "Event":
                event_chain.append(
                    {
                        "event_id": entity["entity_id"],
                        "canonical_name": entity["canonical_name"],
                        "event_type": (
                            entity.get("attributes", {}).get("event_subtype", ["event"])[0]
                            if entity.get("attributes", {}).get("event_subtype")
                            else "event"
                        ),
                        "status": (
                            entity.get("attributes", {}).get("event_status", ["unknown"])[0]
                            if entity.get("attributes", {}).get("event_status")
                            else "unknown"
                        ),
                        "order_key": min_order(entity),
                        "participants": [],
                        "locations": [],
                        "preconditions": [],
                        "state_changes": [],
                        "outcomes": [],
                        "caused_by": [],
                        "source_chunk_ids": entity.get("source_chunk_ids", []),
                        "evidence_refs": evidence_refs(entity),
                    }
                )
    event_chain.sort(
        key=lambda item: (
            item["order_key"] is None,
            item["order_key"] if item["order_key"] is not None else 10**12,
            item["event_id"],
        )
    )

    scene_rows = defaultdict(
        lambda: {
            "order_key": None,
            "participants": {},
            "locations": {},
            "artifacts": {},
            "abilities": {},
            "relations": [],
            "evidence_refs": [],
        }
    )

    def add_scene_name(row, bucket, entity_id, name):
        if entity_id and name:
            row[bucket][entity_id] = name

    def add_scene_evidence(row, order, source_text="", relation_summary="", tags=None):
        row["order_key"] = order
        source_text = clean_text(source_text)
        relation_summary = clean_text(relation_summary)
        if not source_text and not relation_summary:
            return
        row["evidence_refs"].append(
            {
                "source_chunk_id": order,
                "source_text": source_text,
                "relation_summary": relation_summary,
                "tags": unique(tags or [])[:12],
            }
        )

    for relation in relation_rows:
        try:
            order = int(
                relation.get("order_key")
                if relation.get("order_key") is not None
                else relation.get("first_seen_order")
            )
        except (TypeError, ValueError):
            continue
        row = scene_rows[order]
        for side in ("source", "target"):
            entity_type = relation.get(f"{side}_entity_type")
            entity_id = relation.get(f"{side}_entity_id")
            name = relation.get(f"{side}_name")
            if entity_type == "Character":
                add_scene_name(row, "participants", entity_id, name)
            elif entity_type == "Location":
                add_scene_name(row, "locations", entity_id, name)
            elif entity_type == "Artifact":
                add_scene_name(row, "artifacts", entity_id, name)
            elif entity_type == "Ability":
                add_scene_name(row, "abilities", entity_id, name)
        row["relations"].append(
            {
                "relation_id": relation.get("relation_id"),
                "relation_type": relation.get("relation_type"),
                "source_name": relation.get("source_name"),
                "target_name": relation.get("target_name"),
            }
        )
        for evidence in relation.get("evidence_refs", [])[:3]:
            add_scene_evidence(
                row,
                order,
                evidence.get("source_text"),
                evidence.get("relation_summary"),
                [
                    relation.get("relation_type", ""),
                    relation.get("source_name", ""),
                    relation.get("target_name", ""),
                ],
            )

    for entity in world_graph.get("entities", []):
        if entity.get("entity_type") not in {"Location", "Artifact", "Ability"}:
            continue
        order = min_order(entity)
        if order is None:
            continue
        row = scene_rows[order]
        bucket = {
            "Location": "locations",
            "Artifact": "artifacts",
            "Ability": "abilities",
        }[entity.get("entity_type")]
        add_scene_name(row, bucket, entity["entity_id"], entity.get("canonical_name", ""))
        for evidence in evidence_refs(entity)[:2]:
            add_scene_evidence(
                row,
                order,
                evidence.get("source_text"),
                evidence.get("relation_summary", ""),
                [entity.get("entity_type"), entity.get("canonical_name", "")],
            )

    scene_beats = []
    for order, row in sorted(scene_rows.items()):
        evidence = unique(row["evidence_refs"])[:8]
        if not evidence and not row["relations"]:
            continue
        summary_parts = []
        if row["participants"]:
            summary_parts.append("人物：" + "、".join(row["participants"].values()))
        if row["locations"]:
            summary_parts.append("地点：" + "、".join(row["locations"].values()))
        if row["artifacts"]:
            summary_parts.append("物品：" + "、".join(row["artifacts"].values()))
        if row["abilities"]:
            summary_parts.append("能力：" + "、".join(row["abilities"].values()))
        evidence_text = "；".join(
            clean_text(item.get("relation_summary"))
            or clean_text(item.get("source_text"))
            for item in evidence[:3]
            if clean_text(item.get("relation_summary"))
            or clean_text(item.get("source_text"))
        )
        if evidence_text:
            summary_parts.append(evidence_text)
        if not summary_parts:
            continue
        scene_beats.append(
            {
                "scene_beat_id": f"scene_beat_{order}",
                "canonical_name": f"剧情片段 {order}",
                "order_key": order,
                "participants": [
                    {"entity_id": key, "name": value, "role": "present_or_related"}
                    for key, value in row["participants"].items()
                ],
                "locations": [
                    {"entity_id": key, "name": value}
                    for key, value in row["locations"].items()
                ],
                "artifacts": [
                    {"entity_id": key, "name": value}
                    for key, value in row["artifacts"].items()
                ],
                "abilities": [
                    {"entity_id": key, "name": value}
                    for key, value in row["abilities"].items()
                ],
                "summary": "；".join(summary_parts)[:900],
                "relation_refs": unique(row["relations"])[:16],
                "source_chunk_ids": [str(order)],
                "evidence_refs": evidence,
                "confidence": "scene_beat_from_skeleton_evidence",
                "runtime_use": "rag_and_narrative_pressure",
                "not_a_hard_canonical_event": True,
            }
        )

    canonical_db = {
        "schema_version": LAYER_SCHEMA_VERSION,
        "layer": "Canonical Novel DB",
        "purpose": (
            "Read-only canonical trajectory for the prepared novel scope; it "
            "stores tracks, dependencies and source evidence, not final grants."
        ),
        "source_world_graph_fingerprint": world_graph.get("world_graph_fingerprint"),
        "source_normalized_graph_fingerprint": normalized.get(
            "normalized_graph_fingerprint"
        ),
        "project_scope_policy": (
            "This is canonical for the source percentage processed by preparation."
        ),
        "entity_tracks": {
            entity["entity_id"]: entity_snapshot(entity)
            for entity in world_graph.get("entities", [])
        },
        "character_growth_lines": character_growth_lines,
        "relationship_development_lines": relationship_development_lines,
        "event_chain": event_chain,
        "scene_beats": scene_beats,
        "item_flow": item_flow,
        "ability_unlock_paths": ability_unlock_paths,
        "organization_changes": organization_changes,
        "world_rules": legacy_world_db.get("rule_engine", {}).get("rules", []),
        "resources": {
            item["resource_id"]: item for item in resources
        },
        "dependency_graph": build_dependency_graph(resources),
        "acquisition_system": build_acquisition_system(resources),
        "validation": {
            "entity_count": len(world_graph.get("entities", [])),
            "relation_count": len(relations),
            "resource_count": len(resources),
            "exclusive_resource_count": sum(
                item.get("access_type") == "exclusive" for item in resources
            ),
            "open_resource_count": sum(
                item.get("access_type") == "open" for item in resources
            ),
            "event_chain_count": len(event_chain),
            "scene_beat_count": len(scene_beats),
            "relationship_line_count": len(relationship_development_lines),
            "organization_change_count": len(organization_changes),
            "relation_type_counts": dict(Counter(item["type"] for item in relations)),
        },
    }
    canonical_db["canonical_db_fingerprint"] = stable_json_hash(
        {
            key: value
            for key, value in canonical_db.items()
            if key != "canonical_db_fingerprint"
        }
    )
    return canonical_db


def cutoff_or_latest(canonical_db, cutoff_order=None):
    if cutoff_order is not None:
        return int(cutoff_order)
    orders = []
    for entity in canonical_db.get("entity_tracks", {}).values():
        if entity.get("first_seen_order") is not None:
            orders.append(entity["first_seen_order"])
    for event in canonical_db.get("event_chain", []):
        if event.get("order_key") is not None:
            orders.append(event["order_key"])
    return max(orders) if orders else 0


def resource_state_at_cutoff(resource, cutoff_order):
    first_order = resource.get("first_acquisition_order")
    if first_order is None or first_order > cutoff_order:
        return None
    current_owner_ids = list(resource.get("canonical_owner_ids", []))
    current_user_ids = list(resource.get("canonical_user_ids", []))
    return {
        "resource_id": resource["resource_id"],
        "resource_type": resource["resource_type"],
        "canonical_name": resource["canonical_name"],
        "access_type": resource.get("access_type", "open"),
        "original_owner_ids": resource.get("original_owner_ids", []),
        "canonical_owner_ids": resource.get("canonical_owner_ids", []),
        "current_owner_ids": unique(current_owner_ids),
        "current_user_ids": unique(current_user_ids or current_owner_ids),
        "current_holder_ids": unique(current_owner_ids),
        "status": "acquired_or_known_by_cutoff",
        "acquired_at_order": first_order,
        "last_updated_by_event_id": None,
        "conditions": resource.get("conditions", {}),
        "source": "simulation_state_cutoff",
    }


def build_simulation_state_db(canonical_db, cutoff_order=None, existing_world_state=None):
    cutoff_order = cutoff_or_latest(canonical_db, cutoff_order)
    entity_states = {}
    for entity_id, entity in canonical_db.get("entity_tracks", {}).items():
        first_seen = entity.get("first_seen_order")
        if first_seen is not None and first_seen <= cutoff_order:
            entity_states[entity_id] = {
                "entity_id": entity_id,
                "entity_type": entity.get("entity_type"),
                "name": entity.get("canonical_name"),
                "record_status": "known_by_cutoff",
                "first_seen_order": first_seen,
                "mutable_fields": {},
                "last_updated_by_event_id": None,
            }
    if existing_world_state:
        for entity_id, state in existing_world_state.get("entity_states", {}).items():
            if entity_id in entity_states:
                entity_states[entity_id].update(
                    {
                        key: value
                        for key, value in state.items()
                        if key not in {"entity_id", "entity_type", "name"}
                    }
                )

    resource_states = {}
    identity_states = {}
    for resource_id, resource in canonical_db.get("resources", {}).items():
        state = resource_state_at_cutoff(resource, cutoff_order)
        if not state:
            continue
        resource_states[resource_id] = state
        if resource.get("resource_type") == "identity":
            identity_states[resource_id] = state

    relationship_states = {}
    for relation in canonical_db.get("relationship_development_lines", []):
        order = relation.get("order_key")
        if order is None or order > cutoff_order:
            continue
        relation_key = "relationship_" + relation["relation_id"]
        relationship_states[relation_key] = {
            "relationship_id": relation_key,
            "relation_id": relation["relation_id"],
            "relation_type": relation["relation_type"],
            "participant_ids": unique(
                [relation["source_entity_id"], relation["target_entity_id"]]
            ),
            "status": "established_by_cutoff",
            "current_value": relation.get("relation_type"),
            "first_seen_order": order,
            "last_updated_by_event_id": None,
            "evidence_refs": relation.get("evidence_refs", []),
        }

    completed_event_ids = []
    active_event_ids = []
    future_event_ids = []
    for event in canonical_db.get("event_chain", []):
        order = event.get("order_key")
        if order is None or order > cutoff_order:
            future_event_ids.append(event["event_id"])
        elif event.get("status") in {"ongoing", "pending"}:
            active_event_ids.append(event["event_id"])
        else:
            completed_event_ids.append(event["event_id"])

    state_db = {
        "schema_version": LAYER_SCHEMA_VERSION,
        "layer": "Simulation State Template",
        "purpose": (
            "Mutable baseline produced by cutting the canonical trajectory at "
            "a chosen timepoint; contains only happened/owned/known/established state. "
            "The live save is runtime/simulation_state.json."
        ),
        "source_canonical_db_fingerprint": canonical_db.get(
            "canonical_db_fingerprint"
        ),
        "cutoff_order": cutoff_order,
        "cutoff_policy": {
            "only_include_orders_lte_cutoff": True,
            "future_events_excluded_from_state": True,
            "resource_current_owner_separate_from_original_owner": True,
            "no_auto_future_grants": True,
        },
        "current_world_state": {
            "state_revision": 0,
            "baseline_kind": "canonical_cutoff_checkpoint",
            "branch_id": "main",
            "entity_states": entity_states,
            "resource_states": resource_states,
            "identity_states": identity_states,
            "relationship_states": relationship_states,
            "completed_event_ids": completed_event_ids,
            "active_event_ids": active_event_ids,
            "future_event_ids": future_event_ids,
            "state_change_log": [],
        },
        "known_fact_policy": "Agents decide from this state and their visible memories, not from the canonical ending.",
        "available_cutoff_orders": sorted(
            set(
                item
                for entity in canonical_db.get("entity_tracks", {}).values()
                for item in [entity.get("first_seen_order")]
                if item is not None
            )
        ),
    }
    state_db["simulation_state_db_fingerprint"] = stable_json_hash(
        {
            key: value
            for key, value in state_db.items()
            if key != "simulation_state_db_fingerprint"
        }
    )
    state_db["simulation_state_template_fingerprint"] = state_db[
        "simulation_state_db_fingerprint"
    ]
    return state_db


def state_change_refs_for_event(event, canonical_db):
    event_id = event.get("event_id")
    order = event.get("order_key")
    participants = {
        item.get("entity_id") if isinstance(item, dict) else item
        for item in event.get("participants", [])
    }
    participants = {item for item in participants if item}
    state_refs = {
        "relationship_change_refs": [],
        "ability_change_refs": [],
        "item_change_refs": [],
        "identity_change_refs": [],
        "organization_change_refs": [],
        "knowledge_change_refs": [],
    }
    for relation in canonical_db.get("relationship_development_lines", []):
        if relation.get("order_key") == order or (
            participants
            and participants
            & {relation.get("source_entity_id"), relation.get("target_entity_id")}
        ):
            state_refs["relationship_change_refs"].append(relation.get("relation_id"))
    for resource_id, resource in canonical_db.get("resources", {}).items():
        if resource.get("first_acquisition_order") == order:
            key = {
                "ability": "ability_change_refs",
                "artifact": "item_change_refs",
                "identity": "identity_change_refs",
                "relationship": "relationship_change_refs",
            }.get(resource.get("resource_type"), "knowledge_change_refs")
            state_refs[key].append(resource_id)
    for change in canonical_db.get("organization_changes", []):
        if change.get("order_key") == order:
            state_refs["organization_change_refs"].append(change.get("relation_id"))
    for key, values in state_refs.items():
        state_refs[key] = unique(values)
    state_refs["event_id"] = event_id
    return state_refs


def generic_blocked_consequences(event, state_refs):
    consequences = []
    for key, label in (
        ("relationship_change_refs", "relationship changes"),
        ("ability_change_refs", "ability unlocks or upgrades"),
        ("item_change_refs", "item transfers or acquisitions"),
        ("identity_change_refs", "identity/title changes"),
        ("organization_change_refs", "organization membership/authority changes"),
        ("knowledge_change_refs", "knowledge exposure"),
    ):
        if state_refs.get(key):
            consequences.append(
                {
                    "consequence_type": key.replace("_refs", ""),
                    "description": (
                        f"Canonical {label} linked to this event are not applied "
                        "unless a runtime event independently re-establishes them."
                    ),
                    "affected_refs": state_refs[key],
                }
            )
    if not consequences:
        consequences.append(
            {
                "consequence_type": "timeline_branch",
                "description": (
                    "Blocking this canonical event leaves future dependent events "
                    "eligible only after runtime preconditions are revalidated."
                ),
                "affected_refs": [event.get("event_id")],
            }
        )
    return consequences


def alternative_hooks(event, state_refs):
    hooks = [
        {
            "hook_type": "alternative_scene",
            "description": (
                "If the canonical event is blocked, the runtime may create a new "
                "scene that satisfies equivalent state, relationship, location, "
                "knowledge, or organization conditions."
            ),
            "inherits_canonical_outcome": False,
            "required_checks": [
                "current_world_state",
                "agent_visibility",
                "dependency_graph",
                "acquisition_system",
                "relationship_runtime_state",
            ],
        }
    ]
    if event.get("participants"):
        hooks.append(
            {
                "hook_type": "participant_replacement_or_delay",
                "description": (
                    "Participants may change, arrive late, refuse, or act differently; "
                    "the event must be revalidated against runtime state."
                ),
                "canonical_participants": event.get("participants", []),
            }
        )
    if event.get("locations"):
        hooks.append(
            {
                "hook_type": "location_variant",
                "description": (
                    "A different location can host a variant only if local rules, "
                    "access, witnesses, and available objects support it."
                ),
                "canonical_locations": event.get("locations", []),
            }
        )
    if any(state_refs.get(key) for key in ("ability_change_refs", "item_change_refs")):
        hooks.append(
            {
                "hook_type": "resource_opportunity",
                "description": (
                    "Abilities or items may be obtained by another qualified actor "
                    "if that actor triggers the opportunity and passes all conditions."
                ),
                "affected_resources": unique(
                    state_refs.get("ability_change_refs", [])
                    + state_refs.get("item_change_refs", [])
                ),
            }
        )
    return hooks


def canonical_event_record(event, canonical_db):
    state_refs = state_change_refs_for_event(event, canonical_db)
    order = event.get("order_key")
    return {
        "event_id": event.get("event_id"),
        "canonical_name": event.get("canonical_name", ""),
        "event_type": event.get("event_type", "event"),
        "canonical_order": order,
        "status_in_source": event.get("status", "unknown"),
        "participants": event.get("participants", []),
        "locations": event.get("locations", []),
        "preconditions": event.get("preconditions", []),
        "trigger_conditions": event.get("preconditions", []),
        "state_changes": event.get("state_changes", []),
        "outcomes": event.get("outcomes", []),
        "caused_by": event.get("caused_by", []),
        "unlocks_next_events": [],
        "relationship_change_refs": state_refs["relationship_change_refs"],
        "ability_change_refs": state_refs["ability_change_refs"],
        "item_change_refs": state_refs["item_change_refs"],
        "identity_change_refs": state_refs["identity_change_refs"],
        "organization_change_refs": state_refs["organization_change_refs"],
        "knowledge_change_refs": state_refs["knowledge_change_refs"],
        "can_be_blocked": True,
        "can_be_altered": True,
        "blocked_consequences": generic_blocked_consequences(event, state_refs),
        "alternative_runtime_hooks": alternative_hooks(event, state_refs),
        "source_chunk_ids": event.get("source_chunk_ids", []),
        "evidence_refs": event.get("evidence_refs", []),
    }


def relationship_dimensions(relation_type, evidence_kind=""):
    dims = {
        "knows_each_other": 0,
        "familiarity": 0,
        "trust": 0,
        "respect": 0,
        "affection": 0,
        "hostility": 0,
        "authority": 0,
        "debt": 0,
        "shared_history": 0,
        "visibility": 0,
    }
    relation_type = str(relation_type or "")
    if relation_type == "CO_OCCURS_IN_SCENE" or evidence_kind == "same_scene":
        dims.update({"visibility": 1})
    elif relation_type.startswith("CO_") or evidence_kind in {
        "shared_event",
        "shared_location",
        "shared_artifact",
    }:
        dims.update({"knows_each_other": 1, "familiarity": 1, "visibility": 1})
    if relation_type in {"COMPANION_OF", "HAS_RELATIONSHIP", "SEEKS_HELP_FROM"}:
        dims.update({"trust": 1, "familiarity": 1, "shared_history": 1})
    if relation_type in {"CHILD_OF", "PARENT_OF", "DISCIPLE_OF"}:
        dims.update({"authority": 1, "trust": 1, "shared_history": 1})
    if relation_type in {"FIGHTS_WITH", "HAS_CONFLICT_WITH", "OPPOSES", "OFFENDS"}:
        dims.update({"hostility": 1, "visibility": 1})
    return dims


def build_canonical_component_dbs(canonical_db, world_db=None):
    world_db = world_db or {}
    events = [
        canonical_event_record(event, canonical_db)
        for event in canonical_db.get("event_chain", [])
    ]
    events_by_id = {event["event_id"]: event for event in events if event.get("event_id")}
    ordered_event_ids = [
        event["event_id"]
        for event in sorted(
            events,
            key=lambda item: (
                item.get("canonical_order") is None,
                item.get("canonical_order")
                if item.get("canonical_order") is not None
                else 10**12,
                item.get("event_id", ""),
            ),
        )
        if event.get("event_id")
    ]
    timeline_nodes = [
        {
            "timeline_node_id": "timeline_" + event_id,
            "canonical_order": events_by_id[event_id].get("canonical_order"),
            "event_id": event_id,
            "event_ref": {"db": "canonical_event_db", "event_id": event_id},
            "branchable": True,
            "can_be_blocked": True,
            "can_be_altered": True,
            "state_change_refs": {
                key: events_by_id[event_id].get(key, [])
                for key in (
                    "relationship_change_refs",
                    "ability_change_refs",
                    "item_change_refs",
                    "identity_change_refs",
                    "organization_change_refs",
                    "knowledge_change_refs",
                )
            },
        }
        for event_id in ordered_event_ids
    ]
    scene_beat_records = {
        item["scene_beat_id"]: item
        for item in canonical_db.get("scene_beats", [])
        if item.get("scene_beat_id")
    }
    event_orders = {
        events_by_id[event_id].get("canonical_order")
        for event_id in ordered_event_ids
        if event_id in events_by_id
    }
    prepared_orders = {
        item.get("order_key")
        for item in scene_beat_records.values()
        if item.get("order_key") is not None
    }
    sparse_threshold = max(8, min(60, len(prepared_orders) // 2))
    if len(timeline_nodes) < sparse_threshold:
        for scene_beat_id, beat in sorted(
            scene_beat_records.items(),
            key=lambda item: (item[1].get("order_key", 10**12), item[0]),
        ):
            if beat.get("order_key") in event_orders:
                continue
            timeline_nodes.append(
                {
                    "timeline_node_id": "timeline_" + scene_beat_id,
                    "canonical_order": beat.get("order_key"),
                    "event_id": scene_beat_id,
                    "event_ref": {
                        "db": "canonical_scene_beat_db",
                        "scene_beat_id": scene_beat_id,
                    },
                    "branchable": True,
                    "can_be_blocked": True,
                    "can_be_altered": True,
                    "node_kind": "scene_beat",
                    "confidence": beat.get("confidence"),
                    "not_a_hard_canonical_event": True,
                    "state_change_refs": {},
                }
            )
        timeline_nodes.sort(
            key=lambda item: (
                item.get("canonical_order") is None,
                item.get("canonical_order")
                if item.get("canonical_order") is not None
                else 10**12,
                item.get("timeline_node_id", ""),
            )
        )

    canonical_relationship_source = world_db.get("canonical_relationship_db") or world_db.get(
        "canonical_relationships_db", {}
    )
    relationship_arcs = world_db.get("relationship_arc_db", {}).get(
        "relationship_arcs", []
    )
    canonical_relationships = []
    for relation in canonical_relationship_source.get("relationships", []):
        first_order = None
        orders = []
        for evidence in relation.get("evidence", []):
            try:
                orders.append(int(evidence.get("source_chunk_id")))
            except (TypeError, ValueError):
                pass
        if orders:
            first_order = min(orders)
        dims = relationship_dimensions(
            relation.get("relationship_type"),
            (relation.get("evidence") or [{}])[0].get("evidence_kind", ""),
        )
        canonical_relationships.append(
            {
                "canonical_relationship_id": relation.get(
                    "canonical_relationship_id"
                ),
                "source_entity_id": relation.get("source_entity_id"),
                "target_entity_id": relation.get("target_entity_id"),
                "participant_ids": unique(
                    [
                        relation.get("source_entity_id"),
                        relation.get("target_entity_id"),
                    ]
                ),
                "source_name": relation.get("source_name", ""),
                "target_name": relation.get("target_name", ""),
                "relationship_type": relation.get("relationship_type", ""),
                "relationship_origin": (
                    "normalized_weak_relation"
                    if not relation.get("final_relationship")
                    else "canonical_evidence"
                ),
                "first_seen_order": first_order,
                "dimension_seed": dims,
                "evidence": relation.get("evidence", []),
                "source_chunk_ids": relation.get("source_chunk_ids", []),
                "runtime_policy": {
                    "not_final_label": True,
                    "changes_require_event": True,
                    "different_paths_can_produce_different_dimensions": True,
                },
            }
        )

    character_records = []
    for entity_id, entity in canonical_db.get("entity_tracks", {}).items():
        if entity.get("entity_type") != "Character":
            continue
        growth = canonical_db.get("character_growth_lines", {}).get(entity_id, {})
        character_records.append(
            {
                "character_id": entity_id,
                "entity_id": entity_id,
                "canonical_name": entity.get("canonical_name", ""),
                "aliases": entity.get("aliases", []),
                "titles": entity.get("titles", []),
                "forms": entity.get("forms", []),
                "first_seen_order": entity.get("first_seen_order"),
                "template_only": True,
                "growth_fact_refs": [
                    item.get("occurrence_id")
                    for item in growth.get("growth_facts", [])
                    if item.get("occurrence_id")
                ],
                "ability_resource_ids": growth.get("ability_resource_ids", []),
                "artifact_resource_ids": growth.get("artifact_resource_ids", []),
                "identity_resource_ids": growth.get("identity_resource_ids", []),
                "evidence_refs": entity.get("evidence_refs", []),
            }
        )

    def resource_db(resource_type, layer_name, purpose):
        resources = {
            resource_id: resource
            for resource_id, resource in canonical_db.get("resources", {}).items()
            if resource.get("resource_type") == resource_type
        }
        return {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": layer_name,
            "purpose": purpose,
            "resources": resources,
            "dependency_graph_refs": [
                "dep_" + resource_id for resource_id in resources
            ],
            "policy": {
                "original_owner_is_not_runtime_owner": True,
                "access_type_controls_acquisition_attempts": True,
                "all_changes_require_runtime_event": True,
            },
        }

    organization_records = {
        entity_id: entity
        for entity_id, entity in canonical_db.get("entity_tracks", {}).items()
        if entity.get("entity_type") == "Organization"
    }
    location_records = {
        entity_id: entity
        for entity_id, entity in canonical_db.get("entity_tracks", {}).items()
        if entity.get("entity_type") == "Location"
    }
    knowledge_units = world_db.get("knowledge_units", [])
    component_dbs = {
        "canonical_timeline_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical Timeline DB",
            "purpose": "Read-only default source trajectory and event references.",
            "source_canonical_db_fingerprint": canonical_db.get(
                "canonical_db_fingerprint"
            ),
            "ordered_event_ids": ordered_event_ids,
            "timeline_nodes": timeline_nodes,
            "policy": {
                "timeline_is_default_route_not_destiny": True,
                "cutoff_selects_checkpoint_only": True,
                "future_events_require_runtime_preconditions": True,
            },
        },
        "canonical_event_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical Event DB",
            "purpose": "Read-only canonical events with runtime trigger hooks.",
            "events": events_by_id,
            "event_order": ordered_event_ids,
            "policy": {
                "canonical_event_can_be_blocked": True,
                "blocked_events_do_not_apply_state_changes": True,
                "alternative_hooks_enable_branching": True,
            },
        },
        "canonical_scene_beat_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical Scene Beat DB",
            "purpose": (
                "Low-confidence skeleton-derived scene beats for RAG and "
                "narrative pressure; not hard canonical events."
            ),
            "scene_beats": scene_beat_records,
            "scene_beat_order": [
                item["scene_beat_id"]
                for item in sorted(
                    scene_beat_records.values(),
                    key=lambda beat: (
                        beat.get("order_key") is None,
                        beat.get("order_key")
                        if beat.get("order_key") is not None
                        else 10**12,
                        beat.get("scene_beat_id", ""),
                    ),
                )
            ],
            "policy": {
                "scene_beats_are_not_hard_events": True,
                "use_for_retrieval_and_pacing": True,
                "must_not_override_committed_runtime_state": True,
            },
        },
        "canonical_character_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical Character DB",
            "purpose": "Canonical character templates and growth references, not runtime state.",
            "characters": character_records,
            "character_by_id": {item["character_id"]: item for item in character_records},
            "policy": {
                "template_only": True,
                "runtime_state_lives_in_agents_runtime_agent_state_and_runtime_simulation_state": True,
            },
        },
        "canonical_relationship_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical Relationship DB",
            "purpose": "Event-evidence relationship arcs; not final relationship truth.",
            "relationships": canonical_relationships,
            "relationship_arcs": relationship_arcs,
            "policy": {
                "mention_weak_relations_are_resolver_evidence": True,
                "runtime_relationships_are_event_sourced": True,
                "relationship_dimensions_not_static_labels": True,
            },
        },
        "canonical_ability_db": resource_db(
            "ability",
            "Canonical Ability DB",
            "Ability definitions, dependency conditions and original users.",
        ),
        "canonical_item_db": resource_db(
            "artifact",
            "Canonical Item DB",
            "Item/artifact definitions, transfer conditions and original holders.",
        ),
        "canonical_organization_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical Organization DB",
            "purpose": "Canonical organizations and organization-change evidence.",
            "organizations": organization_records,
            "organization_changes": canonical_db.get("organization_changes", []),
            "policy": {"membership_changes_require_runtime_event": True},
        },
        "canonical_location_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical Location DB",
            "purpose": "Canonical locations and source event references.",
            "locations": location_records,
            "event_location_refs": [
                {
                    "event_id": event.get("event_id"),
                    "locations": event.get("locations", []),
                    "canonical_order": event.get("canonical_order"),
                }
                for event in events
            ],
        },
        "canonical_world_rule_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical World Rule DB",
            "purpose": "World rules used by runtime validation.",
            "rules": canonical_db.get("world_rules", []),
            "rule_engine": world_db.get("rule_engine", {}),
            "policy": {"rules_apply_to_runtime_even_when_plot_branches": True},
        },
        "canonical_knowledge_db": {
            "schema_version": LAYER_SCHEMA_VERSION,
            "layer": "Canonical Knowledge DB",
            "purpose": "Knowledge units and scopes; runtime visibility is separate.",
            "knowledge_units": knowledge_units,
            "knowledge_scope_system": world_db.get("knowledge_scope_system", []),
            "policy": {
                "knowledge_exists_in_canon_but_agent_visibility_requires_runtime_scope": True
            },
        },
    }
    for db in component_dbs.values():
        db["db_fingerprint"] = stable_json_hash(
            {key: value for key, value in db.items() if key != "db_fingerprint"}
        )
    return component_dbs


def build_runtime_event_db(canonical_db, simulation_state_db):
    cutoff_order = simulation_state_db.get("cutoff_order", 0)
    queue = []
    for event in canonical_db.get("event_chain", []):
        order = event.get("order_key")
        if order is None or order > cutoff_order:
            status = "waiting_trigger"
        elif event["event_id"] in simulation_state_db["current_world_state"].get(
            "active_event_ids", []
        ):
            status = "active"
        else:
            status = "completed"
        queue.append(
            {
                "runtime_event_id": "runtime_" + event["event_id"],
                "canonical_event_id": event["event_id"],
                "source_type": "canonical",
                "event_type": event.get("event_type", "canonical_event"),
                "canonical_name": event.get("canonical_name", ""),
                "status": status,
                "queue_status": status,
                "scheduled_order": order,
                "preconditions": event.get("preconditions", []),
                "trigger_conditions": event.get("preconditions", []),
                "participants": event.get("participants", []),
                "locations": event.get("locations", []),
                "state_changes": event.get("state_changes", []),
                "blocked_reason": "",
                "blocked_consequences": generic_blocked_consequences(
                    event, state_change_refs_for_event(event, canonical_db)
                ),
                "alternative_runtime_hooks": alternative_hooks(
                    event, state_change_refs_for_event(event, canonical_db)
                ),
                "committed_at_revision": None,
                "created_by": "canonical_timeline_import",
                "can_be_altered_or_blocked": True,
                "source": "canonical_event_chain",
            }
        )

    acquired = set(
        simulation_state_db.get("current_world_state", {})
        .get("resource_states", {})
        .keys()
    )
    for resource_id, resource in canonical_db.get("resources", {}).items():
        if resource_id in acquired:
            continue
        queue.append(
            {
                "runtime_event_id": "runtime_acquire_" + resource_id,
                "canonical_event_id": None,
                "source_type": "runtime_opportunity",
                "event_type": "resource_acquisition_opportunity",
                "canonical_name": resource.get("canonical_name", resource_id),
                "resource_id": resource_id,
                "status": "waiting_trigger",
                "queue_status": "waiting_trigger",
                "scheduled_order": resource.get("first_acquisition_order"),
                "preconditions": resource.get("conditions", {}).get(
                    "acquisition_conditions", []
                ),
                "trigger_conditions": resource.get("conditions", {}).get(
                    "acquisition_conditions", []
                ),
                "participants": resource.get("canonical_owner_ids", []),
                "locations": [],
                "state_changes": [],
                "blocked_reason": "",
                "blocked_consequences": [
                    {
                        "consequence_type": "resource_not_granted",
                        "description": (
                            "The resource remains unowned or with its current runtime "
                            "holder until another valid acquisition event commits."
                        ),
                        "affected_refs": [resource_id],
                    }
                ],
                "alternative_runtime_hooks": [
                    {
                        "hook_type": "alternate_acquisition_path",
                        "description": (
                            "Any qualified actor may attempt this resource if the "
                            "dependency and acquisition conditions pass."
                        ),
                        "access_type": resource.get("access_type", "open"),
                    }
                ],
                "committed_at_revision": None,
                "created_by": "acquisition_system",
                "can_be_altered_or_blocked": True,
                "source": "acquisition_system",
            }
        )

    runtime_db = {
        "schema_version": LAYER_SCHEMA_VERSION,
        "layer": "Runtime Event DB",
        "purpose": (
            "Future, active, completed and blocked event queue. Canonical events "
            "are pressure/defaults, not forced chapter scripts."
        ),
        "source_canonical_db_fingerprint": canonical_db.get(
            "canonical_db_fingerprint"
        ),
        "source_simulation_state_db_fingerprint": simulation_state_db.get(
            "simulation_state_db_fingerprint"
        ),
        "cutoff_order": cutoff_order,
        "event_queue": queue,
        "completed_event_ids": [
            item["runtime_event_id"]
            for item in queue
            if item["queue_status"] == "completed"
        ],
        "waiting_trigger_event_ids": [
            item["runtime_event_id"]
            for item in queue
            if item["queue_status"] == "waiting_trigger"
        ],
        "active_event_ids": [
            item["runtime_event_id"] for item in queue if item["queue_status"] == "active"
        ],
        "blocked_event_ids": [],
        "queue_policy": {
            "canonical_event_may_be_prevented": True,
            "agent_decisions_use_current_state": True,
            "events_commit_atomically": True,
            "resource_changes_require_conditions": True,
        },
    }
    runtime_db["runtime_event_db_fingerprint"] = stable_json_hash(
        {
            key: value
            for key, value in runtime_db.items()
            if key != "runtime_event_db_fingerprint"
        }
    )
    return runtime_db


def build_runtime_relationship_db(simulation_state_db, canonical_relationship_db=None):
    canonical_relationship_db = canonical_relationship_db or {}
    current = simulation_state_db.get("current_world_state", {})
    relationships = {}
    canonical_by_pair = {}
    for relation in canonical_relationship_db.get("relationships", []):
        pair = tuple(sorted(relation.get("participant_ids", [])))
        canonical_by_pair.setdefault(pair, []).append(relation)
    for rel_id, state in current.get("relationship_states", {}).items():
        pair = tuple(sorted(state.get("participant_ids", [])))
        seeds = canonical_by_pair.get(pair, [])
        dims = {
            "knows_each_other": 1,
            "familiarity": 1,
            "trust": 0,
            "respect": 0,
            "affection": 0,
            "hostility": 0,
            "authority": 0,
            "debt": 0,
            "shared_history": 1,
            "visibility": 1,
        }
        for seed in seeds:
            for key, value in seed.get("dimension_seed", {}).items():
                dims[key] = max(dims.get(key, 0), value)
        relationships[rel_id] = {
            "runtime_relationship_id": rel_id,
            "canonical_relation_id": state.get("relation_id"),
            "participant_ids": state.get("participant_ids", []),
            "current_dimensions": dims,
            "current_labels": [state.get("current_value", "")],
            "status": state.get("status", "established_by_cutoff"),
            "visible_to_agent_ids": [],
            "source_event_ids": [],
            "last_updated_by_event_id": state.get("last_updated_by_event_id"),
            "policy": {
                "labels_are_derived_from_dimensions": True,
                "changes_require_runtime_event": True,
                "different_runtime_paths_can_diverge_from_canon": True,
            },
            "evidence_refs": state.get("evidence_refs", []),
        }
    output = {
        "schema_version": LAYER_SCHEMA_VERSION,
        "layer": "Runtime Relationship DB",
        "purpose": "Current relationship truth for the live simulation.",
        "source_simulation_state_template_fingerprint": simulation_state_db.get(
            "simulation_state_template_fingerprint"
        ),
        "relationships": relationships,
        "change_log": [],
        "policy": {
            "not_derived_from_final_canon": True,
            "event_sourced": True,
            "agent_visibility_can_differ": True,
        },
    }
    output["runtime_relationship_db_fingerprint"] = stable_json_hash(
        {key: value for key, value in output.items() if key != "runtime_relationship_db_fingerprint"}
    )
    return output


def build_runtime_agent_state(agent_profiles, simulation_state_db, runtime_relationship_db=None):
    runtime_relationship_db = runtime_relationship_db or {}
    current = simulation_state_db.get("current_world_state", {})
    agent_states = {}
    for profile in agent_profiles.get("agents", []):
        agent_id = profile.get("agent_id")
        character_id = profile.get("character_id")
        if not agent_id or not character_id:
            continue
        entity_state = current.get("entity_states", {}).get(character_id, {})
        known_relationship_ids = [
            rel_id
            for rel_id, relation in runtime_relationship_db.get(
                "relationships", {}
            ).items()
            if character_id in relation.get("participant_ids", [])
        ]
        agent_states[agent_id] = {
            "agent_id": agent_id,
            "character_id": character_id,
            "canonical_profile_fingerprint": profile.get("profile_fingerprint"),
            "runtime_status": entity_state.get("record_status", "unknown_at_cutoff"),
            "current_location": entity_state.get("mutable_fields", {}).get(
                "current_location"
            ),
            "known_resource_ids": [
                resource_id
                for resource_id, resource in current.get(
                    "resource_states", {}
                ).items()
                if character_id
                in set(
                    resource.get("current_owner_ids", [])
                    + resource.get("current_user_ids", [])
                    + resource.get("current_holder_ids", [])
                )
            ],
            "known_relationship_ids": known_relationship_ids,
            "knowledge_scope": profile.get("state", {}).get("knowledge_scope", []),
            "short_term_memory": [],
            "long_term_memory_refs": [],
            "current_goals": profile.get("state", {}).get("goals", []),
            "last_updated_by_event_id": None,
            "policy": {
                "profile_is_template": True,
                "runtime_truth_lives_here_and_in_simulation_state": True,
                "agent_decisions_must_use_current_state": True,
            },
        }
    output = {
        "schema_version": LAYER_SCHEMA_VERSION,
        "layer": "Runtime Agent State",
        "purpose": "Dynamic agent state separated from canonical profile templates.",
        "source_agent_profile_db_fingerprint": agent_profiles.get(
            "agent_profile_db_fingerprint"
        ),
        "source_simulation_state_template_fingerprint": simulation_state_db.get(
            "simulation_state_template_fingerprint"
        ),
        "agent_states": agent_states,
        "policy": {
            "do_not_modify_agent_profiles_during_simulation": True,
            "runtime_agent_state_is_mutable": True,
        },
    }
    output["runtime_agent_state_fingerprint"] = stable_json_hash(
        {key: value for key, value in output.items() if key != "runtime_agent_state_fingerprint"}
    )
    return output


def build_runtime_log(simulation_state_db, runtime_event_db=None):
    runtime_event_db = runtime_event_db or {}
    output = {
        "schema_version": LAYER_SCHEMA_VERSION,
        "layer": "Runtime Log",
        "purpose": "Event-sourcing ledger for simulation branches.",
        "source_simulation_state_template_fingerprint": simulation_state_db.get(
            "simulation_state_template_fingerprint"
        ),
        "entries": [
            {
                "log_id": "log_initial_checkpoint",
                "entry_type": "initial_checkpoint",
                "cutoff_order": simulation_state_db.get("cutoff_order", 0),
                "state_revision": 0,
                "description": "Runtime initialized from canonical cutoff template.",
            }
        ],
        "runtime_event_db_fingerprint": runtime_event_db.get(
            "runtime_event_db_fingerprint"
        ),
    }
    output["runtime_log_fingerprint"] = stable_json_hash(
        {key: value for key, value in output.items() if key != "runtime_log_fingerprint"}
    )
    return output


def enhance_world_db_with_state_layers(world_db, world_graph, normalized, cutoff_order=None):
    canonical_db = build_canonical_novel_db(world_graph, normalized, world_db)
    component_dbs = build_canonical_component_dbs(canonical_db, world_db)
    simulation_state_db = build_simulation_state_db(
        canonical_db,
        cutoff_order=cutoff_order,
        existing_world_state=world_db.get("world_state"),
    )
    runtime_event_db = build_runtime_event_db(canonical_db, simulation_state_db)
    runtime_relationship_db = build_runtime_relationship_db(
        simulation_state_db,
        component_dbs.get("canonical_relationship_db", {}),
    )
    runtime_log = build_runtime_log(simulation_state_db, runtime_event_db)
    world_db["canonical_novel_db"] = canonical_db
    world_db["canonical_component_dbs"] = component_dbs
    world_db.update(component_dbs)
    world_db["simulation_state_db"] = simulation_state_db
    world_db["simulation_state_template"] = simulation_state_db
    world_db["runtime_event_db"] = runtime_event_db
    world_db["runtime_relationship_db"] = runtime_relationship_db
    world_db["runtime_log"] = runtime_log
    world_db["dependency_graph"] = canonical_db["dependency_graph"]
    world_db["acquisition_system"] = canonical_db["acquisition_system"]
    world_db["layered_world_state_policy"] = {
        "canonical_db_is_read_only": True,
        "canonical_components_are_read_only": True,
        "simulation_state_template_is_cutoff_state": True,
        "runtime_simulation_state_is_live_truth": True,
        "runtime_event_db_controls_future_progress": True,
        "runtime_relationship_db_controls_current_relationship_truth": True,
        "resource_grants_require_dependency_checks": True,
        "agents_use_current_state_not_canonical_ending": True,
    }
    validation = world_db.setdefault("validation", {})
    validation["layered_world_state"] = {
        "canonical_resource_count": len(canonical_db.get("resources", {})),
        "simulation_resource_state_count": len(
            simulation_state_db.get("current_world_state", {}).get(
                "resource_states", {}
            )
        ),
        "runtime_event_queue_count": len(runtime_event_db.get("event_queue", [])),
        "runtime_relationship_count": len(
            runtime_relationship_db.get("relationships", {})
        ),
        "exclusive_resource_count": canonical_db.get("validation", {}).get(
            "exclusive_resource_count", 0
        ),
        "open_resource_count": canonical_db.get("validation", {}).get(
            "open_resource_count", 0
        ),
    }
    return world_db


def write_world_state_layer_files(base_dir, world_db):
    base_dir = Path(base_dir)
    files = {
        "canonical_novel_db.json": world_db.get("canonical_novel_db", {}),
        "canonical_timeline_db.json": world_db.get("canonical_timeline_db", {}),
        "canonical_event_db.json": world_db.get("canonical_event_db", {}),
        "canonical_scene_beat_db.json": world_db.get("canonical_scene_beat_db", {}),
        "canonical_character_db.json": world_db.get("canonical_character_db", {}),
        "canonical_relationship_db.json": world_db.get("canonical_relationship_db", {}),
        "canonical_ability_db.json": world_db.get("canonical_ability_db", {}),
        "canonical_item_db.json": world_db.get("canonical_item_db", {}),
        "canonical_organization_db.json": world_db.get("canonical_organization_db", {}),
        "canonical_location_db.json": world_db.get("canonical_location_db", {}),
        "canonical_world_rule_db.json": world_db.get("canonical_world_rule_db", {}),
        "canonical_knowledge_db.json": world_db.get("canonical_knowledge_db", {}),
        "simulation_state_db.json": world_db.get("simulation_state_db", {}),
        "simulation_state_template.json": world_db.get("simulation_state_template", {}),
        "runtime_event_db.json": world_db.get("runtime_event_db", {}),
        "runtime_relationship_db.json": world_db.get("runtime_relationship_db", {}),
        "runtime_log.json": world_db.get("runtime_log", {}),
    }
    for name, payload in files.items():
        atomic_write_json(base_dir / name, payload)
    return files


def write_runtime_agent_state_file(base_dir, agent_profiles, simulation_state_db, runtime_relationship_db=None):
    base_dir = Path(base_dir)
    runtime_agent_state = build_runtime_agent_state(
        agent_profiles,
        simulation_state_db,
        runtime_relationship_db=runtime_relationship_db,
    )
    atomic_write_json(base_dir / "runtime_agent_state.json", runtime_agent_state)
    return runtime_agent_state


def load_layer_sidecars(world_db, base_dir):
    base_dir = Path(base_dir)
    mapping = {
        "canonical_novel_db": "canonical_novel_db.json",
        "canonical_timeline_db": "canonical_timeline_db.json",
        "canonical_event_db": "canonical_event_db.json",
        "canonical_scene_beat_db": "canonical_scene_beat_db.json",
        "canonical_character_db": "canonical_character_db.json",
        "canonical_relationship_db": "canonical_relationship_db.json",
        "canonical_ability_db": "canonical_ability_db.json",
        "canonical_item_db": "canonical_item_db.json",
        "canonical_organization_db": "canonical_organization_db.json",
        "canonical_location_db": "canonical_location_db.json",
        "canonical_world_rule_db": "canonical_world_rule_db.json",
        "canonical_knowledge_db": "canonical_knowledge_db.json",
        "simulation_state_db": "simulation_state_db.json",
        "simulation_state_template": "simulation_state_template.json",
        "runtime_event_db": "runtime_event_db.json",
        "runtime_relationship_db": "runtime_relationship_db.json",
        "runtime_log": "runtime_log.json",
    }
    for key, filename in mapping.items():
        path = base_dir / filename
        if key not in world_db and path.is_file():
            world_db[key] = json.loads(path.read_text(encoding="utf-8"))
    if "dependency_graph" not in world_db and world_db.get("canonical_novel_db"):
        world_db["dependency_graph"] = world_db["canonical_novel_db"].get(
            "dependency_graph", {}
        )
    if "acquisition_system" not in world_db and world_db.get("canonical_novel_db"):
        world_db["acquisition_system"] = world_db["canonical_novel_db"].get(
            "acquisition_system", {}
        )
    return world_db
