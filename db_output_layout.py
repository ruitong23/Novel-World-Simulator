"""Output folders for generated simulation databases."""

from __future__ import annotations

import shutil
from pathlib import Path


GENERATED_DB_DIR = Path("db")
GRAPH_DB_DIR = GENERATED_DB_DIR / "graph"
CANONICAL_DB_DIR = GENERATED_DB_DIR / "canonical"
AGENT_DB_DIR = GENERATED_DB_DIR / "agents"
RUNTIME_DB_DIR = GENERATED_DB_DIR / "runtime"


GRAPH_FILES = [
    "novel_ontology.json",
    "raw_graph_triples.json",
    "normalized_graph_triples.json",
    "structured_world_graph.json",
    "mention_weak_relations.json",
]

CANONICAL_FILES = [
    "world_db.json",
    "canonical_novel_db.json",
    "canonical_timeline_db.json",
    "canonical_event_db.json",
    "canonical_scene_beat_db.json",
    "canonical_character_db.json",
    "canonical_relationship_db.json",
    "canonical_relationships_db.json",
    "canonical_ability_db.json",
    "canonical_item_db.json",
    "canonical_organization_db.json",
    "canonical_location_db.json",
    "canonical_world_rule_db.json",
    "canonical_knowledge_db.json",
    "relationship_arc_db.json",
    "mention_alias_index.json",
    "canonical_entities.json",
    "character_state_db.json",
    "simulation_state_db.json",
]

AGENT_FILES = [
    "agent_profiles.json",
    "runtime_agent_state.json",
]

RUNTIME_FILES = [
    "simulation_state_template.json",
    "simulation_state.json",
    "runtime_event_db.json",
    "runtime_relationship_db.json",
    "runtime_log.json",
]


def generated_path(group, filename, base_dir=Path(".")):
    base_dir = Path(base_dir)
    if group == "graph":
        return base_dir / GRAPH_DB_DIR / filename
    if group == "canonical":
        return base_dir / CANONICAL_DB_DIR / filename
    if group == "agents":
        return base_dir / AGENT_DB_DIR / filename
    if group == "runtime":
        return base_dir / RUNTIME_DB_DIR / filename
    # Compatibility for older callers. New code should use graph/canonical/runtime.
    if group == "world":
        return base_dir / CANONICAL_DB_DIR / filename
    if group == "characters":
        return base_dir / CANONICAL_DB_DIR / filename
    raise ValueError(f"Unknown generated DB group: {group}")


def ensure_generated_dirs(base_dir=Path(".")):
    base_dir = Path(base_dir)
    for directory in (GRAPH_DB_DIR, CANONICAL_DB_DIR, AGENT_DB_DIR, RUNTIME_DB_DIR):
        (base_dir / directory).mkdir(parents=True, exist_ok=True)


def publish_generated_databases(base_dir=Path(".")):
    base_dir = Path(base_dir)
    ensure_generated_dirs(base_dir)
    published = {}
    for group, filenames in (
        ("graph", GRAPH_FILES),
        ("canonical", CANONICAL_FILES),
        ("agents", AGENT_FILES),
        ("runtime", RUNTIME_FILES),
    ):
        for filename in filenames:
            source = base_dir / filename
            if not source.is_file():
                continue
            target = generated_path(group, filename, base_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            published[filename] = str(target)
    return published


def cleanup_root_database_files(base_dir=Path("."), published=None):
    """Remove root-level generated JSON files after they were copied to db/."""
    base_dir = Path(base_dir)
    published = published or publish_generated_databases(base_dir)
    protected = {"settings.json"}
    removed = []
    for filename in sorted(
        set(GRAPH_FILES + CANONICAL_FILES + AGENT_FILES + RUNTIME_FILES)
    ):
        if filename in protected:
            continue
        source = base_dir / filename
        target = published.get(filename)
        if not source.is_file() or not target or not Path(target).is_file():
            continue
        source.unlink()
        removed.append(str(source))
    return removed
