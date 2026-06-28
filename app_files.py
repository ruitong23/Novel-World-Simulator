"""Shared file contracts and settings for the desktop applications."""

import json
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.json"
GENERATED_DB_DIR = APP_DIR / "db"
GRAPH_DB_DIR = GENERATED_DB_DIR / "graph"
CANONICAL_DB_DIR = GENERATED_DB_DIR / "canonical"
AGENT_DB_DIR = GENERATED_DB_DIR / "agents"
RUNTIME_DB_DIR = GENERATED_DB_DIR / "runtime"


def generated_db_path(group, filename):
    if group == "graph":
        return GRAPH_DB_DIR / filename
    if group == "canonical":
        return CANONICAL_DB_DIR / filename
    if group == "agents":
        return AGENT_DB_DIR / filename
    if group == "runtime":
        return RUNTIME_DB_DIR / filename
    # Backward-compatible aliases for older code paths.
    if group in {"world", "characters"}:
        return CANONICAL_DB_DIR / filename
    raise ValueError(f"Unknown generated DB group: {group}")

PREPARATION_OUTPUTS = [
    ("db/graph/novel_ontology.json", "Ontology used by graph extraction"),
    ("db/graph/raw_graph_triples.json", "Single-pass skeleton graph triples for selected chunks"),
    ("db/graph/mention_weak_relations.json", "Mention-level weak relation evidence"),
    ("db/canonical/mention_alias_index.json", "Mention and alias index"),
    ("db/canonical/canonical_entities.json", "Resolved canonical entities"),
    ("db/graph/normalized_graph_triples.json", "Normalized graph"),
    ("db/canonical/canonical_relationship_db.json", "Canonical relationship database"),
    ("db/canonical/relationship_arc_db.json", "Relationship arc database"),
    ("db/graph/structured_world_graph.json", "Structured world graph aggregated from skeleton evidence"),
    ("db/canonical/character_state_db.json", "Character state database"),
    ("db/canonical/world_db.json", "Canonical world aggregate"),
    ("db/canonical/canonical_timeline_db.json", "Canonical baseline timeline"),
    ("db/canonical/canonical_event_db.json", "Canonical event database"),
    ("db/canonical/canonical_scene_beat_db.json", "Skeleton scene-beat database for RAG and pacing"),
    ("db/canonical/canonical_character_db.json", "Canonical character template database"),
    ("db/canonical/canonical_relationships_db.json", "Canonical relationship evidence database"),
    ("db/canonical/canonical_ability_db.json", "Canonical ability database"),
    ("db/canonical/canonical_item_db.json", "Canonical item database"),
    ("db/canonical/canonical_organization_db.json", "Canonical organization database"),
    ("db/canonical/canonical_location_db.json", "Canonical location database"),
    ("db/canonical/canonical_world_rule_db.json", "Canonical world-rule database"),
    ("db/canonical/canonical_knowledge_db.json", "Canonical knowledge database"),
    ("db/runtime/simulation_state_template.json", "Cutoff-based initial state template"),
    ("db/runtime/runtime_event_db.json", "Runtime event queue database"),
    ("db/runtime/runtime_relationship_db.json", "Runtime relationship database"),
    ("db/runtime/runtime_log.json", "Runtime event-sourcing log"),
    ("db/agents/agent_profiles.json", "Canonical agent profile templates"),
    ("db/agents/runtime_agent_state.json", "Runtime agent dynamic state"),
]

SIMULATION_REQUIRED_FILES = [
    ("db/canonical/world_db.json", "Canonical world aggregate"),
    ("db/canonical/canonical_timeline_db.json", "Canonical baseline timeline"),
    ("db/canonical/canonical_event_db.json", "Canonical event database"),
    ("db/runtime/simulation_state_template.json", "Cutoff-based initial state template"),
    ("db/runtime/runtime_event_db.json", "Runtime event queue database"),
    ("db/runtime/runtime_relationship_db.json", "Runtime relationship database"),
    ("db/canonical/canonical_character_db.json", "Canonical character template database"),
    ("db/agents/agent_profiles.json", "Canonical agent profile templates"),
    ("db/agents/runtime_agent_state.json", "Runtime agent dynamic state"),
    ("step17_runtime.py", "Step 17 simulation engine"),
]


def file_status(rows, base_dir=APP_DIR):
    return [
        {
            "name": name,
            "description": description,
            "exists": (Path(base_dir) / name).is_file(),
            "path": Path(base_dir) / name,
        }
        for name, description in rows
    ]


def load_settings():
    defaults = {
        "llm_base_url": "http://localhost:1234/v1",
        "llm_model": "gemma-4-26b-a4b-it",
        "llm_api_key": "lm-studio",
    }
    if not SETTINGS_PATH.is_file():
        return defaults
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    return {**defaults, **saved}


def save_settings(settings):
    temporary = SETTINGS_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(SETTINGS_PATH)
