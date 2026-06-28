# NavelMaker 2 Desktop Guide

NavelMaker 2 Desktop is a local novel preparation and simulation runtime. It converts a novel TXT file into layered JSON databases that can start from any canonical time point, branch away from the original plot, update relationships, change abilities/items/identities, support Agent decisions, and accept user intervention.

## Quick Start

Run these batch files in order:

```bat
01_install_requirements.bat
02_prepare_simulation.bat
03_run_simulation.bat
```

`01_install_requirements.bat` installs dependencies. `02_prepare_simulation.bat` opens the preparation UI. Select a novel, choose the source percentage, verify the local LLM, and generate databases. The preparation UI's `Preview source moment` button lets you skim roughly 3000 characters around the selected percentage before generating DBs. `03_run_simulation.bat` launches the simulation UI.

## Local LLM

The app needs an OpenAI-compatible API, such as LM Studio. Defaults live in `settings.json`:

```json
{
  "llm_base_url": "http://localhost:1234/v1",
  "llm_model": "gemma-4-26b-a4b-it",
  "llm_api_key": "lm-studio"
}
```

Both preparation and simulation read this file. Environment variables `NOVEL_LLM_BASE_URL`, `NOVEL_LLM_MODEL`, and `NOVEL_LLM_API_KEY` override it.

## Output Layout

Official outputs are under `db/`:

```text
db/
  graph/
    novel_ontology.json
    raw_graph_triples.json
    normalized_graph_triples.json
    structured_world_graph.json
    mention_weak_relations.json

  canonical/
    world_db.json
    canonical_timeline_db.json
    canonical_event_db.json
    canonical_character_db.json
    canonical_relationship_db.json
    canonical_scene_beat_db.json
    canonical_ability_db.json
    canonical_item_db.json
    canonical_organization_db.json
    canonical_location_db.json
    canonical_world_rule_db.json
    canonical_knowledge_db.json
    relationship_arc_db.json
    mention_alias_index.json
    canonical_entities.json
    character_state_db.json

  agents/
    agent_profiles.json
    runtime_agent_state.json
    runtime_agent_dbs_index.json
    runtime_agent_dbs/

  runtime/
    simulation_state_template.json
    simulation_state.json
    runtime_event_db.json
    runtime_relationship_db.json
    runtime_log.json
```

`graph/` stores extraction and entity-resolution evidence. `canonical/` is the read-only original baseline. `canonical_scene_beat_db.json` stores low-confidence scene beats derived from skeleton evidence; these provide narrative pressure and preview context, not hard canonical events. `agents/agent_profiles.json` is the canonical character template layer, `agents/runtime_agent_state.json` is mutable runtime agent state, and `agents/runtime_agent_dbs/` stores per-active-agent retrieval sidecars. `runtime/` stores the live simulation save and event queues.

## Core Rules

- Canonical data is the original baseline, not current truth.
- Runtime data is the current world truth.
- Agent Profiles are templates and are not directly mutated during simulation.
- Abilities, items, relationships, identities, organizations, and knowledge scope are not inherited from final canon.
- Current state is determined by cutoff_order and committed runtime events.
- The original plot is a default route, not destiny; blocked canonical events do not force themselves back in.
- Relationships are multidimensional event-driven state, not final labels.

## Canonical Layer

`canonical_timeline_db.json` stores only the default source route and event references. `canonical_event_db.json` stores events, trigger conditions, preconditions, blocked consequences, and `alternative_runtime_hooks`.

Resources are split into:

- `canonical_ability_db.json`
- `canonical_item_db.json`
- `canonical_relationship_db.json`
- `canonical_organization_db.json`
- `canonical_world_rule_db.json`
- `canonical_knowledge_db.json`

Abilities, items, identities, and relationships keep Dependency Graph / Acquisition System information, including acquisition, loss, use, upgrade, and transfer conditions. Original canonical owners are stored separately from current runtime owners.

## Runtime Layer

`simulation_state_template.json` is the initial checkpoint produced by cutting canonical data at a selected cutoff. Once simulation starts, the live save is:

```text
db/runtime/simulation_state.json
```

Runtime also synchronizes:

- `runtime_event_db.json`
- `runtime_relationship_db.json`
- `runtime_log.json`
- `agents/runtime_agent_state.json`

So a new simulation reuses the canonical baseline and cutoff template, but player actions, relationship state, resource ownership, dynamic agent state, and memories are written to runtime only.

The simulation UI's `Preview DB anchor` button creates a player-facing opening preview from the selected character and story progress. It prioritizes the character's direct source chunk, scene beats, and raw graph evidence, then summarizes identity, aliases/forms, location, abilities, relationships, before/after context, and evidence gaps. For example, selecting Bai Gu Jing should anchor near White Tiger Ridge rather than showing only a vague percentage.

After several turns, `Save` writes `runtime.recovery_snapshot`. When the simulation UI opens again, it prefers that recovery snapshot and displays a short "last save recap" with the latest story summary, current location, nearby characters, and time. Each turn also updates `recent_dialogue_turns`, `agent_memories`, `runtime_event_db.json`, `runtime_log.json`, and per-agent sidecar DBs so the conversation can continue with continuity.

## Retrieval And Control

Step17 builds a RAG orchestration packet for every reasoning step. The player character is `MANUAL`, so user input directly controls only that character's attempted action for the turn. Nearby NPCs are `AUTO` and may act only from visible scene state, memory, and their own retrieval packet. The Local World Agent handles the current local area, sensory state, positions, local events, and explanations for newly surfaced abilities/items. The GM Resolver adjudicates success, consequences, causal consistency, and the current canonical anchor status. The Global World Agent only runs for long time jumps, travel, leaving the region, or high-impact events.

Actor-facing RAG packets exclude future canonical anchors, preventing characters from seeing future plot. System packets may use current and nearby anchors as narrative pressure, but canonical data does not directly overwrite runtime truth.

## Relationship System

Before Entity Resolution, the pipeline creates `graph/mention_weak_relations.json`. These mention-level weak relations include same-scene co-presence, forms of address, actions, shared event participation, shared locations, shared items, aliases, titles, and transformations. They are resolver evidence only, not runtime truth.

After entity resolution, weak relations normalize into `canonical_relationship_db.json` and `relationship_arc_db.json`. During simulation, the current relationship truth is controlled by `runtime/runtime_relationship_db.json`.

## Command-Line Test

Run the first N chunks directly:

```bat
python pipeline_program.py --novel "C:\path\to\novel.txt" --percent 100 --chunk-limit 20
```

Use `--chunk-limit 0` to process every chunk in the selected percentage.

## GitHub Upload

Upload the source and documentation from the repository folder. `db/` is runtime output and is usually not committed unless you intentionally want sample databases.
