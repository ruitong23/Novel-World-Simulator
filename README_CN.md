# NavelMaker 2 Desktop 使用说明

NavelMaker 2 Desktop 是一个本地小说准备与模拟运行工具。它会把小说 TXT 抽取成多层 JSON 数据库，用于从任意原著时间点开始模拟、允许剧情分支、关系变化、能力/物品/身份变化、Agent 决策和用户干预。

## 快速开始

按顺序运行：

```bat
01_install_requirements.bat
02_prepare_simulation.bat
03_run_simulation.bat
```

`01_install_requirements.bat` 安装依赖。`02_prepare_simulation.bat` 打开准备界面，选择小说、设置比例、检查本地 LLM 后生成数据库。准备界面的 `Preview source moment` 可以在生成前扫一眼所选百分比附近约 3000 字，帮助判断当前剧情位置。`03_run_simulation.bat` 打开模拟界面。

## 本地 LLM

需要 OpenAI-compatible API，例如 LM Studio。默认配置在 `settings.json`：

```json
{
  "llm_base_url": "http://localhost:1234/v1",
  "llm_model": "gemma-4-26b-a4b-it",
  "llm_api_key": "lm-studio"
}
```

准备流程和模拟流程都会读取这套配置；环境变量 `NOVEL_LLM_BASE_URL`、`NOVEL_LLM_MODEL`、`NOVEL_LLM_API_KEY` 可覆盖它。

## 输出目录

正式输出在 `db/`：

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

`graph/` 是抽取与实体归并证据层。`canonical/` 是原著基线层，只读，其中 `canonical_scene_beat_db.json` 是从骨架证据补出的低置信剧情节拍，用来给模拟和预览提供叙事压强，不当作硬性原著事件。`agents/agent_profiles.json` 是原著角色模板，`agents/runtime_agent_state.json` 是当前动态 agent 状态，`agents/runtime_agent_dbs/` 是运行时按活跃角色生成的检索侧车。`runtime/` 是真实运行存档和事件队列。

## 核心原则

- Canonical 层是原著 baseline，不是当前世界真相。
- Runtime 层才是当前模拟真相。
- Agent Profile 是原著角色模板，不在模拟中直接修改。
- 能力、物品、关系、身份、组织、知识范围不能从原著最终状态继承。
- 当前状态必须由 cutoff_order 和已提交事件决定。
- 原著剧情线是默认路线图，不是命运；被阻断事件不会强制发生。
- 关系是事件结果驱动的多维状态，不是最终标签。

## Canonical 层

`canonical_timeline_db.json` 只保存原著默认轨道和事件引用。`canonical_event_db.json` 保存事件、触发条件、前置条件、阻断后果和 `alternative_runtime_hooks`。

资源分开存：

- `canonical_ability_db.json`
- `canonical_item_db.json`
- `canonical_relationship_db.json`
- `canonical_organization_db.json`
- `canonical_world_rule_db.json`
- `canonical_knowledge_db.json`

能力、物品、身份和关系都保留 Dependency Graph / Acquisition System 信息，包括获得、失去、使用、升级、转移条件，以及原著拥有者和模拟当前拥有者的分离。

## Runtime 层

`simulation_state_template.json` 是从 canonical cutoff 截断得到的开局模板。开始模拟后，真实存档写入：

```text
db/runtime/simulation_state.json
```

运行中还会同步写入：

- `runtime_event_db.json`
- `runtime_relationship_db.json`
- `runtime_log.json`
- `agents/runtime_agent_state.json`

所以新模拟会沿用 canonical baseline 和开局模板，但玩家行动、角色关系、资源归属、agent 动态记忆都写入 runtime，不会反写 canonical。

模拟界面的 `Preview DB anchor` 会根据当前选择的角色和剧情进度生成玩家可读的开局预览。它会优先使用角色直接出场 chunk、scene beats 和 raw graph 证据，说明角色身份、别名/形态、地点、能力、关系、前因后果和资料缺口。比如白骨精会定位到白虎岭附近，而不是只显示空泛的剧情百分比。

多轮对话后，`Save` 会生成 `runtime.recovery_snapshot`。下次打开模拟界面时，如果存在恢复摘要，界面会优先显示“上次存档回顾”，包括最近剧情总结、当前位置、附近人物和时间。每轮模拟还会更新 `recent_dialogue_turns`、`agent_memories`、`runtime_event_db.json`、`runtime_log.json` 和 per-agent sidecar DB，方便角色继续记住刚发生的事情。

## 检索与控制权

Step17 运行时会为每轮推理建立 RAG orchestration packet。玩家控制的角色是 `MANUAL`，本轮用户输入只直接接管这个角色的尝试；附近 NPC 是 `AUTO`，它们只能基于可见场景、记忆和自身检索包行动；Local World Agent 负责当前小区域环境、位置、局部事件和新出现能力/物品解释；GM Resolver 负责裁定成功、后果、因果一致性和当前原著锚点状态；Global World Agent 只在长时间跳转、旅行、离开区域或高影响事件时运行。

Actor-facing RAG packet 不包含未来原著锚点，避免角色窥探未来。系统层可以看到当前/附近锚点作为叙事压力，但 canonical 层不会直接污染 runtime 真相。

## 关系系统

Entity Resolution 前先生成 `graph/mention_weak_relations.json`。这些是 mention-level weak relations，包括同场景、称呼、动作、事件参与、地点共现、物品共用、别名、称号、变身等。它们只作为 resolver 证据，不直接进入 runtime 真相。

实体归并后，弱关系会 normalize 成 `canonical_relationship_db.json` 和 `relationship_arc_db.json`。模拟开始后，当前关系状态由 `runtime/runtime_relationship_db.json` 控制。

## 命令行测试

可以直接跑前 N 个 chunk：

```bat
python pipeline_program.py --novel "C:\path\to\novel.txt" --percent 100 --chunk-limit 20
```

`--chunk-limit 0` 表示处理所选比例内的全部 chunk。

## 上传 GitHub

要上传的源码和文档应放入仓库目录。`db/` 是运行产物，通常不需要提交，除非你想提交样例数据库。
