<!--
Thanks for contributing to LLMQuant Skills — the workflow layer for LLMQuant Data.
Contributions should make agents better at using LLMQuant Data with clear
reasoning, explicit evidence, and reproducible output.

PR title MUST follow Conventional Commits (CI-enforced):
  <type>(<scope>): <subject>
Examples:
  feat(options): add iv-term-structure workflow
  fix(macro): correct fallback when CPI release is missing
  docs: add issue and PR templates
See CONTRIBUTING.md "PR Title & Commit Conventions" for the full spec.

Read CONTRIBUTING.md for the full Required Contract and Quality Bar.
Start from templates/SKILL_TEMPLATE.md (router) or templates/WORKFLOW_TEMPLATE.md (workflow).
-->

## Summary

<!-- What does this PR add or change, and why? -->



## Type of change

- [ ] New category skill (`skills/llmquant-<category>/`)
- [ ] New workflow (`workflows/<name>.md`)
- [ ] Fix to an existing skill / workflow
- [ ] Script or asset change
- [ ] Docs / README only

## Affected categories

<!-- e.g. llmquant-options, llmquant-macro -->



## Contract checklist

<!-- See CONTRIBUTING.md -> Required Contract & Pull Request Checklist. Tick each box that applies. -->

- [ ] Category folder is named `llmquant-*`.
- [ ] Root `SKILL.md` exists and routes to the workflow.
- [ ] Workflow file added or updated under `workflows/`.
- [ ] `input_data_source: LLMQuant Data` is present in the router frontmatter.
- [ ] Required data capabilities are described in natural language (not exact MCP tool names).
- [ ] Missing or future data capabilities are explicitly named.
- [ ] Freshness rules are explicit (dates, filing periods, observation dates, stale notices).
- [ ] Fallback behavior is explicit for missing, unsupported, or stale data.
- [ ] Guardrails prevent invented data and unsupported conclusions.
- [ ] Output format is structured (Answer, Evidence, Risks/Caveats, Data Used).
- [ ] README tables updated if a category or major workflow was added, removed, or renamed.

## Evidence grounding

<!-- Confirm external facts route through LLMQuant Data and the workflow shows its evidence and data dates. Note any compatible-MCP fallback used. -->



## Linked issues

<!-- e.g. Closes #123 -->



By submitting this PR you agree that your contribution to the repository text is released under the repository [LICENSE](../LICENSE).
