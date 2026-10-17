---
title: FlightPath
emoji: 🛫
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Flight recorder and replay debugger for AI agents
---

# FlightPath

**The flight recorder for AI agents.** FlightPath records every step an AI agent takes,
points to the most likely root cause of a failure in plain words, and restarts the run
from that step with one change, in a sandbox, to show whether the fix works.

Try it: choose **Scripted** or **Live AI**, pick a scenario such as *Agent bug: wrong input*,
and press **Start the run**. Open the run to see what went wrong and re-run it with the
suggested fix. The **Benchmark** page shows how often the suggested change fixes a failed
run, compared with a random change and with no change.

About this demo:

- It resets on every restart; runs you make here are not kept.
- Live AI uses a small Qwen model on this Space's CPU, so each step takes a few seconds,
  and runs are limited per visitor.
- All tools are simulated. Nothing leaves the sandbox.

Source code, method and benchmark results: [github.com/Kaushik2AI/agent-blackbox](https://github.com/Kaushik2AI/agent-blackbox).
