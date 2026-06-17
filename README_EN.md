# Novel World Simulator

A novel world simulation framework powered by LLMs, knowledge graphs, and autonomous agents.

The system transforms a novel into a structured, queryable, and simulation-ready world by extracting characters, locations, organizations, abilities, items, events, and world rules.

The generated world can then be used for roleplay, agent interactions, branching storylines, and dynamic world simulation.

## Features

* Automatic novel parsing
* Structured knowledge graph generation
* Entity discovery and resolution
* Relationship extraction
* Event extraction
* Ability and item extraction
* World database generation
* Agent profile generation
* Timeline-based simulation entry points
* Dynamic events and relationship updates
* Multi-agent simulation foundation

## Pipeline

```text
Novel
  ↓
Ontology Generation
  ↓
Knowledge Graph Extraction
  ↓
Entity Resolution
  ↓
World Database
  ↓
Agent Profiles
  ↓
Simulation Runtime
```

## Project Structure

```text
generated_db/
├── graph/
├── canonical/
├── agents/
└── runtime/
```

* Graph: knowledge graph layer
* Canonical: source novel baseline data
* Agents: character templates and runtime states
* Runtime: active simulation state

## Usage

1. Prepare a novel text file
2. Run the extraction pipeline
3. Generate the world database
4. Generate agent profiles
5. Select a timeline point and start simulation

## Current Status

Implemented:

* Novel parsing
* Knowledge graph construction
* Entity resolution
* World database generation
* Agent profile generation

In Progress:

* Runtime agent state system
* Dynamic relationship engine
* Dynamic event engine
* Multi-agent simulation
* Visualization interface

## Roadmap

* Long novel optimization
* Multi-world support
* Tool-calling agents
* Long-term memory
* Dynamic story generation
* Web UI
* Interactive world simulation

## Vision

Transform novels from static text into living worlds that can be explored, queried, interacted with, and continuously evolved.
