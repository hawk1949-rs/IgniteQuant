---
name: "Data capability request"
about: "Request or track an LLMQuant Data capability a workflow needs but cannot get yet"
title: "Data: <capability> for <category>"
labels: ["data-gap"]
assignees: []
---

<!--
Many workflows depend on LLMQuant Data capabilities. Use this template when a
workflow is blocked or degraded because a required data capability is not yet
exposed, or when you want to track a "future capability" already named in a
skill's LLMQuant Data Contract.
Native data layer: https://github.com/LLMQuant/data-mcp
-->

## 1. Capability needed

<!-- Describe the data capability in natural language: which entity, fields, frequency, and history depth. -->



## 2. Which skills / workflows need it

<!-- Category folders and workflow files that are blocked or would improve. -->



## 3. Current behavior without it

<!-- Tick one. -->

- [ ] Workflow is fully blocked (cannot run).
- [ ] Workflow runs but with a named fallback and reduced evidence.
- [ ] Workflow uses a workaround (describe in section 5).

## 4. Why it matters

<!-- What decision or output quality improves once this capability exists. -->



## 5. Workaround in the meantime

<!-- The fallback the workflow currently declares for this missing input. -->



## 6. Anything else

<!-- Links to a data-mcp issue, a sample schema, the upstream source, etc. -->
