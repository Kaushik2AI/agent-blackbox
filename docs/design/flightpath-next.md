# FlightPath: the next layer

Written after the redesign in `flightpath-redesign.md` shipped. Every item is specific to
what FlightPath already records: tool calls with arguments and results, AI reasoning notes,
token counts, rule-based findings with cited steps, checkpoints, one-change re-runs and an
outcome check that knows the right answer. Each item has a cost tag: **S** (a day or less),
**M** (2-4 days), **L** (a week or more).

The one-line pitch everything below serves:
**"Your AI agent failed. FlightPath shows you the exact step, tells you why, and proves the fix, in under a minute."**

---

## 1. Ten high-impact product improvements

| # | Feature | What the user sees | Why it matters | Cost |
|---|---|---|---|---|
| 1 | **Incident replay animation** | A "Play" button on the run page. The flight path animates step by step at 1×/2×/4×, the step detail panel updates as it goes, and it pauses on the root cause with the red flag dropping in. | Turns a static page into the "watch it unfold" moment. The single best thing to screen-record for a portfolio. | M |
| 2 | **Prove the fix (repeat ×5)** | After "Fixed by one change", a button: "Run it 5 more times". Shows `5/5 passed` with five small dots. Live AI runs often show `4/5`, which is honest and impressive. | The comparison caveat already says one success is not proof. This closes the gap and makes the AI's randomness visible. | M |
| 3 | **Control re-run baseline** | Next to every fix result: "Without the change: 0/5 passed" (re-runs from the same step with nothing changed). | This is the difference between "it worked once" and "the change caused it". Recruiters who know ML will notice. | S (after #2) |
| 4 | **Fix suggestions ranked by evidence** | "Try next" shows up to three candidate changes ("Use the product code", "Pretend the stock check answered", "Skip the stock check") with a one-line reason each, and lets you run all three side by side. | Today there is one suggestion; ranking several shows FlightPath reasons about alternatives. | M |
| 5 | **Shareable incident card** | "Share" on the run page creates an image and a link: title, status, the flight path in miniature, root cause, fix result. Opens with Open Graph tags, so it previews in Slack or LinkedIn. | A failure explained in one picture is the post that gets shared. | M |
| 6 | **Failure patterns across runs** | On the Runs page: "Wrong input to the stock check: 14 runs, 9 fixed by the same change". Groups runs by root cause and by the fix that worked. | Moves FlightPath from debugging one run to understanding an agent. | M |
| 7 | **Agent version diff** | Pick two agent versions; see pass rate, most common root cause and median steps for each, plus the runs that flipped from passing to failing. | Answers "did my prompt change make things worse?", the question every agent team has. | L |
| 8 | **Prompt and tool-description editor as an intervention** | In Replay Studio, a fourth change type: "What the agent was told". Edit one sentence of the system prompt or a tool description and re-run. | Most real fixes are prompt fixes. This is the change people actually want to test. (Matches the `replace_prompt_fragment` stage in the replay contract.) | L |
| 9 | **Cost and time saved** | On every fixed run: "The fix saves 3 steps, 4.1 s and 5,440 tokens per ticket" and a projected monthly figure at a volume the viewer can edit. | Business language. A hiring manager understands money faster than SKU_REQUIRED. | S |
| 10 | **Bring your own agent (SDK quickstart)** | A "Record your own agent" page with a 6-line Python snippet (`with Recorder(...)`) and a test key; runs from outside the demo appear in Runs. | Proves FlightPath is infrastructure, not a toy wrapped around one fixture. | M |

---

## 2. Five run-page improvements

1. **Hover-to-preview on the flight path.** Hovering a waypoint shows the step detail in a
   floating card, without changing the selection. Click still pins it below. Cuts the
   click-scroll-click loop in half.
2. **"Where it went wrong" scrubber.** A thin timeline under the summary strip with one
   tick per step, coloured by outcome and sized by duration. Dragging it scrolls the
   flight path. Long runs (30+ steps) stay navigable.
3. **Root-cause spotlight mode.** Clicking "Evidence: step 2" dims every other waypoint
   to 30% opacity and draws a bracket under the evidence steps, labelled with the finding.
   Esc restores. Evidence becomes visual, not a list of numbers.
4. **Plain-language diff on retries.** Inside an expanded loop, show what changed between
   attempts. When nothing did, say so: "Attempts 2-7 were identical to attempt 1: same
   tool, same input." That sentence is the diagnosis of a retry loop.
5. **Keyboard flight.** ← → move between waypoints, Enter opens detail, `t` toggles
   Technical view, `r` opens Replay Studio on the selected step. A small "?" lists them.
   Developers notice, demos look fluent.

---

## 3. Five Replay Studio improvements

1. **Start from the step, not the studio.** Every waypoint gets "Restart here with a
   change", which opens the studio pre-set to that step and its recorded input. The
   first decision is already made.
2. **Contract-aware field editor.** Field names come from the tool contract, with
   type hints and a live check ("sku must look like SKU-..."). The server validates the
   same contract, so the button is disabled before a request can fail.
3. **Predicted path ghost.** While editing, the rest of the path after the restart
   point turns to grey dashed outlines labelled "will be re-run". It shows exactly what
   is kept and what is redone before anything runs.
4. **Live re-run on the same path.** After "Start re-run", the new waypoints land one by
   one on a second track directly under the original, aligned by step, as they happen.
   The split point is where the two tracks visibly diverge.
5. **Saved experiments.** Each re-run is listed in a strip at the top ("#1 sku = SKU-RED-004
   passed", "#2 tool answers in stock, failed") so you can compare attempts and re-open any
   one. Turns the studio into a lab notebook.

---

## 4. Five onboarding and first-run improvements

1. **Guided first incident.** The first visit opens with one line, "Want to see an AI
   agent fail and get fixed? Takes 20 seconds", and one button. It runs the scripted
   wrong-input scenario, pauses on the root cause with a single callout, then highlights
   "Try next". No setup choices on the first run.
2. **Three hotspot callouts, once.** Small numbered dots on the summary strip, the root
   cause card and the flight path, each with a one-sentence explanation. Dismissed for
   good after one look. Never a modal tour.
3. **Pre-recorded showcase runs.** Runs page ships with four labelled examples (wrong
   input, mixed-up orders, system down, recovered timeout) so a visitor who never presses
   "Start" still sees the product working.
4. **Live AI honesty banner.** When the Live AI is selected: "This is a real model. It
   may succeed, fail differently or fail in a new way. That's the point." Sets
   expectations and turns randomness into a feature.
5. **"Explain this page" in Simple view.** A small link on each page that expands a
   three-sentence description of what the page answers. Gone in Technical view.

---

## 5. Five technical-mode improvements

1. **Prompt inspector.** For each AI decision: the exact messages sent (system, ticket,
   prior results), the raw reply and the parsed action, side by side, with token counts per
   message. Today only the note and total tokens are shown.
2. **Span waterfall.** A Gantt-style view of spans with real durations (AI vs tool time),
   next to the graph. Latency problems show up immediately.
3. **Copy as reproduction.** One button that copies a `curl` for the replay API (checkpoint
   id, intervention JSON, idempotency key) and a `pytest` snippet that asserts the fixed
   outcome. Turns a fix into a regression test.
4. **Detector transparency.** Each finding shows the rule it applied and the measured
   precision and recall from `make eval-detectors`, with a link to the labelled cases. A
   developer can judge how far to trust it.
5. **OpenTelemetry export.** "Download trace (OTLP JSON)" so a run can be opened in
   Jaeger or any OTel tool. Shows the event contract is real and portable.

---

## 6. Empty, failure and success states

| State | Copy and behaviour |
|---|---|
| Runs page, no runs | "No flights recorded yet. Start one from the live demo, or record your own agent with the SDK." Two buttons. The metric strip shows dashes, not zeros. |
| Run passed, no findings | Green summary strip, "Handled correctly. No problems found on the way." Replay tab: "Nothing to fix. Test how sensitive this run is: change one step and see if it still passes." |
| Run passed with warnings | Strip says "Passed with 1 warning" in orange. Answer card: "It got there, but a system timed out once. A retry fixed it." |
| No finding matched a failure | "None of the automatic checks matched. That's rare, and worth a look." Path is still shown; the most suspicious step (first error, or last step before the end) gets a grey "Start here" flag. |
| Live AI unreachable | Live AI tile reads "AI server is not running" and is disabled; one line below: "The scripted agent works without it." No error banner. |
| Re-run failed to start | Inline in the review panel, red: the server's reason in plain words ("sku must look like SKU-..."), with the field highlighted. Never a toast that disappears. |
| Fix worked | Green "Fixed by one change", before → after pills, then "Prove it: run 5 more times" (#2). |
| Fix didn't work | "Still failing after this change." Show where the new path failed and offer the next ranked suggestion (#4): "Try: pretend the stock check answered." |

---

## 7. Small premium touches

- The root-cause flag drops onto its waypoint with a 200 ms settle when the analysis
  finishes. The only celebratory motion on the page.
- When a fix passes, the red dashed track behind the original path re-draws as a solid
  green track up to the landing square, once.
- Holding pattern: the loop node's dashed ellipse rotates slowly (8 s per turn) while the
  run is still looping live. Stops when it lands.
- Copy buttons on IDs say "Copied" in place for one second instead of showing a toast.
- The tab title shows status during a live run: "● Recording · FlightPath", then
  "✕ Failed · Wrong input" when it lands, so a background tab tells you the result.
- Numbers in the summary strip count up from 0 over 300 ms on first load only.

---

## 8. Simple mode vs Technical mode

| Element | Simple | Technical |
|---|---|---|
| Step titles | "Check stock for “red backpack”" | Same, plus `lookup_inventory` chip and the raw arguments |
| Errors | "The stock system needs a product code" | Plus `SKU_REQUIRED` and the tool's error message |
| AI | "Thinking: check whether a new red backpack is in stock" | Plus tokens per decision, latency, prompt inspector link |
| Findings | Cause and symptoms in plain words | Detector id, version, explanation, cited span ids, precision/recall |
| Replay Studio | Field editor with recorded vs new values | JSON editor with contract schema and a copyable request |
| Comparison | Before / change / after cards and aligned paths | Plus sandbox diff, span graphs, replay class |
| IDs | Hidden | Run, span and job ids with copy buttons |

Rule: Technical view adds; it never removes or reorders. Anyone can switch mid-task
without losing their place.

---

## 9. Metrics and visual summaries

- **Recovery rate**: share of failed runs where a one-change re-run passed. Headline number on Runs.
- **Mean steps to failure**: how far agents get before the root cause, per scenario.
- **Loop waste**: steps and tokens spent repeating identical failing calls. "Loops wasted 1,240 steps and 310k tokens this week."
- **Fix stability**: for each fix, passes out of 5 repeats (#2) next to the control (#3).
- **Root-cause mix**: a single horizontal bar split by cause, clickable to filter runs.
- **Pass rate by agent version**: a small sparkline per version on the Runs page.
- **Time to diagnosis**: from run end to the first time someone opened its root cause. A product metric, shown to the team.

---

## 10. What to build next, in order

1. **Prove the fix + control baseline** (#2, #3). Small, and it turns "it worked once" into evidence. Strongest signal for ML-savvy viewers.
2. **Incident replay animation** (#1) and **shareable incident card** (#5). The demo video and the post.
3. **Failure patterns across runs** (#6). Makes FlightPath about agents, not single runs.
4. **Bring your own agent** (#10). Proves it is infrastructure.
5. **Prompt intervention** (#8) and **agent version diff** (#7). The features a real agent team would pay for.
