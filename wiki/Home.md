# LinkedIn Content Agent — Wiki

This Wiki documents the design, architecture, and operation of a multi-agent LinkedIn content system built by Animesh Jain, Group PM at Tata 1mg. It is written for anyone who wants to understand how the system works, why it was built the way it was, and how to run or extend it. It assumes you are comfortable reading Python and can operate a terminal.

This system is in production. Notes reflect real decisions made on real data, not hypotheticals.

---

## Table of Contents

### Design Philosophy
Three foundational decisions that shape every other choice in the system.

| Page | Description |
|---|---|
| [The Brand Brain is the moat](Design-Philosophy#the-brand-brain-is-the-moat) | Why the memory layer — not the agents — is the durable competitive advantage, and why schema stability is the most expensive constraint to violate. |
| [Progressive autonomy — how agents earn trust](Design-Philosophy#progressive-autonomy--how-agents-earn-trust) | Why full automation is a brand risk and full human review is just a faster copy-paste tool. The case for per-dimension trust gating. |
| [Why bare Anthropic SDK](Design-Philosophy#why-bare-anthropic-sdk-not-langchain-crewai-or-langgraph) | The argument against abstraction layers when the prompt is the product. Honest about where this decision gets re-evaluated. |

---

### System Architecture
How the pieces fit together in the running system.

| Page | Description |
|---|---|
| [Pipeline overview](System-Architecture#pipeline-overview) | The full daily flow from news ingestion to Typefully scheduling: Ideator → Writer → Critic → Telegram HITL → Typefully. |
| [The Brand Brain](System-Architecture#the-brand-brain) | SQLite schema, voice guide structure, topics taxonomy, and how similarity search drives the Writer. |
| [Agent contracts](System-Architecture#agent-contracts) | How every agent is a single `run(InputModel) -> OutputModel` call, why agents never write to the DB, and what the base class enforces. |

---

### Prompt Engineering
How prompts are authored, versioned, and evaluated.

| Page | Description |
|---|---|
| [Prompt file structure](Prompt-Engineering#prompt-file-structure) | YAML frontmatter convention (`model`, `temperature`, `max_tokens`, `version`), `{variable}` placeholder system, the `render_prompt` utility. |
| [Writer prompt](Prompt-Engineering#writer-prompt) | How `prompts/writer.md` uses the voice guide, similar past posts, and topic context to generate two structurally distinct drafts. |
| [Critic prompt](Prompt-Engineering#critic-prompt) | The four scoring dimensions (hook strength, voice match, argument quality, hygiene) and how the score drives the Telegram UI. |
| [Ideator prompt](Prompt-Engineering#ideator-prompt) | How the Ideator consumes news feed items and recent posts to surface ranked angles, weighted by content lane targets from `topics.yaml`. |
| [Voice-match eval suite](Prompt-Engineering#voice-match-eval-suite) | The pytest gate that runs before any prompt version bump: 5 fixed prompts, Claude-as-judge scoring on four dimensions, −0.5 regression threshold. |

---

### Operating the System
How to run, monitor, and extend the system day-to-day.

| Page | Description |
|---|---|
| [Daily pipeline](Operating-the-System#daily-pipeline) | Running `agent run-daily`, what each step logs, and how to kill a stuck bot process. |
| [Telegram HITL flow](Operating-the-System#telegram-hitl-flow) | The ✅/✏️/❌ approval interface, the edit flow, and what happens on each action (DB status update + Typefully scheduling). |
| [Configuration reference](Operating-the-System#configuration-reference) | Every key in `config.yaml` and `.env`, with notes on which ones matter most and which are Phase 4 placeholders. |

---

### Learnings
What the data has taught us so far. Updated as engagement data accumulates.

| Page | Description |
|---|---|
| [Format performance from 47-post corpus](Learnings#format-performance-from-47-post-corpus) | Ranked format table: strategy teardowns at 228K impressions, resource roundups retired. The data behind the voice guide's format rankings. |
| [Prompt version history](Learnings#prompt-version-history) | A running log of every prompt version bump: what changed, what the eval score was before and after, and whether the change shipped. |

---

> This system is in production. Notes reflect real decisions made on real data, not hypotheticals.
