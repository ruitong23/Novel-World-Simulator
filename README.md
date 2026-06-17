# Novel Character Simulator

English:
README_EN.md

一个通用的小说角色模拟器与小说世界模拟器。

本项目旨在将任意小说文本自动转换为可运行的角色与世界数据，用于角色扮演、世界模拟、多 Agent 推演、RAG 检索以及 AI NPC 构建。

---

## 项目目标

输入一本小说：

```text
novel.txt
```

自动生成：

```text
world_db.json
character_state_db.json
agent_profiles.json
```

最终实现：

- AI 角色模拟
- 多 Agent 世界推演
- 小说世界状态管理
- 基于原文的 RAG 检索
- 世界规则约束
- 动态事件推进

---

## 核心能力

### 1. 小说知识图谱构建

从原文中抽取：

- 角色
- 地点
- 势力
- 法宝
- 技能
- 世界规则
- 事件
- 角色关系

构建结构化知识图谱。

### 2. Entity Resolution

自动归并不同称呼的同一实体。

例如：

```text
孙悟空
悟空
行者
美猴王
齐天大圣
```

统一映射为：

```text
孙悟空
```

归并依据不仅是名字，还包括：

- 关系
- 能力
- 物品
- 地点
- 事件链

---

### 3. Character State Builder

为每个角色构建：

- 身份
- 背景
- 性格
- 能力
- 物品
- 关系网络
- 目标
- 记忆

---

### 4. World Database Builder

构建全局世界数据库：

- 地图
- 势力
- 世界规则
- 时间线
- 能力体系
- 重大事件

---

### 5. Agent Profile Builder

生成可直接用于 LLM 的角色 Agent：

- Personality
- Speech Style
- Goals
- Relationships
- Behavior Rules
- Retrieval Tags

---

## 系统架构

```text
Novel Text
    │
    ▼
Ontology Generation
    │
    ▼
Graph Triple Extraction
    │
    ▼
Entity Resolution
    │
    ▼
Structured World Graph
    │
 ┌──┴──┐
 ▼     ▼
World DB   Character DB
      │
      ▼
Agent Profiles
      │
      ▼
Simulation Runtime
```

---

## 技术栈

- Python
- LLM
- RAG
- Knowledge Graph
- BM25
- Vector Search
- Multi-Agent System

主要组件：

- SentenceTransformers
- rank_bm25
- OpenAI Compatible API
- Local LLM (LM Studio)

---

## 当前进度

| 模块 | 状态 |
|--------|--------|
| Text Processing | ✅ |
| Hybrid Retrieval | ✅ |
| Ontology Generation | ✅ |
| Graph Extraction | ✅ |
| Entity Resolution | ✅ |
| Structured World Graph | ✅ |
| Character Database | ✅ |
| World Database | ✅ |
| Agent Profile Builder | ✅ |
| Simulation Runtime | 🚧 |

---

## 项目原则

本项目遵循以下原则：

- 不做小说摘要器
- 不做世界观总结器
- 不依赖硬编码规则
- 不依赖 Stopword 修补
- 不依赖名字相似度归并

目标是：

> 构建一个可运行的小说世界，而不是生成一本小说简介。

---

## Roadmap

- [x] Hybrid Retrieval
- [x] Graph Extraction
- [x] Entity Resolution
- [x] World Database
- [x] Character Database
- [x] Agent Profiles
- [ ] Simulation Runtime
- [ ] Event Engine
- [ ] Autonomous World Progression
- [ ] Long-Term Character Memory

---

## Vision

让任意小说自动转换为：

- 世界数据库
- 角色数据库
- Agent 系统
- 可交互模拟世界

最终实现真正意义上的：

**Novel World Simulator**
