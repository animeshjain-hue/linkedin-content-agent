# Configuration Reference

Two files control all behavior: `config.yaml` for tunables (safe to commit, no secrets) and `.env` for secrets (never commit — only `.env.example` is tracked).

---

## config.yaml

Full current contents with annotations:

```yaml
models:
  writer: "claude-opus-4-7"            # highest quality; costs more per run
  strategist: "claude-opus-4-7"        # not yet live (Phase 3)
  critic: "claude-haiku-4-5-20251001"  # fast, cheap, good enough for scoring
  ideator: "claude-haiku-4-5-20251001"
  analyst: "claude-haiku-4-5-20251001" # not yet live (Phase 3)
  evaluator: "claude-haiku-4-5-20251001"
  mapper: "claude-haiku-4-5-20251001"  # AngleMappingAgent

agent_defaults:
  temperature: 0.7          # writer + ideator; ignored by Claude 4.x (see note below)
  critic_temperature: 0.3   # CriticAgent is hardcoded to 0.0 in critic.py
  max_tokens: 2000           # global default
  ideator_max_tokens: 4096  # ideator output (5-10 verbose angles) needs more room

schedule:
  daily_run_time: "07:00"        # overridden by launchd in practice; launchd fires at 9am
  weekly_run_day: "monday"
  weekly_run_time: "08:00"
  news_poll_interval_hours: 6    # used by future always-on scheduler; launchd run fetches fresh

content:
  drafts_per_run: 2              # WriterAgent generates exactly this many drafts
  top_angles_per_run: 5          # how many angles IdeatorAgent surfaces (top 1 is used)
  auto_approve_threshold: 8.5    # Critic overall gate for Phase 4 auto-approve (unused now)

news_feeds:
  - name: et_tech
    url: "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"
  - name: yourstory
    url: "https://yourstory.com/feed"
  - name: inc42
    url: "https://inc42.com/feed/"
  - name: techcrunch_ai
    url: "https://techcrunch.com/category/artificial-intelligence/feed/"
  - name: hacker_news_top
    url: "https://hnrss.org/frontpage"
```

### Note on temperature and Claude 4.x models

Claude 4.x models (`claude-opus-4-7`, `claude-haiku-4-5-20251001`, etc.) have deprecated the `temperature` parameter. The `call_llm()` wrapper in `src/llm.py` detects the model prefix and omits `temperature` from the API call for all Claude 4.x models. The values in `config.yaml` are preserved for documentation and for future use if the model family changes.

### Adding or removing news feeds

Add an entry to `news_feeds` in `config.yaml`. No code changes required. The feed is read by `fetch_all_feeds()` in `src/inputs/news.py` at runtime. Feeds that fail (connection error, bad XML) are logged as `feed_fetch_failed` warnings and skipped — they do not abort the run.

---

## .env secrets

See `.env.example` for the full template. Values are loaded by `pydantic-settings` via `src/config.py`.

| Variable | Required | Source |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | [console.anthropic.com](https://console.anthropic.com) |
| `TELEGRAM_BOT_TOKEN` | Yes | @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | Yes | Your Telegram user ID (not the bot's) |
| `TYPEFULLY_API_KEY` | Yes | [typefully.com/api](https://typefully.com/api) |
| `OPENAI_API_KEY` | Yes (schema) | [platform.openai.com](https://platform.openai.com) — used for Whisper (Phase 4); required by Settings but not called yet |
| `DB_PATH` | No | Defaults to `data/brain.db` |
| `LOG_PATH` | No | Defaults to `logs/agent.log` |
| `LOG_LEVEL` | No | Defaults to `INFO` |

`TYPEFULLY_API_KEY` can be set to `placeholder` to run the pipeline without scheduling. `schedule_post()` in `src/outputs/typefully.py` detects the placeholder value and skips gracefully, logging `typefully_skipped`.

---

## Paths

| Path | Purpose | Git status |
|---|---|---|
| `data/brain.db` | SQLite database — all posts, engagement, news items | gitignored |
| `data/voice_guide.md` | Voice profile — loaded by WriterAgent and EvaluatorAgent | tracked |
| `data/topics.yaml` | Topic lanes, sub-topics, weights — loaded by IdeatorAgent | tracked |
| `data/strategy_current.md` | Weekly strategy doc (Phase 3, not yet generated) | gitignored |
| `data/eval_history.jsonl` | Voice-match eval results, appended per run | gitignored |
| `logs/agent.log` | Structured JSON log from structlog | gitignored |
| `logs/launchd.log` | stdout/stderr from the launchd-managed process | gitignored |
| `prompts/*.md` | All prompts with YAML frontmatter | tracked |
| `migrations/001_init.sql` | Database schema — `posts`, `engagement_snapshots`, `news_items` | tracked |

---

## Launchd plist

File location: `~/Library/LaunchAgents/com.animesh.linkedin-agent.daily.plist`

Key configuration inside the plist:

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key><integer>9</integer>
    <key>Minute</key><integer>0</integer>
</dict>
<key>StandardOutPath</key>
<string>/path/to/linkedin-agent/logs/launchd.log</string>
<key>StandardErrorPath</key>
<string>/path/to/linkedin-agent/logs/launchd.log</string>
```

To reload after editing the plist:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.animesh.linkedin-agent.daily.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.animesh.linkedin-agent.daily.plist
```

To check if it is loaded:

```bash
launchctl list | grep linkedin
```

To trigger immediately without waiting for 9am:

```bash
launchctl kickstart gui/$(id -u)/com.animesh.linkedin-agent.daily
```

---

## Prompts

All prompts live in `prompts/` as markdown files with YAML frontmatter. Example (`prompts/writer.md`):

```yaml
---
model: claude-opus-4-7
temperature: 0.7
max_tokens: 2000
version: "1.0"
---
```

The frontmatter fields are parsed by `render_prompt()` in `src/agents/base.py` and returned alongside the rendered prompt text. The `version` field is logged with every agent run under `prompt_version`. When you edit a prompt, bump the version number — this is the only way to correlate output quality changes to prompt changes in the log.

Current prompt files and their versions:

| File | Agent | Version |
|---|---|---|
| `prompts/writer.md` | WriterAgent | 1.0 |
| `prompts/critic.md` | CriticAgent | 1.0 |
| `prompts/ideator.md` | IdeatorAgent | (check frontmatter) |
| `prompts/angle_mapper.md` | AngleMappingAgent | (check frontmatter) |
| `prompts/voice_eval.md` | EvaluatorAgent | (check frontmatter) |
| `prompts/analyst.md` | AnalystAgent (Phase 3) | (check frontmatter) |
| `prompts/strategist.md` | StrategistAgent (Phase 3) | (check frontmatter) |
