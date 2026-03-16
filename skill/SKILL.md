---
name: universal-time-estimator
description: >
  Universal Time Estimator — estimate how long ANY task will take in minutes, log actual outcomes,
  review calibration accuracy, and generate full project offer estimates with buffer. Also tracks
  time per project so users can see how much time they spent on a project on any given day or date
  range. Works for all domains: React apps, Shopify stores, n8n workflows, CLI tools, infra, docs,
  GSD phases, or anything else. Use this skill whenever the user asks "how long will this take?",
  "estimate time", "log time", "record outcome", "how accurate are my estimates?", "how much time
  did I spend on X?", "project time report", "scope this project", "create an offer", "estimate
  this project", "how many hours for this project?", or any variation. Also use it when planning
  work (GSD or otherwise) and time estimates would be useful — even if the user doesn't explicitly
  ask, offer estimates when scoping multi-task plans. Use OFFER_ESTIMATE when the user is planning
  a multi-phase project, creating a proposal, or needs buffered hours for a client offer. Trigger
  on keywords: estimate, ETA, time estimate, how long, log time, log outcome, calibration, accuracy,
  time tracking, effort estimate, project time, time spent, time report, offer, proposal, scope,
  budget, quote, hours estimate, project estimate.
---

# Universal Time Estimator

You are a framework-agnostic time estimation engine. You estimate human effort (in minutes) for
any task, learn from a persistent global log, and self-correct over time.

## Data Store

All historical data lives in a single JSONL file:

```
~/.claude/universal_time_log.jsonl
```

Each line is one completed task record (JSON object). Create the file if it doesn't exist.

## Operations

This skill has five operations. Determine which one the user needs from context:

| User says... | Operation |
|---|---|
| "how long will X take?", "estimate this task", "what's the ETA?" | **ESTIMATE** |
| "log time", "record outcome", "that took X minutes", "done, took 45 min" | **LOG_OUTCOME** |
| "how accurate are estimates?", "calibration", "show estimation stats" | **CALIBRATION_SUMMARY** |
| "how much time on DealOS?", "project time report", "time spent on X this week" | **PROJECT_SUMMARY** |
| "scope this project", "estimate all phases", "create an offer", "how many hours total?" | **OFFER_ESTIMATE** |

### Choosing between ESTIMATE and OFFER_ESTIMATE

This distinction matters — getting it wrong wastes time and produces the wrong level of detail:

- **ESTIMATE** is for a single task or feature. "How long will it take to add dark mode?" → one estimate call, one result. Even if the feature has sub-parts, treat it as one task with an appropriate size_hint (L or XL for bigger features).
- **OFFER_ESTIMATE** is for multi-phase projects where the user needs a proposal-ready breakdown. Only use it when the user explicitly asks to "scope a project", "create an offer/proposal", "estimate all phases", or provides a list of distinct deliverables.

When in doubt, use ESTIMATE. It's faster and more appropriate for most requests.

---

## Operation 1: ESTIMATE

Estimate the time (in minutes) for a task the user describes.

### Step-by-step

1. **Parse the task.** Extract or ask for these fields:

   | Field | Type | Required | Description |
   |-------|------|----------|-------------|
   | `summary` | string | yes | Short description of the task |
   | `domain` | string | yes | `web_app`, `automation`, `infra`, `docs`, `design`, `data`, `devops` |
   | `framework_tags` | string[] | yes | Arbitrary tags: `["react","shopify"]`, `["n8n"]`, `["gsd","supabase"]` |
   | `artifact_type` | string | yes | `code`, `workflow`, `infra`, `doc` |
   | `size_hint` | string | yes | `XS`, `S`, `M`, `L`, `XL` |
   | `complexity` | int | yes | 1-5 (1 = trivial, 5 = novel/ambiguous) |

   If the user gives a natural-language request like "estimate how long it'll take to add dark mode to my React app", infer reasonable values and confirm them before proceeding. For example:
   - summary: "Add dark mode toggle to React app"
   - domain: "web_app"
   - framework_tags: ["react"]
   - artifact_type: "code"
   - size_hint: "M"
   - complexity: 3

2. **Run the estimator.** Execute the Python script:

   ```bash
   python3 ~/.claude/skills/universal-time-estimator/time_estimator.py estimate \
     --summary "Add dark mode toggle to React app" \
     --domain web_app \
     --framework-tags react \
     --artifact-type code \
     --size-hint M \
     --complexity 3
   ```

   The script reads the log, finds similar past tasks, computes correction factors, and returns JSON.

3. **Present the result.** Show the user a clean summary with both numbers and context:

   ```
   Time Estimate: Add dark mode toggle to React app
   -----------------------------------------------
   Low:        40 min
   Best guess: 65 min
   High:       90 min
   Confidence: 78% (based on 12 similar tasks)

   Based on:
   - "Phase 25: Dark mode fixes, mobile layout" → 45 min actual
   - "Dashboard visual polish — card shadows, spacing" → 40 min actual
   - "Accessibility compliance — aria-labels, tap targets" → 30 min actual

   Assumptions & risk factors:
   - Assumes familiarity with the existing codebase and styling approach
   - Risk: scope creep if dark mode requires rethinking component-level color tokens
   - If this is a first-time dark mode implementation (vs. fixing existing), add 30-50%
   ```

   Always include these three sections in your presentation:
   - **The numbers** (low/best/high + confidence)
   - **The basis** — show the top 2-3 similar past tasks from the `similar_examples` field in the JSON response, so the user understands where the estimate comes from
   - **Assumptions & risk factors** — briefly note what could make this take longer or shorter. Use your judgment about the task domain to add 2-3 relevant caveats. This qualitative context is just as valuable as the numbers.

   If confidence is below 0.5, note that this is a rough estimate due to limited historical data.

### How the estimation algorithm works (for your understanding)

The Python script does this internally — you don't need to reimplement it:

1. **Empirical baselines**: Computes median actual time from ALL logged tasks matching the domain+size bucket — even those logged without prior estimates. This means retroactively logged tasks (the majority of data) still improve future estimates. The empirical baseline is blended with static priors: at 3 samples it's 50/50, at 10+ samples it's almost fully empirical.

2. **Text similarity**: Uses keyword extraction (Jaccard similarity) on task summaries to find more relevant matches. A task about "dark mode fixes" will match better against past "dark mode" tasks than against unrelated ones.

3. **Dynamic spread**: The low/high range narrows as more data accumulates. With few records, it uses a fixed spread. With 5+ similar records, it computes the actual coefficient of variation from historical data and blends it in. At 15+ samples, the range is almost entirely data-driven.

4. **Complexity multiplier**: Adjusts the baseline by ±15% per complexity step from neutral (3). A complexity-2 task gets 0.85x; complexity-5 gets 1.30x. This ensures two M-sized tasks with different complexity levels produce different estimates.

5. **Correction factor**: For records that have prior estimates, computes `ratio = actual / midpoint(estimate)` and averages into a weighted correction factor (recent data weighted 2x).

6. **Fallback priors**: If fewer than 3 matching records exist, falls back to these static baselines:

  | size_hint | code | workflow | infra | doc |
  |-----------|------|----------|-------|-----|
  | XS        | 15   | 10       | 10    | 10  |
  | S         | 35   | 25       | 25    | 20  |
  | M         | 75   | 50       | 55    | 45  |
  | L         | 150  | 100      | 120   | 90  |
  | XL        | 300  | 200      | 250   | 180 |

---

## Operation 2: LOG_OUTCOME

Record how long a task actually took. This is how the estimator learns.

### Step-by-step

1. **Gather outcome data.** Extract or ask for:

   | Field | Type | Required | Description |
   |-------|------|----------|-------------|
   | `summary` | string | yes | What was done |
   | `domain` | string | yes | Same domain categories as ESTIMATE |
   | `framework_tags` | string[] | yes | Tags that apply |
   | `artifact_type` | string | yes | `code`, `workflow`, `infra`, `doc` |
   | `size_hint` | string | yes | `XS`-`XL` |
   | `complexity` | int | yes | 1-5 |
   | `estimate_low_min` | number | no | Original low estimate (if one was made) |
   | `estimate_high_min` | number | no | Original high estimate (if one was made) |
   | `actual_minutes` | number | yes | How long it actually took |
   | `status` | string | yes | `done`, `partial`, or `abandoned` |
   | `project` | string | no | Project name for time tracking (e.g. "DealOS", "Shopify Store") |
   | `id` | string | no | Auto-generated if not provided |

   If the user just says "that took 45 minutes", use context from the current conversation to fill in the other fields. If you previously gave an estimate in this session, reuse those parameters. If you know which project the user is working on (from cwd, CLAUDE.md, or conversation context), include the `--project` flag.

2. **Run the logger:**

   ```bash
   python3 ~/.claude/skills/universal-time-estimator/time_estimator.py log_outcome \
     --summary "Add dark mode toggle to React app" \
     --domain web_app \
     --framework-tags react \
     --artifact-type code \
     --size-hint M \
     --complexity 3 \
     --estimate-low 40 \
     --estimate-high 90 \
     --actual-minutes 70 \
     --status done \
     --project DealOS
   ```

3. **Confirm to the user:**

   ```
   Logged: "Add dark mode toggle to React app" — 70 min actual (estimated 40-90)
   ID: T-2026-03-08-001

   Updated stats for web_app / M:
     Tasks logged: 13
     Avg correction factor: 1.08
     Avg absolute error: 12 min
   ```

---

## Operation 3: CALIBRATION_SUMMARY

Show how well estimates have been tracking reality.

### Step-by-step

1. **Run the calibration script:**

   ```bash
   python3 ~/.claude/skills/universal-time-estimator/time_estimator.py calibration_summary
   ```

2. **Present the results** in a readable table:

   ```
   Estimation Calibration Summary
   ==============================

   By Domain + Size:
   -----------------------------------------
   web_app / S:   8 tasks, correction 1.05, avg error 8 min, trend: stable
   web_app / M:  13 tasks, correction 1.12, avg error 14 min, trend: improving
   automation / S: 5 tasks, correction 0.92, avg error 6 min, trend: stable

   By Framework Tag (top 5):
   -----------------------------------------
   react:     15 tasks, correction 1.10, avg error 12 min
   n8n:        7 tasks, correction 0.95, avg error 7 min
   gsd:       10 tasks, correction 1.08, avg error 11 min

   Overall: 35 tasks logged, mean correction factor 1.06
   ```

---

## Operation 4: PROJECT_SUMMARY

Show how much time was spent on a specific project, broken down by date.

### Step-by-step

1. **Identify the project name** from the user's request. If unclear, ask which project they mean.

2. **Run the project summary script:**

   ```bash
   python3 ~/.claude/skills/universal-time-estimator/time_estimator.py project_summary \
     --project DealOS
   ```

   Optionally filter by date range:

   ```bash
   python3 ~/.claude/skills/universal-time-estimator/time_estimator.py project_summary \
     --project DealOS \
     --from 2026-03-01 \
     --to 2026-03-08
   ```

3. **Present the results** in a readable format:

   ```
   Project Time Report: DealOS
   ===========================
   Total: 12.5 hours across 18 tasks (Mar 1 - Mar 8)

   By Date:
   -----------------------------------------
   2026-03-01:  2.3 hrs (3 tasks) — Auth middleware, JWT validation, API tests
   2026-03-03:  4.1 hrs (5 tasks) — Deal CRUD, Input forms, File upload
   2026-03-05:  3.5 hrs (6 tasks) — Output generation, SSE streaming, Chat
   2026-03-08:  2.6 hrs (4 tasks) — Profile editing, Source transparency

   By Domain:
   -----------------------------------------
   web_app:     8.2 hrs (12 tasks)
   automation:  2.8 hrs (4 tasks)
   docs:        1.5 hrs (2 tasks)
   ```

   The project name is case-insensitive, so "dealos", "DealOS", and "DEALOS" all match.

---

## Operation 5: OFFER_ESTIMATE

Estimate an entire multi-phase project and produce a proposal-ready breakdown with buffer for client offers.

This is the go-to operation when the user is planning a new project, scoping work for a proposal, or needs total hours with buffer for pricing. It runs per-task estimates through the existing engine, aggregates by phase, and adds risk-adjusted buffer automatically.

### Step-by-step

1. **Gather the project scope.** You need phases, each with tasks. There are three common sources:

   **a) GSD Roadmap** — If the project uses GSD, read the `ROADMAP.md` file. Each phase becomes a phase entry, and you break each phase's goal into estimable tasks.

   **b) User-described project** — The user describes what they need built. You break it into logical phases (e.g., "Auth & Setup", "Core Features", "Polish & Deploy") and tasks within each.

   **c) Existing task list** — The user provides a list of tasks. Group them into phases if they haven't already.

2. **Create a phases JSON file.** Write a temp file with this structure:

   ```json
   [
     {
       "name": "Phase 1: Auth & Project Setup",
       "tasks": [
         {"summary": "JWT auth middleware", "domain": "web_app", "framework_tags": ["react", "supabase"], "artifact_type": "code", "size_hint": "S", "complexity": 2},
         {"summary": "Database schema + migrations", "domain": "web_app", "framework_tags": ["supabase"], "artifact_type": "infra", "size_hint": "M", "complexity": 3}
       ]
     },
     {
       "name": "Phase 2: Core CRUD",
       "tasks": [
         {"summary": "Deal list with search/filter", "domain": "web_app", "framework_tags": ["react"], "artifact_type": "code", "size_hint": "M", "complexity": 3},
         {"summary": "Deal detail page", "domain": "web_app", "framework_tags": ["react"], "artifact_type": "code", "size_hint": "L", "complexity": 4}
       ]
     }
   ]
   ```

   Save to `/tmp/offer_phases.json` (or a project-specific temp path).

3. **Run the offer estimator:**

   ```bash
   python3 ~/.claude/skills/universal-time-estimator/time_estimator.py offer_estimate \
     --phases-file /tmp/offer_phases.json \
     --buffer 25
   ```

   Optionally include hourly rate for cost calculation:

   ```bash
   python3 ~/.claude/skills/universal-time-estimator/time_estimator.py offer_estimate \
     --phases-file /tmp/offer_phases.json \
     --buffer 25 \
     --hourly-rate 150
   ```

4. **Present the result** as a proposal-ready table:

   ```
   Project Estimate: DealOS MVP
   ============================

   Phase 1: Auth & Project Setup (2 tasks)
     JWT auth middleware                S   —   20-50 min (best: 35)   conf: 72%
     Database schema + migrations       M   —   40-80 min (best: 55)   conf: 58%
     Phase subtotal:                         —   1.0-2.2 hrs (best: 1.5 hrs)
     Buffer (25%):                           →   1.9 hrs (offer-ready)

   Phase 2: Core CRUD (2 tasks)
     Deal list with search/filter       M   —   50-100 min (best: 75)  conf: 65%
     Deal detail page                   L   —  100-200 min (best: 150) conf: 45%
     Phase subtotal:                         —   2.5-5.0 hrs (best: 3.8 hrs)
     Buffer (37.5%):                         →   5.2 hrs (offer-ready)
                                               ↑ higher buffer due to lower confidence

   ═══════════════════════════════════════════
   TOTAL (raw):        3.5 - 7.2 hrs  (best: 5.3 hrs)
   TOTAL (buffered):   7.1 hrs  ← use this for the offer
   Cost @ $150/hr:     $1,065
   ═══════════════════════════════════════════
   ```

### Buffer logic

The buffer is risk-adjusted per phase based on average confidence:

| Phase avg confidence | Effective buffer (base 25%) |
|---------------------|----------------------------|
| >= 0.7 (high)       | 25% (base)                 |
| 0.5 - 0.7 (medium)  | 31.25% (1.25x base)        |
| 0.3 - 0.5 (low)     | 37.5% (1.5x base)          |
| < 0.3 (very low)    | 50% (2x base)              |

This means phases with unfamiliar technology or novel complexity automatically get more buffer — which is exactly what you want in a client offer. You don't need to manually guess risk; the historical data does it for you.

### Buffer guidance for users

When presenting, explain the buffer to the user:
- **25% base buffer** is reasonable for known domains with historical data
- **30-40%** is appropriate for mixed familiarity or medium-complexity projects
- **50%+** is appropriate for greenfield work with no historical reference
- The user can override with `--buffer` (e.g., `--buffer 30` for a more conservative offer)
- Tell the user: "The buffered total is what you'd put in the offer. The raw estimate is your internal target."

---

## Integration with GSD Framework

When working inside GSD (plan-phase, execute-phase, etc.), use this skill to:

1. **New project scoping:** When a user starts `/gsd:new-project` or describes a new project, run OFFER_ESTIMATE to produce a full phase-by-phase estimate with buffer. This gives the user realistic hours they can use for offers/proposals before committing to the build.

2. **During planning:** For each task in a wave, run ESTIMATE with:
   - `framework_tags` including `"gsd"` plus relevant tech tags
   - Present per-task and per-wave time totals

3. **After execution:** When a phase completes, run LOG_OUTCOME for each task with actual times if the user provides them. This feeds back into future estimates, making OFFER_ESTIMATE more accurate over time.

Example GSD planning integration:
```
Wave 1 Time Estimates:
  Task 1.1: Implement auth middleware     — 35-75 min (best: 55)
  Task 1.2: Add JWT validation           — 20-45 min (best: 30)
  Wave 1 total:                           — 55-120 min (best: 85)
```

## Batch Estimation

When the user provides multiple tasks at once (common in GSD planning), run the estimator once per task and present a summary table:

```bash
# Run for each task, then aggregate
python3 ~/.claude/skills/universal-time-estimator/time_estimator.py estimate \
  --summary "Task 1" --domain web_app --framework-tags react,gsd \
  --artifact-type code --size-hint S --complexity 2
```

Present as:

```
Task Estimates Summary
======================
| # | Task                        | Low | Best | High | Confidence |
|---|-----------------------------| --- | ---- | ---- | ---------- |
| 1 | Implement auth middleware   | 35  |  55  |  75  |    72%     |
| 2 | Add JWT validation          | 20  |  30  |  45  |    65%     |
| 3 | Write integration tests     | 25  |  40  |  60  |    58%     |
|   | **TOTAL**                   | 80  | 125  | 180  |            |
```

## Edge Cases

- **No log file exists yet:** The script creates it. Fall back to generic priors. Note to the user that estimates will improve as more outcomes are logged.
- **User gives partial info:** Infer what you can from conversation context. Ask for anything critical you can't infer (especially `actual_minutes` for LOG_OUTCOME).
- **User says "that took about an hour":** Convert to minutes (60). Approximate is fine.
- **Negative or zero times:** Reject gracefully — ask the user to double-check.
- **Very old log data:** The script weights recent data more heavily (last 90 days get 2x weight).
