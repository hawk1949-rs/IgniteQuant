---
name: "Bug report"
about: "Report a skill or workflow that routes wrong, breaks, or produces ungrounded output"
title: "Bug: <category>/<workflow> - <short summary>"
labels: ["bug"]
assignees: []
---

<!--
Use this to report defects in an existing skill or workflow: wrong routing, a
broken script, malformed output, mishandled stale data, or a guardrail bypass
(invented data, model output presented as data).
For missing data coverage, use the "Data capability request" template instead.
-->

## 1. Affected skill / workflow

- **Category**: <!-- e.g. llmquant-options -->
- **Workflow file**: <!-- e.g. workflows/iv-rank.md, or "router / SKILL.md" -->

## 2. Agent & install surface

<!--
Where it happened: Claude Code, Claude.ai, Cursor, Codex CLI, etc.
How installed: `npx skills add LLMQuant/skills`, native plugin (`/plugin install`), or manual copy.
-->



## 3. What happened

<!-- Observed behavior. Paste the prompt and the relevant part of the agent output. -->



## 4. Expected behavior

<!-- What the contract or the workflow says should have happened. -->



## 5. Defect category

<!-- Tick all that apply. -->

- [ ] **Wrong routing** — router selected the wrong workflow or none.
- [ ] **Broken script** — a `scripts/` helper errors or returns garbage.
- [ ] **Bad output format** — missing Evidence / Data Used / required structure.
- [ ] **Freshness failure** — stale data used without a notice; missing as-of dates.
- [ ] **Fallback failure** — a missing input was not surfaced; the agent continued silently.
- [ ] **Guardrail bypass** — invented data, fabricated quotes, or model output shown as data.
- [ ] **Docs / link** — broken workflow link, README table mismatch, or typo.
- [ ] **Other** (explain below).

## 6. Reproduction

<!-- Minimal steps to reproduce: tickers / inputs used, and whether LLMQuant Data was reachable. -->



## 7. Anything else

<!-- Environment, MCP availability, screenshots, or a proposed fix. -->
