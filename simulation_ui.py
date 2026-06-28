"""Standalone Tkinter interface for the Step 17 novel simulation runtime."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import messagebox, ttk

from app_files import (
    SIMULATION_REQUIRED_FILES,
    file_status,
    generated_db_path,
    load_settings,
)
from step17_runtime import load_step17_runtime


def make_llm_callable(base_url, model, api_key):
    def call_llm(system_prompt, user_prompt, temperature=0.2, max_tokens=4096):
        request = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=900) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"].strip()

    return call_llm


class SimulationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NavelMaker 2 - Novel Simulation")
        self.root.geometry("1180x800")
        self.root.minsize(960, 680)
        self.events = queue.Queue()
        self.operation_started = None
        self.selected_character_id = None
        self.start_percent = tk.DoubleVar(value=0.0)

        saved = load_settings()
        self.base_url = os.getenv("NOVEL_LLM_BASE_URL", saved["llm_base_url"])
        self.model = os.getenv("NOVEL_LLM_MODEL", saved["llm_model"])
        self.api_key = (
            os.getenv("NOVEL_LLM_API_KEY", saved["llm_api_key"]).strip()
            or "lm-studio"
        )
        llm = make_llm_callable(self.base_url, self.model, self.api_key)
        self.runtime = load_step17_runtime(
            world_path=generated_db_path("canonical", "world_db.json"),
            character_path=generated_db_path(
                "canonical", "canonical_character_db.json"
            ),
            agent_path=generated_db_path("agents", "agent_profiles.json"),
            state_path=generated_db_path("runtime", "simulation_state.json"),
            llm_callable=llm,
        )
        self.store = self.runtime["store"]
        self.orchestrator = self.runtime["orchestrator"]
        self.catalog = sorted(
            self.orchestrator.agent_catalog(),
            key=lambda item: item.get("canonical_name", "").casefold(),
        )
        self.catalog_by_id = {
            item["character_id"]: item for item in self.catalog
        }
        self.character_by_id = {
            item["character_id"]: item
            for item in self.runtime["character_db"].get("characters", [])
        }
        self.filtered_catalog = list(self.catalog)
        self.list_ids = []

        self.search_text = tk.StringVar()
        self.file_status_text = tk.StringVar(value="Required files: all checks passed")
        self.runtime_status_text = tk.StringVar()
        self.progress_value = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="Ready")
        self.eta_text = tk.StringVar(value="ETA: --")
        self.story_progress_value = tk.DoubleVar(value=0)
        self.story_progress_text = tk.StringVar(value="Story progress: --")

        self._build_ui()
        self._refresh_agent_list()
        self._restore_active_character()
        self._refresh_runtime_status()
        self._show_latest_story(prefer_recovery=True)
        self.root.after(100, self._drain_events)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(
            header,
            text="NavelMaker 2",
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left")
        ttk.Label(header, textvariable=self.file_status_text, foreground="#137333").pack(
            side="right"
        )

        left = ttk.LabelFrame(outer, text="Choose a character", padding=8)
        left.grid(row=1, column=0, sticky="nsw", padx=(0, 8))
        left.rowconfigure(1, weight=1)

        search = ttk.Entry(left, textvariable=self.search_text, width=32)
        search.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        search.bind("<KeyRelease>", lambda _event: self._apply_filter())

        self.agent_list = tk.Listbox(left, width=35, exportselection=False)
        agent_scroll = ttk.Scrollbar(left, command=self.agent_list.yview)
        self.agent_list.configure(yscrollcommand=agent_scroll.set)
        self.agent_list.grid(row=1, column=0, sticky="nsew")
        agent_scroll.grid(row=1, column=1, sticky="ns")
        self.agent_list.bind("<<ListboxSelect>>", self._select_agent)

        self.agent_detail = tk.Text(left, width=35, height=13, wrap="word", state="disabled")
        self.agent_detail.grid(row=2, column=0, columnspan=2, pady=(8, 6), sticky="ew")
        start_scope = ttk.Frame(left)
        start_scope.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        start_scope.columnconfigure(1, weight=1)
        ttk.Label(start_scope, text="Start %").grid(row=0, column=0, sticky="w")
        ttk.Scale(
            start_scope,
            from_=0,
            to=100,
            variable=self.start_percent,
        ).grid(row=0, column=1, padx=6, sticky="ew")
        ttk.Label(start_scope, text="0 = auto").grid(row=0, column=2, sticky="e")
        self.enter_button = ttk.Button(
            left, text="Enter world as this character", command=self.enter_world
        )
        self.enter_button.grid(row=4, column=0, columnspan=2, sticky="ew")

        right = ttk.Frame(outer)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        runtime_frame = ttk.LabelFrame(right, text="Runtime", padding=8)
        runtime_frame.grid(row=0, column=0, sticky="ew")
        runtime_frame.columnconfigure(0, weight=1)
        ttk.Label(runtime_frame, textvariable=self.runtime_status_text).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Progressbar(
            runtime_frame,
            variable=self.progress_value,
            maximum=100,
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(runtime_frame, textvariable=self.progress_text).grid(
            row=2, column=0, sticky="w"
        )
        ttk.Label(runtime_frame, textvariable=self.eta_text).grid(
            row=2, column=1, sticky="e", padx=8
        )
        self.save_button = ttk.Button(
            runtime_frame, text="Save", command=self.save_world
        )
        self.save_button.grid(row=1, column=2, padx=(8, 0))
        ttk.Button(runtime_frame, text="Reset world", command=self.reset_world).grid(
            row=2, column=2, padx=(8, 0)
        )
        ttk.Progressbar(
            runtime_frame,
            variable=self.story_progress_value,
            maximum=100,
        ).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(runtime_frame, textvariable=self.story_progress_text).grid(
            row=4, column=0, columnspan=3, sticky="w"
        )
        ttk.Button(
            runtime_frame,
            text="Preview DB anchor",
            command=self.preview_db_anchor,
        ).grid(row=5, column=2, padx=(8, 0), pady=(6, 0), sticky="e")

        notebook = ttk.Notebook(right)
        notebook.grid(row=1, column=0, pady=(8, 0), sticky="nsew")
        story_tab = ttk.Frame(notebook, padding=8)
        status_tab = ttk.Frame(notebook, padding=8)
        diagnostics_tab = ttk.Frame(notebook, padding=8)
        notebook.add(story_tab, text="Story")
        notebook.add(status_tab, text="Character status")
        notebook.add(diagnostics_tab, text="Diagnostics")

        story_tab.columnconfigure(0, weight=1)
        story_tab.rowconfigure(0, weight=1)
        self.story = tk.Text(
            story_tab,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 11),
            padx=12,
            pady=12,
        )
        story_scroll = ttk.Scrollbar(story_tab, command=self.story.yview)
        self.story.configure(yscrollcommand=story_scroll.set)
        self.story.grid(row=0, column=0, sticky="nsew")
        story_scroll.grid(row=0, column=1, sticky="ns")

        self.user_input = tk.Text(story_tab, height=4, wrap="word")
        self.user_input.grid(row=1, column=0, pady=(8, 0), sticky="ew")
        self.continue_button = ttk.Button(
            story_tab, text="Continue story", command=self.continue_story
        )
        self.continue_button.grid(row=1, column=1, padx=(8, 0), pady=(8, 0), sticky="ns")

        self.status_view = tk.Text(status_tab, wrap="word", state="disabled")
        self.status_view.pack(fill="both", expand=True)
        self.diagnostics = tk.Text(
            diagnostics_tab, wrap="none", state="disabled", font=("Consolas", 9)
        )
        self.diagnostics.pack(fill="both", expand=True)

    def _apply_filter(self):
        query = self.search_text.get().strip().casefold()
        self.filtered_catalog = [
            item
            for item in self.catalog
            if not query
            or query in item.get("canonical_name", "").casefold()
            or query
            in " ".join(item.get("aliases", [])).casefold()
        ]
        self._refresh_agent_list()

    def _refresh_agent_list(self):
        self.agent_list.delete(0, "end")
        self.list_ids = []
        for item in self.filtered_catalog:
            tier = item.get("tier", "reference").upper()
            self.agent_list.insert(
                "end", f"{item.get('canonical_name', '?')}  [{tier}]"
            )
            self.list_ids.append(item["character_id"])

    def _restore_active_character(self):
        scene = self.store.runtime.get("active_scene") or {}
        character_id = scene.get("focus_character_id")
        if not character_id or character_id not in self.list_ids:
            return
        index = self.list_ids.index(character_id)
        self.agent_list.selection_clear(0, "end")
        self.agent_list.selection_set(index)
        self.agent_list.see(index)
        self._select_agent()

    def _select_agent(self, _event=None):
        selection = self.agent_list.curselection()
        if not selection:
            return
        character_id = self.list_ids[selection[0]]
        self.selected_character_id = character_id
        catalog = self.catalog_by_id[character_id]
        character = self.character_by_id.get(character_id, {})
        detail = "\n".join(
            [
                catalog.get("canonical_name", ""),
                f"Tier: {catalog.get('tier', 'unknown')}",
                catalog.get("notice", ""),
                "",
                character.get("background_summary", ""),
                "",
                "Aliases: " + ", ".join(character.get("aliases", [])),
            ]
        ).strip()
        self._set_text(self.agent_detail, detail)
        self._show_character_status(character_id)

    def _show_character_status(self, character_id=None):
        character_id = character_id or self.selected_character_id
        if not character_id:
            return
        character = self.character_by_id.get(character_id, {})
        runtime_state = self.store.runtime.get("character_runtime", {}).get(
            character_id, {}
        )
        content = {
            "canonical_name": character.get("canonical_name"),
            "background": character.get("background_summary"),
            "personality": character.get("personality", []),
            "goals": character.get("goals", []),
            "constraints": character.get("constraints", []),
            "abilities": character.get("abilities", []),
            "story_progress": self._story_progress_snapshot(),
            "runtime": runtime_state,
        }
        self._set_text(
            self.status_view, json.dumps(content, ensure_ascii=False, indent=2)
        )

    def _progress_callback(self, value, label):
        self.events.put(("progress", {"percent": value, "label": label}))

    def _run_operation(self, label, function):
        self.operation_started = time.monotonic()
        self.progress_value.set(1)
        self.progress_text.set(label)
        self.eta_text.set("ETA: calculating")
        self.enter_button.configure(state="disabled")
        self.continue_button.configure(state="disabled")
        self.save_button.configure(state="disabled")

        def worker():
            try:
                result = function()
                self.events.put(("operation_done", result))
            except Exception as error:
                self.events.put(("operation_error", error))

        threading.Thread(target=worker, daemon=True).start()

    def enter_world(self):
        if not self.selected_character_id:
            messagebox.showwarning("Choose a character", "Select a character first.")
            return
        self._run_operation(
            "Creating the opening scene...",
            lambda: self.orchestrator.start_character_experience(
                self.selected_character_id,
                progress_percent=(
                    float(self.start_percent.get())
                    if float(self.start_percent.get()) > 0
                    else None
                ),
                progress_callback=self._progress_callback,
            ),
        )

    def continue_story(self):
        if not self.store.runtime.get("active_scene"):
            messagebox.showwarning(
                "No active scene", "Choose a character and enter the world first."
            )
            return
        text = self.user_input.get("1.0", "end").strip()
        if not text:
            text = "I pause and pay attention to what is happening around me."
        self._run_operation(
            "Running the next simulation turn...",
            lambda: self.orchestrator.run_turn(
                text, progress_callback=self._progress_callback
            ),
        )

    def save_world(self):
        if not self.store.runtime.get("active_scene"):
            messagebox.showwarning(
                "No active scene",
                "Choose a character and enter the world before saving.",
            )
            return
        self._run_operation(
            "Preparing manual save...",
            lambda: {
                "manual_save": self.orchestrator.create_manual_save(
                    progress_callback=self._progress_callback
                )
            },
        )

    def _db_anchor_packet(self):
        story_progress = self._story_progress_snapshot()
        runtime = self.store.runtime
        timeline = (
            runtime.get("canonical_timeline")
            or self.orchestrator.canonical_timeline
            or self.runtime["world_db"]
            .get("canonical_timeline_db", {})
            .get("timeline_nodes", [])
        )
        scene = runtime.get("active_scene") or {}
        focus_id = scene.get("focus_character_id") or self.selected_character_id
        if timeline and not runtime.get("active_scene") and self.start_percent.get() > 0:
            cursor = round((len(timeline) - 1) * float(self.start_percent.get()) / 100)
        elif timeline and not runtime.get("active_scene") and focus_id:
            try:
                cursor, _anchor = self.orchestrator._opening_anchor(focus_id)
            except Exception:
                cursor = int(runtime.get("timeline_cursor", 0) or 0)
        else:
            cursor = int(runtime.get("timeline_cursor", 0) or 0)
        cursor = max(0, min(cursor, max(0, len(timeline) - 1)))
        current = timeline[cursor] if timeline else {}
        nearby = timeline[max(0, cursor - 2): cursor + 3] if timeline else []
        focus_name = self.character_by_id.get(focus_id, {}).get(
            "canonical_name", "No active character"
        )
        character_packet = self._character_preview_packet(
            focus_id,
            cursor,
            timeline,
        )
        return {
            "focus_character": focus_name,
            "focus_character_id": focus_id,
            "focus_character_packet": character_packet,
            "selected_start_percent": float(self.start_percent.get()),
            "preview_cursor": cursor,
            "active_scene": scene,
            "story_progress": story_progress,
            "current_canonical_anchor": current,
            "nearby_canonical_anchors": nearby,
            "recent_branch_records": runtime.get("branch_records", [])[-5:],
            "recent_runtime_events": [
                {
                    "event_type": item.get("event_type"),
                    "narration": item.get("narration", "")[:500],
                    "revision_after": item.get("revision_after"),
                }
                for item in self.store.branch.get("events", [])[-5:]
            ],
        }

    def _character_preview_packet(self, character_id, cursor, timeline):
        if not character_id:
            return {}
        character = self.character_by_id.get(character_id, {})
        try:
            profile = self.orchestrator._dynamic_profile(character_id)
        except Exception:
            profile = {}
        world_db = self.runtime["world_db"]
        canonical_db = world_db.get("canonical_novel_db", {})
        entity_track = canonical_db.get("entity_tracks", {}).get(character_id, {})
        names = {
            character.get("canonical_name", ""),
            entity_track.get("canonical_name", ""),
            profile.get("canonical_name", ""),
            *character.get("aliases", []),
            *character.get("forms", []),
            *entity_track.get("aliases", []),
            *entity_track.get("forms", []),
            *profile.get("identity", {}).get("aliases", []),
            *profile.get("identity", {}).get("forms", []),
        }
        names = {item for item in names if item}
        source_orders = set()
        for value in (
            character.get("first_seen_order"),
            entity_track.get("first_seen_order"),
            profile.get("first_seen_order"),
        ):
            if str(value).isdigit():
                source_orders.add(int(value))
        for source in (
            character.get("source_chunk_ids", []),
            entity_track.get("source_chunk_ids", []),
            profile.get("source_chunk_refs", []),
        ):
            for value in source:
                if str(value).isdigit():
                    source_orders.add(int(value))
        for evidence in [
            *character.get("evidence_refs", []),
            *entity_track.get("evidence_refs", []),
            *profile.get("evidence_refs", []),
        ]:
            value = evidence.get("source_chunk_id")
            if str(value).isdigit():
                source_orders.add(int(value))
        if timeline and not source_orders and 0 <= cursor < len(timeline):
            for value in timeline[cursor].get("source_chunk_ids", []):
                if str(value).isdigit():
                    source_orders.add(int(value))

        relationship_lines = []
        for relation in canonical_db.get("relationship_development_lines", []):
            if character_id in {
                relation.get("source_entity_id"),
                relation.get("target_entity_id"),
            }:
                relationship_lines.append(relation)

        scene_beat_hits = []
        for beat in self.orchestrator.canonical_timeline:
            text = json.dumps(beat, ensure_ascii=False)
            if character_id in text or any(name and name in text for name in names):
                scene_beat_hits.append(beat)
                continue
            beat_orders = {
                int(value)
                for value in beat.get("source_chunk_ids", [])
                if str(value).isdigit()
            }
            if beat_orders & source_orders:
                scene_beat_hits.append(beat)

        raw_contexts = self._raw_chunk_preview_context(names, source_orders)
        raw_text = json.dumps(raw_contexts, ensure_ascii=False)
        related_names = set()
        evidence_digest = {
            "identity_or_forms": [],
            "locations": [],
            "abilities": [],
            "items": [],
            "relationship_or_conflict_lines": [],
            "nearby_event_lines": [],
            "raw_focus_descriptions": [],
        }
        focus_names = {name for name in names if name}
        for chunk in raw_contexts:
            for node in chunk.get("nodes", []):
                node_name = node.get("surface_name")
                node_type = node.get("type")
                description = node.get("description")
                if node_name:
                    related_names.add(node_name)
                node_line = "：".join(
                    part for part in (node_name, description) if part
                )
                if not node_line:
                    continue
                if node_name in focus_names or any(
                    name and name in node_line for name in focus_names
                ):
                    evidence_digest["raw_focus_descriptions"].append(node_line)
                if node_type in {"TitleOrIdentity", "Identity", "Form"}:
                    evidence_digest["identity_or_forms"].append(node_line)
                elif node_type == "Location":
                    evidence_digest["locations"].append(node_line)
                elif node_type == "Ability":
                    evidence_digest["abilities"].append(node_line)
                elif node_type in {"Artifact", "Item", "Weapon"}:
                    evidence_digest["items"].append(node_line)
            for edge in chunk.get("edges", []):
                if edge.get("source_surface_name"):
                    related_names.add(edge["source_surface_name"])
                if edge.get("target_surface_name"):
                    related_names.add(edge["target_surface_name"])
                summary = edge.get("relation_summary") or edge.get("summary")
                if summary:
                    evidence_digest["nearby_event_lines"].append(summary)
                edge_text = json.dumps(edge, ensure_ascii=False)
                if summary and any(
                    name and name in edge_text for name in focus_names
                ):
                    evidence_digest["relationship_or_conflict_lines"].append(
                        summary
                    )
        for beat in scene_beat_hits:
            beat_line = beat.get("summary") or beat.get("event")
            if beat_line:
                evidence_digest["nearby_event_lines"].append(beat_line)
        for key, values in list(evidence_digest.items()):
            deduped = []
            seen = set()
            for value in values:
                if value and value not in seen:
                    deduped.append(value)
                    seen.add(value)
                if len(deduped) >= 12:
                    break
            evidence_digest[key] = deduped

        return {
            "character_name": character.get("canonical_name")
            or entity_track.get("canonical_name")
            or profile.get("canonical_name"),
            "character": {
                "character_id": character_id,
                "canonical_name": character.get("canonical_name")
                or entity_track.get("canonical_name")
                or profile.get("canonical_name"),
                "aliases": character.get("aliases", []),
                "titles": character.get("titles", []),
                "forms": character.get("forms", [])
                or entity_track.get("forms", []),
                "first_seen_order": character.get("first_seen_order")
                or entity_track.get("first_seen_order"),
                "description": character.get("background_summary")
                or "；".join(entity_track.get("descriptions", [])),
                "attributes": entity_track.get("attributes", {}),
                "profile_tier": profile.get("profile_tier", "reference"),
                "runtime_mode": profile.get("runtime_mode", "dynamic_reference_agent"),
            },
            "capabilities": profile.get("capabilities", {}),
            "relationships": profile.get("relationships", [])[:16],
            "canonical_relationship_lines": relationship_lines[:16],
            "related_scene_beats": scene_beat_hits[:12],
            "raw_chunk_contexts": raw_contexts[:6],
            "evidence_digest": evidence_digest,
            "related_surface_names": sorted(related_names)[:40],
            "evidence_gaps": {
                "has_prebuilt_agent_profile": bool(
                    character_id in self.orchestrator.agent_by_character_id
                ),
                "has_direct_relationship_lines": bool(relationship_lines),
                "has_raw_chunk_context": bool(raw_contexts),
                "raw_context_mentions_focus": any(
                    name and name in raw_text for name in names
                ),
            },
            "preview_policy": {
                "prefer_character_centered_summary": True,
                "state_uncertainty_when_db_is_sparse": True,
                "do_not_use_external_story_knowledge": True,
                "include_playable_opening_hooks": True,
            },
        }

    def _raw_chunk_preview_context(self, names, source_orders):
        graph_path = generated_db_path("graph", "raw_graph_triples.json")
        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        target_orders = set(source_orders)
        for order in list(source_orders):
            target_orders.update({order - 1, order, order + 1})
        contexts = []
        for chunk in graph.get("results", []):
            chunk_id = chunk.get("chunk_id")
            try:
                chunk_order = int(chunk_id)
            except (TypeError, ValueError):
                chunk_order = None
            text = json.dumps(chunk, ensure_ascii=False)
            if chunk_order not in target_orders and not any(
                name and name in text for name in names
            ):
                continue
            nodes = [
                node
                for node in chunk.get("nodes", [])
                if any(name and name in json.dumps(node, ensure_ascii=False) for name in names)
                or chunk_order in source_orders
            ][:16]
            edges = [
                edge
                for edge in chunk.get("edges", [])
                if any(name and name in json.dumps(edge, ensure_ascii=False) for name in names)
                or chunk_order in source_orders
            ][:24]
            if not nodes and not edges:
                continue
            contexts.append(
                {
                    "chunk_id": chunk_id,
                    "chunk_index": chunk.get("chunk_index"),
                    "nodes": nodes,
                    "edges": edges,
                    "validation_status": chunk.get("validation_status"),
                }
            )
            if len(contexts) >= 8:
                break
        return contexts

    def _compact_db_anchor_packet_for_llm(self, payload):
        character_packet = payload.get("focus_character_packet") or {}

        def compact_anchor(anchor):
            if not anchor:
                return {}
            return {
                "scheduled_order": anchor.get("scheduled_order"),
                "event": anchor.get("event"),
                "summary": anchor.get("summary"),
                "location_id": anchor.get("location_id"),
                "participant_ids": anchor.get("participant_ids", [])[:8],
                "source_chunk_ids": anchor.get("source_chunk_ids", [])[:8],
                "confidence": anchor.get("confidence"),
            }

        def compact_relation(relation):
            return {
                "source": relation.get("source_entity_name")
                or relation.get("source_surface_name")
                or relation.get("source_entity_id"),
                "target": relation.get("target_entity_name")
                or relation.get("target_surface_name")
                or relation.get("target_entity_id"),
                "type": relation.get("relation_type") or relation.get("type"),
                "summary": relation.get("summary")
                or relation.get("relation_summary"),
            }

        return {
            "focus_character": payload.get("focus_character"),
            "selected_start_percent": payload.get("selected_start_percent"),
            "preview_cursor": payload.get("preview_cursor"),
            "story_progress": payload.get("story_progress"),
            "current_anchor": compact_anchor(
                payload.get("current_canonical_anchor")
            ),
            "nearby_anchors": [
                compact_anchor(anchor)
                for anchor in payload.get("nearby_canonical_anchors", [])[:5]
            ],
            "character": character_packet.get("character", {}),
            "character_evidence_digest": character_packet.get(
                "evidence_digest", {}
            ),
            "canonical_relationship_lines": [
                compact_relation(relation)
                for relation in character_packet.get(
                    "canonical_relationship_lines", []
                )[:8]
            ],
            "related_scene_beats": [
                compact_anchor(anchor)
                for anchor in character_packet.get("related_scene_beats", [])[:8]
            ],
            "related_surface_names": character_packet.get(
                "related_surface_names", []
            )[:30],
            "evidence_gaps": character_packet.get("evidence_gaps", {}),
            "recent_branch_records": payload.get("recent_branch_records", []),
            "recent_runtime_events": payload.get("recent_runtime_events", []),
        }

    def _render_db_anchor_preview_material(self, material):
        character = material.get("character") or {}
        digest = material.get("character_evidence_digest") or {}
        current = material.get("current_anchor") or {}
        gaps = material.get("evidence_gaps") or {}
        lines = [
            f"焦点角色：{material.get('focus_character') or 'DB 暂无'}",
            f"当前剧情锚点：{current.get('event') or 'DB 暂无'}",
            f"锚点顺序：{current.get('scheduled_order') or 'DB 暂无'}",
            f"角色身份描述：{character.get('description') or 'DB 暂无'}",
            f"首次出场顺序：{character.get('first_seen_order') or 'DB 暂无'}",
            "身份/别名/形态证据："
            + "；".join(digest.get("identity_or_forms") or ["DB 暂无"]),
            "地点证据：" + "；".join(digest.get("locations") or ["DB 暂无"]),
            "能力证据：" + "；".join(digest.get("abilities") or ["DB 暂无"]),
            "物品证据：" + "；".join(digest.get("items") or ["DB 暂无"]),
            "关系/冲突证据："
            + "；".join(
                digest.get("relationship_or_conflict_lines") or ["DB 暂无"]
            ),
            "附近事件证据："
            + "；".join(digest.get("nearby_event_lines") or ["DB 暂无"]),
            "角色原始描述："
            + "；".join(digest.get("raw_focus_descriptions") or ["DB 暂无"]),
            "相关表面名："
            + "；".join(material.get("related_surface_names") or ["DB 暂无"]),
        ]
        gap_lines = []
        if not gaps.get("has_prebuilt_agent_profile"):
            gap_lines.append("没有预制角色画像，需要运行时用原文片段补充性格、口吻和行动习惯")
        if not gaps.get("has_direct_relationship_lines"):
            gap_lines.append("没有直接关系线，需要从附近事件推断与唐僧师徒的冲突关系")
        if not gaps.get("has_raw_chunk_context"):
            gap_lines.append("没有原始片段上下文，需要回查原文")
        if not gap_lines:
            gap_lines.append("暂无明显缺口")
        lines.append("资料缺口：" + "；".join(gap_lines))
        related_beats = []
        for beat in material.get("related_scene_beats", [])[:5]:
            beat_line = beat.get("summary") or beat.get("event")
            if beat_line:
                related_beats.append(beat_line)
        if related_beats:
            lines.append("相关剧情片段：" + "；".join(related_beats))
        return "\n".join(lines)

    def preview_db_anchor(self):
        payload = self._db_anchor_packet()
        preview_material = self._compact_db_anchor_packet_for_llm(payload)
        preview_material_text = self._render_db_anchor_preview_material(
            preview_material
        )
        self.progress_text.set("Summarizing DB anchor...")

        def worker():
            try:
                summary = self.orchestrator._call_text(
                    (
                        "你是给玩家看的小说剧情预览撰稿人，不是技术顾问。"
                        "只根据给出的事实清单写角色开局预览，不使用外部知识。"
                        "你的目标是帮助玩家判断：这个角色此刻是谁、处在什么剧情附近、"
                        "有什么能力/关系/前因后果，以及适合从哪里开局。"
                        "禁止写技术方案、代码、schema、pipeline、API、节点、边、字段、ID、表格。"
                        "证据不足时写“资料暂缺”，不要编造。"
                        "你的第一行必须直接是“角色名 - 剧情阶段”，不要写"
                        "“根据提供的信息/数据”等开场白。"
                    ),
                    (
                        "请只根据下面的事实清单写预览，不要提到事实清单、"
                        "技术系统或内部结构。\n\n"
                        "输出格式：\n"
                        "角色名 - 当前剧情阶段\n"
                        "2到4句话可玩定位。\n\n"
                        "【已知信息】\n"
                        "- 身份/别名/形态：...\n"
                        "- 目标或动机：...\n"
                        "- 地点：...\n"
                        "- 人物关系：...\n\n"
                        "【能力与限制】\n"
                        "- 能力：...\n"
                        "- 物品：...\n"
                        "- 弱点或限制：...\n\n"
                        "【前因后果】\n"
                        "...\n\n"
                        "【开局切入点】\n"
                        "1. ...\n2. ...\n3. ...\n\n"
                        "【资料缺口】\n"
                        "- ...\n\n"
                        "事实清单：\n"
                        f"{preview_material_text}"
                    ),
                    temperature=0.2,
                    max_tokens=1600,
                )
                self.events.put(
                    (
                        "preview",
                        {
                            "title": "DB anchor preview",
                            "text": summary
                            + "\n\n--- DB anchor packet ---\n"
                            + json.dumps(payload, ensure_ascii=False, indent=2),
                        },
                    )
                )
            except Exception as error:
                self.events.put(("operation_error", error))

        threading.Thread(target=worker, daemon=True).start()

    def reset_world(self):
        if not messagebox.askyesno(
            "Reset simulation", "Reset runtime/simulation_state.json to a new main branch?"
        ):
            return
        self.store.reset()
        self.selected_character_id = None
        self.story.configure(state="normal")
        self.story.delete("1.0", "end")
        self.story.configure(state="disabled")
        self.progress_value.set(0)
        self.progress_text.set("World reset")
        self.eta_text.set("ETA: --")
        self._refresh_runtime_status()

    def _story_events(self):
        return [
            event
            for event in self.store.branch.get("events", [])
            if event.get("narration")
            and event.get("event_type")
            in {"scene_opening_rendered", "immersive_scene_turn"}
        ]

    def _show_latest_story(self, prefer_recovery=False):
        if prefer_recovery:
            recovery = self.store.runtime.get("recovery_snapshot") or {}
            if recovery.get("summary"):
                nearby = recovery.get("nearby_state", {})
                names = [
                    item.get("name")
                    for item in nearby.get("characters", [])
                    if item.get("name")
                ]
                clock = nearby.get("clock", {})
                minute = int(clock.get("minute_of_day", 480))
                text = "\n\n".join(
                    [
                        "上次存档回顾",
                        recovery.get("summary", ""),
                        (
                            f"当前位置：{nearby.get('location_name', '当前位置')}；"
                            f"附近人物：{'、'.join(names) or '暂无明确记录'}；"
                            f"时间：第 {clock.get('day', 1)} 天 "
                            f"{minute // 60:02d}:{minute % 60:02d}"
                        ),
                    ]
                )
                self._set_text(self.story, text)
                return
        events = self._story_events()
        text = events[-1].get("narration", "") if events else ""
        if text:
            self._set_text(self.story, text)

    def _refresh_runtime_status(self):
        snapshot = self.store.snapshot()
        scene = snapshot.get("active_scene") or {}
        focus_id = scene.get("focus_character_id")
        focus = self.character_by_id.get(focus_id, {}).get(
            "canonical_name", "No active character"
        )
        clock = snapshot.get("clock", {})
        minute = int(clock.get("minute_of_day", 480))
        self.runtime_status_text.set(
            f"{focus} | Day {clock.get('day', 1)} "
            f"{minute // 60:02d}:{minute % 60:02d} | "
            f"Revision {snapshot.get('revision', 0)} | Model {self.model}"
        )
        story_progress = self._story_progress_snapshot()
        self.story_progress_value.set(story_progress["canonical_percent"])
        self.story_progress_text.set(story_progress["label"])
        if focus_id:
            self._show_character_status(focus_id)

    def _prepared_source_progress(self):
        graph_path = generated_db_path("graph", "raw_graph_triples.json")
        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "completed": 0,
                "available": 0,
                "percent": 0.0,
            }
        completed = int(graph.get("completed_chunk_count") or 0)
        available = int(
            graph.get("available_source_chunk_count")
            or graph.get("total_source_chunk_count")
            or 0
        )
        available_unknown = not bool(available)
        if not available:
            manifest = graph.get("chunk_manifest", [])
            expected = int(graph.get("expected_chunk_count") or len(manifest) or 0)
            available = expected
        percent = completed * 100 / available if available else 0.0
        return {
            "completed": completed,
            "available": available,
            "available_unknown": available_unknown,
            "percent": max(0.0, min(100.0, percent)),
        }

    def _story_progress_snapshot(self):
        runtime = self.store.runtime
        timeline = (
            runtime.get("canonical_timeline")
            or self.orchestrator.canonical_timeline
            or self.runtime["world_db"]
            .get("canonical_timeline_db", {})
            .get("timeline_nodes", [])
        )
        total_canonical_events = len(timeline)
        cursor = int(runtime.get("timeline_cursor", 0) or 0)
        cursor = max(0, min(cursor, total_canonical_events))
        reached = (
            min(total_canonical_events, cursor + 1)
            if total_canonical_events and runtime.get("active_scene")
            else cursor
        )
        runtime_event_count = len(self.store.branch.get("events", []))
        committed_runtime_events = len(
            runtime.get("runtime_event_db", {}).get("runtime_committed_events", [])
        )
        prepared = self._prepared_source_progress()
        canonical_percent = (
            reached * 100 / total_canonical_events
            if total_canonical_events
            else 0.0
        )
        if prepared.get("available_unknown"):
            prepared_label = (
                f"Prepared scope: {prepared['completed']} chunks "
                "(source total unavailable until the next preparation run)"
            )
        else:
            prepared_label = (
                f"Prepared source: {prepared['completed']}/{prepared['available']} "
                f"chunks ({prepared['percent']:.1f}%)"
            )
        label = (
            f"{prepared_label} | "
            f"Canonical position in prepared scope: {reached}/{total_canonical_events} "
            f"events ({canonical_percent:.1f}%) | "
            f"Runtime events: {runtime_event_count} "
            f"(sidecar commits {committed_runtime_events})"
        )
        return {
            "canonical_percent": max(0.0, min(100.0, canonical_percent)),
            "prepared_source_percent": prepared["percent"],
            "prepared_completed_chunks": prepared["completed"],
            "prepared_available_chunks": prepared["available"],
            "canonical_reached_events": reached,
            "canonical_total_events": total_canonical_events,
            "runtime_event_count": runtime_event_count,
            "sidecar_committed_event_count": committed_runtime_events,
            "label": label,
        }

    @staticmethod
    def _set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _set_progress(self, payload):
        percent = max(0.0, min(100.0, float(payload.get("percent", 0))))
        self.progress_value.set(percent)
        self.progress_text.set(payload.get("label", "Working..."))
        if self.operation_started and percent >= 2 and percent < 100:
            elapsed = time.monotonic() - self.operation_started
            remaining = elapsed * (100 - percent) / percent
            self.eta_text.set(f"ETA: {max(1, round(remaining))}s")
        elif percent >= 100:
            self.eta_text.set("ETA: complete")

    def _drain_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    self._set_progress(payload)
                elif event == "operation_done":
                    self.enter_button.configure(state="normal")
                    self.continue_button.configure(state="normal")
                    self.save_button.configure(state="normal")
                    self.progress_value.set(100)
                    self.progress_text.set(
                        "Save complete"
                        if "manual_save" in payload
                        else "Turn complete"
                    )
                    self.eta_text.set("ETA: complete")
                    self.user_input.delete("1.0", "end")
                    self._show_latest_story()
                    self._refresh_runtime_status()
                    pipeline = payload.get("pipeline", payload)
                    self._set_text(
                        self.diagnostics,
                        json.dumps(pipeline, ensure_ascii=False, indent=2),
                    )
                elif event == "operation_error":
                    self.enter_button.configure(state="normal")
                    self.continue_button.configure(state="normal")
                    self.save_button.configure(state="normal")
                    self.progress_text.set("Operation failed")
                    self.eta_text.set("ETA: stopped")
                    messagebox.showerror("Simulation error", str(payload))
                elif event == "preview":
                    self.progress_text.set("Preview ready")
                    self.eta_text.set("ETA: --")
                    self._show_text_window(payload["title"], payload["text"])
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _show_text_window(self, title, text):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("780x640")
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        output = tk.Text(frame, wrap="word")
        scroll = ttk.Scrollbar(frame, command=output.yview)
        output.configure(yscrollcommand=scroll.set)
        output.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        output.insert("1.0", text)
        output.configure(state="disabled")
        ttk.Button(frame, text="Close", command=window.destroy).grid(
            row=1, column=0, columnspan=2, pady=(8, 0), sticky="e"
        )


def main():
    checks = file_status(SIMULATION_REQUIRED_FILES)
    missing = [item for item in checks if not item["exists"]]
    root = tk.Tk()
    root.withdraw()
    if missing:
        lines = "\n".join(f"- {item['name']}: {item['description']}" for item in missing)
        messagebox.showerror(
            "Simulation files missing",
            "Run 02_prepare_simulation.bat first.\n\nMissing files:\n" + lines,
            parent=root,
        )
        root.destroy()
        return
    root.deiconify()
    SimulationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
