# Skeleton Step 9 Test Build

This folder is an isolated copy of `navelmaker2_desktop` for testing a faster
Step 9 graph extraction path.

## Main Changes

- Step 9 schema: `5.1-skeleton`
- One LLM call per chunk in `extract_graph_from_chunk()`
- No Step 9 world sub-pass
- No Step 9 authority sub-pass
- No Step 9 validation retry
- Default chunk size: `3000`
- Default Step 9 chunk limit: `10`
- `uncertain` is always `[]`
- `description` is capped at 20 characters
- `relation_summary` is capped at 20 characters
- Node/edge caps: 24 nodes and 36 edges per chunk

Step 9 now targets graph skeleton evidence only. Longer character/world detail
is expected to come from later aggregation and retrieval over source refs.

## Step 16/17 Retrieval Build

- Step 16 profile schema: `3.2-skeleton-retrieval`
- Agent profiles now expose:
  - `retrieval_tags`
  - `source_chunk_refs`
  - `source_evidence_refs`
  - `event_refs`
  - `needs_runtime_retrieval`
  - `runtime_retrieval`
- Step 17 builds a runtime retrieval packet for each turn:
  - `context.runtime_retrieval.source_snippets`
  - hybrid scoring from player input, scene text, graph neighbors, and source refs
  - top 3 source-grounded snippets are passed into Agent and Scene Renderer context
- Scene Renderer no longer appends continuation text to satisfy length. Short or
  looping drafts trigger a full rewrite instead.
- Scene Renderer now detects repeated narrative loops with paragraph similarity
  and repeated quote checks, then rewrites the whole draft. A final local cleanup
  removes exact or near-duplicate repeated paragraphs.
- Renderer prompts now explicitly forbid padding by looping back, paraphrasing
  the same action, or replaying the same dialogue, and they treat player input
  as the first-paragraph hard constraint.
- `simulation_state.json` is automatically backed up and rebuilt if the Agent
  Profile fingerprint changes.

## Local Test

Command:

```powershell
python -u .\pipeline_program.py --novel "C:\Users\ruitongs\Downloads\《斗罗大陆》_qinkan.net.txt" --percent 100 --chunk-size 3000 --overlap 300 --chunk-limit 10
```

Result:

- Completed Step 9-16 successfully.
- Step 9 chunks: 10/10 complete.
- Step 9 quality: 10 valid, 0 partial, 0 validation errors.
- Step 9 nodes: 72.
- Step 9 edges: 44.
- Step 9 extraction attempts: all `1`.
- Step 9 extraction mode: `single_pass_skeleton`.
- Total `uncertain`: 0.
- Generated DB files: 26.
- Step 16 identity LLM calls: 0.
