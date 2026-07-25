---
name: "New skill or workflow"
about: "Propose a new llmquant-* category skill or a new workflow inside an existing category"
title: "Skill: <category> - <skill or workflow name>"
labels: ["enhancement"]
assignees: []
---

<!--
Thanks for proposing a skill or workflow. Please fill out every field below.
Read CONTRIBUTING.md for the full Required Contract and Quality Bar first.
Start from templates/SKILL_TEMPLATE.md (router) or templates/WORKFLOW_TEMPLATE.md (workflow).
-->

## 1. Proposal type

<!-- Tick exactly one. -->

- [ ] **New category skill** — a new `skills/llmquant-<category>/` router folder.
- [ ] **New workflow** — a new `workflows/<name>.md` inside an existing category.
- [ ] **Major revision** — a significant change to an existing skill or workflow.

## 2. Category

<!-- Existing category folder (e.g. `llmquant-options`), or the proposed new `llmquant-<category>` name. -->



## 3. User intent this serves

<!-- One sentence: what question or task does this answer? This becomes the Workflow Index row and/or the router `description`. -->



## 4. Routing

<!--
New workflow: which existing category router links it, and the exact Workflow Index row text
("User intent" -> `workflows/<name>.md`).
New category: which workflows it routes to first.
-->



## 5. LLMQuant Data needed

<!-- Describe data capabilities in natural language, NOT exact MCP tool names. See the LLMQuant Data Contract in CONTRIBUTING.md. -->

**Required:**



**Optional / future capabilities (not yet exposed):**



## 6. Freshness & fallback

<!--
Freshness: which dates / as-of periods / filing periods / stale notices must be reported.
Fallback: what the agent does when a required input is missing or unsupported.
-->



## 7. Output format

<!-- The structured output the workflow returns, e.g. Answer, Evidence, Scenario/Sensitivity, Risks/Caveats, Data Used. -->



## 8. Contract self-check

<!-- See CONTRIBUTING.md -> Required Contract. If any box is unchecked, justify in section 9. -->

- [ ] Folder/name follows `llmquant-*` (new category only).
- [ ] Router declares `input_data_source: LLMQuant Data` in its frontmatter.
- [ ] Data needs are described as natural-language capabilities, not MCP tool names.
- [ ] Missing or future data capabilities are named explicitly.
- [ ] Freshness and fallback behavior are explicit.
- [ ] Guardrails prevent invented data and unsupported conclusions.
- [ ] Distinct contribution — not duplicative of an existing skill or workflow.

## 9. Anything else

<!-- Optional: prior art, related workflows, sample output skeleton, scripts/assets required, waiver justification. -->



By filing this issue you agree that any contribution to the repository text is released under the repository [LICENSE](../../LICENSE).
