# FlightPath redesign

**FlightPath: the flight recorder for AI agents.**
This document is the plan for the redesign that ships in `apps/web`. Every decision
below is implemented. Where a decision was forced by the data we have, it says so.

---

## 1. Redesign plan

### The problem with the old UI

| Symptom | Cause | Decision |
|---|---|---|
| Feels like a log viewer | Steps were a vertical list, one row per event | Steps become a **horizontal flight path**: waypoints on one line, read left to right like a timeline |
| Long scroll | Story, diagnosis, fix, facts and trace stacked vertically | One screen per question, split into **tabs**. Above the fold: summary strip, three answer cards, the path |
| Hard to understand | Detector wording, error codes and IDs shown first | **Simple view by default.** Codes, tool names, tokens and JSON only in **Technical view** or behind "Show raw data" |
| 7 identical red rows | Every retry rendered | Identical failing attempts fold into one **loop cluster** ("Stuck in a loop, 7 tries") |
| "What do I do now?" | The fix was a side panel | A **recommended action** in the summary strip and a "Try next" card, one click to run |
| Replay felt like a form | Radio list + raw JSON textarea | **Guided workflow**: pick a waypoint on the path, edit fields, read a one-sentence summary, start |

### The four questions, and where each is answered

| Question | Answered by | Where |
|---|---|---|
| What happened? | "In simple words" card + flight path | Run page, Story tab, above the fold |
| Why did it fail? | Root cause card (cause, evidence step, symptoms kept separate) | Story tab; full evidence in the Evidence tab |
| What should I try next? | Recommended action in the summary strip + "Try next" card | Story tab and Replay tab |
| What changed in the replay? | Before / change / after cards + two aligned flight paths | Comparison page and inline after a one-click fix |

### Root cause vs symptoms (a product decision, not a style one)

A failed run usually trips several detectors. Showing them as a flat list of equal red
bullets hides the story. FlightPath ranks them:

1. **Root cause** (one): the first thing that went wrong. Priority:
   order mix-up > wrong input to a tool > a system not answering > repeated step > ran out of steps.
2. **Symptoms** (the rest): consequences, shown as grey chips under the cause ("then: stuck in a loop", "then: ran out of steps").

The root-cause waypoint gets a red ring and a "Root cause" flag on the path. This is
derived from rule-based detectors, so the card says "most likely cause", not "the cause".

---

## 2. Information architecture

```
FlightPath
├── Live demo  (/)                       give the agent a ticket, watch it fly
├── Runs       (/runs)                   every recorded run, with a summary on top
│   └── Run    (/runs/:id)               one run
│       ├── Story            (default)   summary strip, 3 answer cards, flight path, step detail
│       ├── Replay           ?tab=replay recommended fix, re-runs of this run, "design your own"
│       ├── Technical trace  ?tab=trace  event log, span graph, span inspector, raw payloads
│       ├── Evidence         ?tab=evidence  every finding with the steps it cites
│       └── Replay Studio    (/runs/:id/replay)  guided: restart point, change, review and run
│           └── Comparison   (/replays/:job)     before / change / after, two aligned paths
└── System status (/system)              behind the status dot, not in the main nav
```

- Tabs are URL state (`?tab=`), so a teammate can be sent straight to the trace.
- **Simple view / Technical view** is one global switch, remembered per browser. It
  changes density, not structure: the same pages, more or less detail.
- The technical trace is a tab, not a separate page: the run context (strip, title)
  stays on screen.

---

## 3. Component hierarchy

```
AppShell
├── TopBar: Logo (FlightPath mark), Nav [Live demo, Runs], ViewModeToggle, StatusDot
└── <page>

HomePage (LiveDemo)
├── HeroRow: Headline + HowItWorks (3 inline steps)
├── LaunchBar: AgentPicker | SituationTiles (6 tiles, one row) | CustomerMessage | RunButton
├── Stage
│   ├── StageHeader: RecordingLight, Clock, Situation
│   └── FlightPath (live: waypoints appear as they happen)
└── AnswerRow (after landing): SimpleWordsCard | RootCauseCard | NextStepCard

RunsPage (RunsExplorer)
├── PageHeader + Filters
├── MetricStrip: Runs, Success rate, Median time, Most common problem
└── RunTable: RunRow (status, situation, problem, agent, steps, when)

RunPage (RunView)
├── RunHeader: back link, title, status pill, re-run badge
├── SummaryStrip: Status | Situation | Model | Steps | Time | Tokens | Root cause | Recommended action
├── Tabs [Story, Replay (n), Technical trace, Evidence (n)]
├── StoryTab
│   ├── AnswerRow: SimpleWordsCard | RootCauseCard | NextStepCard
│   ├── FlightPath: Waypoint · LoopCluster · Landing
│   └── StepDetail: Thinking (purple) | Sent (blue) | Got back (green/red) | raw data
├── ReplayTab: NextStepCard (wide) + ReplayHistory (before → after cards) + StudioCTA
├── TraceTab: EventLog | SpanGraph | SpanInspector   (the existing technical tools)
└── EvidenceTab: FindingCard[] (role: cause/symptom, evidence step chips, detector, caveats)

ReplayStudio
├── StudioHeader + Stepper (1 Restart point, 2 Change one thing, 3 Review and run)
├── RestartPath: FlightPath of checkpoints, pick a waypoint
├── ChangePanel: ChangeKindTabs + FieldEditor (or JSON editor in Technical view) + SuggestedFixButton
├── ReviewPanel: one-sentence summary, SafetyChecks, Start re-run
└── ReplayResult: before → after mini cards, Compare link

ComparisonPage
├── VerdictBanner
├── BeforeChangeAfter: OutcomeCard | ChangeCard | OutcomeCard
├── AlignedPaths: Before row / After row, one column per step, divergence marked
└── TechnicalDetails (collapsed): sandbox diff, span graphs, caveat
```

---

## 4. Page layouts

All pages: max width 1280px, 24px gutters (16px on phones). Content is left-aligned.

### Run page (the centre of the product)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ← Runs   Broken zip, wants an exchange   [Failed]          Simple | Technical│
├──────────────────────────────────────────────────────────────────────────────┤
│ Failed │ Exchange ticket │ Qwen2.5 1.5B │ 8 of 8 │ 7.3 s │ 9,360 │ Root cause:        │ [Try the fix] │
│        │                 │              │ steps  │       │ tokens│ wrong input to the │               │
│        │                 │              │        │       │       │ stock check        │               │
├──────────────────────────────────────────────────────────────────────────────┤
│ Story   Replay 1   Technical trace   Evidence 3                              │
├────────────────────────┬───────────────────────────┬─────────────────────────┤
│ In simple words        │ Most likely cause         │ Try next                │
│ The agent found the    │ Wrong input to the stock  │ Use the product code    │
│ order, then asked the  │ check (step 2)            │ SKU-RED-004             │
│ stock system about...  │ then: stuck in a loop ... │ [Re-run from step 2]    │
├────────────────────────┴───────────────────────────┴─────────────────────────┤
│ ●──────────●═══════════════════════════●───────────■                         │
│ 1 Look up  2 Check stock  ⟲ ×6         Out of steps                          │
│ order ✓    ✗ Root cause   Stuck in a loop                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│ Step 2: Thinking (purple) │ Sent (blue) │ Got back (red)   [Show raw data]  │
└──────────────────────────────────────────────────────────────────────────────┘
```

Everything a first-time viewer needs is above the fold on a 1366×768 laptop: the strip,
the three answers and the path. The step detail sits under the path, not in a modal.

### Home

```
Headline (left)                         How it works: 1 Ticket → 2 Recording → 3 What broke
[Agent: Live AI | Scripted]  [6 situation tiles in one row ..................]  [Run]
[Customer message (Live AI only) .........................................]
┌ Stage ─ ● Recording 00:04.2 ──────────────────────────────────────────────┐
│ ●────●────●────...   (waypoints appear live)                                │
└─────────────────────────────────────────────────────────────────────────────┘
[In simple words] [Most likely cause] [Try next]           (after the run lands)
```

### Replay Studio

```
1 Restart point ── 2 Change one thing ── 3 Review and run
┌ Pick where to restart ─────────────────────────────────────────────────────┐
│ ●──────●(restart here)──────●──────●──────●                                  │
└─────────────────────────────────────────────────────────────────────────────┘
┌ Change one thing ──────────────────────┐ ┌ Review and run ─────────────────┐
│ (•) What the agent sends               │ │ Restart before step 2 and send  │
│ ( ) What the tool answers              │ │ sku = SKU-RED-004 instead of    │
│ ( ) Nothing, just re-run               │ │ product_name = red backpack.    │
│ field        original      new         │ │ ✓ new recording ✓ sandboxed ... │
│ product_name red backpack  [remove]    │ │ [Start re-run]                  │
│ sku          —             SKU-RED-004 │ │ result: Failed → Passed         │
│ [Use suggested fix]  [+ Add field]     │ └─────────────────────────────────┘
└────────────────────────────────────────┘
```

### Comparison

```
Fixed by one change.  Restarted before step 2. The runs split at step 2.
[Before: Failed, 8 steps, 7 errors] [Change: step 2, product_name → sku] [After: Passed, 5 steps]
Step        1        2               3            4          5          6 ...
Before   ● Order  ✗ Stock (name)  ✗ Stock     ✗ Stock    ✗ Stock    ...
After    ● same   ✓ Stock (code)  ✓ Policy    ✓ Reply    ✓ Close
▸ Technical details (sandbox changes, span graphs)
```

---

## 5. Microcopy

Rules: sentence case; verbs that say what happens; the same name for an action through
the whole flow; no internal names (span, fork, verifier, intervention) in Simple view.

| Where | Old | New |
|---|---|---|
| Nav | Try it / All runs | Live demo / Runs |
| Run button | Run the agent | Start the run |
| Running | Agent is working… | In the air… |
| Repeated rows | (7 rows) | **Stuck in a loop**. Tried the same thing 7 times. Rejected every time. [Show all 7] |
| Diagnosis title | What went wrong | **Most likely cause** (+ "then:" symptom chips) |
| Explanation | (none) | **In simple words** |
| Fix | Try a fix / Re-run from step 2 with this fix | **Try next** / Re-run from step 2 with this change |
| Fix result | The fix worked | **Fixed by one change** / **Still failing after this change** |
| Fork | Fork / re-run with a fix | Re-run (badge), "Re-run of [original]" |
| Verifier | Checker: passed | Outcome check: passed (Technical: verifier) |
| Checkpoint | before call #1 | Restart before step 2 |
| Intervention kinds | Replace tool arguments / result | What the agent sends / What the tool answers / Nothing, just re-run |
| Replay submit | Run replay → Confirm | Start re-run (the review panel is the confirmation) |
| Empty runs | No runs yet | No runs yet. Start one from the live demo and it appears here. [Open the live demo] |
| Not replayable | This run can't be re-run | This run was recorded without its data, so it can't be restarted. Runs started from the live demo always can. |
| AI note | AI's reason: | Thinking: |
| Comparison caveat (scripted) | Deterministic replay: ... | The scripted agent is exact, so this result repeats every time. |

---

## 6. Design system

**Colour means something, always.** Neutral UI; colour only for meaning:

| Token | Hex | Meaning |
|---|---|---|
| `canvas` | `#F4F5F8` | page background (cool, not cream) |
| `surface` | `#FFFFFF` | cards |
| `sunken` | `#EDEFF3` | wells, code, track |
| `line` / `line-strong` | `#E0E3EA` / `#C9CED8` | borders |
| `ink` / `ink-2` / `ink-3` | `#151A24` / `#485063` / `#737B8E` | text: primary / secondary / hidden-detail grey |
| `context` | `#2160C4` (tint `#EAF1FC`) | context: situation, what was sent, your change |
| `ai` | `#6A3BD2` (tint `#F1ECFC`) | AI reasoning, model, tokens |
| `ok` | `#11774A` (tint `#E6F4EC`) | success |
| `warn` | `#AD5208` (tint `#FCF0E3`) | warning: timeouts, slow, partial |
| `bad` | `#C4302A` (tint `#FBEAE9`) | failure, root cause |

Primary buttons are ink (`#151A24`), so no brand colour competes with the semantics.

**Type.** One family, Instrument Sans (variable weight and width), bundled locally.
Its condensed width (wdth 82) is used for big numbers in the summary strip, which reads
like an instrument panel. JetBrains Mono only for real data: IDs, arguments, JSON.

| Role | Size / line | Weight |
|---|---|---|
| Page title | 30 / 36 | 600 |
| Section / card title | 17 / 24 | 600 |
| Body | 15 / 22 | 400 |
| Secondary | 13.5 / 20 | 400 |
| Strip value | 22 / 26, wdth 82 | 600 |
| Data (mono) | 12.5 / 18 | 400 |

**Spacing.** 4px base; steps 4, 8, 12, 16, 24, 32, 48. Cards pad 16-20px.

**Radius by role.** Pills 999px, controls 8px, cards 12px, the stage 16px.

**Elevation.** Borders, not shadows. A shadow appears only on the selected waypoint
and on floating layers.

**Pills and badges.** `StatusPill` (dot + word): Passed, Failed, Running, Queued.
`Pill tone=context|ai|ok|warn|bad|neutral` for tags. Error codes are neutral mono
chips, shown only in Technical view or next to plain text.

**Motion.** One moment: a waypoint drops onto the path as it is recorded during a live
run. Everything else is instant. `prefers-reduced-motion` turns it off.

---

## 7. React structure

```
apps/web
├── app/                       routes unchanged (/, /runs, /runs/[id], /runs/[id]/replay, /replays/[jobId])
├── lib/
│   ├── story.ts       NEW  beats (loop clusters), root cause vs symptoms, plain summary, step numbers
│   ├── view-mode.ts   NEW  useViewMode(): "simple" | "technical", remembered in localStorage
│   ├── describe.ts         plain wording (steps, findings, outcomes)
│   └── steps.ts            TapeStep from live records / stored events, findRepeats
└── components/
    ├── ui.tsx              Button classes, StatusPill, Pill, Card, Tabs, Segmented, Stat
    ├── nav.tsx             TopBar with FlightPath mark + ViewModeToggle
    ├── flight-path.tsx NEW FlightPath, Waypoint, LoopCluster, Landing, StepDetail
    ├── answers.tsx     NEW SimpleWordsCard, RootCauseCard, NextStepCard (one-click fix)
    ├── summary-strip.tsx NEW
    ├── run-view.tsx    NEW the run page with its four tabs (replaces inspector.tsx)
    ├── trace.tsx       NEW EventLog, SpanInspector (moved from the inspector)
    ├── live-demo.tsx       home
    ├── replay-studio.tsx   guided workflow
    ├── comparison-view.tsx before / change / after + aligned paths
    └── runs-explorer.tsx   metric strip + table
```
