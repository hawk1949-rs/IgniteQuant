---
name: llmquant-category-name
description: Router skill for LLMQuant category workflows. Use when the user needs ...
input_data_source: LLMQuant Data
category: category-name
---

# LLMQuant Category Name

This is the router skill for the `llmquant-category-name` category. It selects the correct workflow under `workflows/` and keeps all external evidence grounded in LLMQuant Data.

## Routing Rules

1. Identify the user's task, asset identifiers, horizon, and requested output.
2. Select the closest workflow from the index below.
3. Open only the selected workflow and any referenced local resources needed for that workflow.
4. Use LLMQuant Data as the source for external facts.
5. Report data dates, filing periods, stale notices, and missing inputs.

## Workflow Index

| User intent | Workflow |
|---|---|
| Describe the first supported task. | [`workflows/example-workflow.md`](workflows/example-workflow.md) |

## LLMQuant Data Contract

Data capabilities this category may need:
- Describe the market, filing, holdings, macro, options, portfolio, or risk data needed in natural language.
- Let the agent route to the currently available LLMQuant Data MCP tools or compatible data MCP tools.

Future or optional data capabilities:
- Describe any target data capability that is not yet available but would improve the workflow.

Fallback:
- If LLMQuant Data does not return a required input, name the missing input and continue only with retrieved evidence.
- Do not fill missing values from memory or third-party sources.

## Output Requirements

Every workflow response should include:

1. Answer or recommendation
2. Evidence table
3. Risks and caveats
4. Data used, including dates and coverage notices
