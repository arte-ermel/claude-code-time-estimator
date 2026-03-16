# Claude Code Time Estimator

A self-correcting time estimation skill for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Estimates how long any task will take, learns from your actual outcomes, and gets more accurate over time.

## Install

```bash
npx @arte-ermel/claude-code-time-estimator
```

This copies the skill into `~/.claude/skills/universal-time-estimator/`. No dependencies required — just Python 3 (for the estimation engine) and Claude Code.

> **Note:** This package is hosted on [GitHub Packages](https://github.com/arte-ermel/claude-code-time-estimator/packages). If you haven't used GitHub Packages before, you may need to configure npm to use the GitHub registry for the `@arte-ermel` scope:
> ```bash
> echo "@arte-ermel:registry=https://npm.pkg.github.com" >> ~/.npmrc
> ```

## What It Does

- **Estimate** how long a task will take (low / best guess / high + confidence score)
- **Log outcomes** to teach the estimator how long things actually take
- **Calibration stats** to see how accurate your estimates have been
- **Project time tracking** to see how much time you've spent on a project by day
- **Offer estimates** for multi-phase projects with risk-adjusted buffers

## Usage

Once installed, just talk to Claude Code naturally:

```
How long will it take to build a checkout page in React?
```

```
That took 45 minutes, log it
```

```
Show my estimation accuracy stats
```

```
How much time did I spend on MyProject this week?
```

```
Scope this project and give me an estimate for all phases
```

## How It Works

The estimator uses a multi-signal algorithm that improves with every logged outcome:

1. **Empirical baselines** — Computes median actual time from all logged tasks in a matching domain+size bucket. Blends with static priors when data is sparse.

2. **Text similarity** — Uses keyword extraction (Jaccard similarity) on task summaries to find the most relevant past tasks.

3. **Dynamic spread** — The estimate range (low–high) narrows as more data accumulates. With 15+ similar tasks, the range is almost entirely data-driven.

4. **Complexity multiplier** — Adjusts baseline by ±15% per complexity step. A complexity-2 task gets 0.85x; complexity-5 gets 1.30x.

5. **Correction factor** — For tasks with prior estimates, computes `actual / estimated` ratios and applies a weighted correction to future estimates. Recent data (last 90 days) is weighted 2x.

6. **Fallback priors** — With fewer than 3 similar records, uses static baselines:

| Size | Code | Workflow | Infra | Doc |
|------|------|----------|-------|-----|
| XS   | 15   | 10       | 10    | 10  |
| S    | 35   | 25       | 25    | 20  |
| M    | 75   | 50       | 55    | 45  |
| L    | 150  | 100      | 120   | 90  |
| XL   | 300  | 200      | 250   | 180 |

## Fields Reference

| Field | Values | Description |
|-------|--------|-------------|
| `domain` | `web_app`, `automation`, `infra`, `docs`, `design`, `data`, `devops` | What kind of work |
| `framework_tags` | Any strings | Arbitrary tags: `react`, `n8n`, `shopify`, etc. |
| `artifact_type` | `code`, `workflow`, `infra`, `doc` | What you're producing |
| `size_hint` | `XS`, `S`, `M`, `L`, `XL` | T-shirt size of the task |
| `complexity` | 1–5 | 1 = trivial, 5 = novel/ambiguous |

You don't need to specify these manually — Claude Code infers them from your natural language description and confirms before estimating.

## Data Storage

All your time data is stored locally in a single file:

```
~/.claude/universal_time_log.jsonl
```

Each line is a JSON record. Your data never leaves your machine. You can inspect, back up, or delete it at any time.

## CLI Usage

You can also run the estimator directly:

```bash
# Estimate a task
python3 ~/.claude/skills/universal-time-estimator/time_estimator.py estimate \
  --summary "Build checkout page" \
  --domain web_app \
  --framework-tags react,shopify \
  --artifact-type code \
  --size-hint M \
  --complexity 3

# Log an outcome
python3 ~/.claude/skills/universal-time-estimator/time_estimator.py log_outcome \
  --summary "Build checkout page" \
  --domain web_app \
  --framework-tags react,shopify \
  --artifact-type code \
  --size-hint M \
  --complexity 3 \
  --actual-minutes 80 \
  --status done

# View calibration stats
python3 ~/.claude/skills/universal-time-estimator/time_estimator.py calibration_summary

# Project time report
python3 ~/.claude/skills/universal-time-estimator/time_estimator.py project_summary \
  --project MyProject --from 2025-01-01 --to 2025-01-31
```

## Uninstall

```bash
npx @arte-ermel/claude-code-time-estimator --uninstall
```

This removes the skill files but preserves your time log data.

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python 3.6+
- Node.js 14+ (for installation only)

## License

MIT
