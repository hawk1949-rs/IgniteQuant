# Workflow Name

## Use When

Use this workflow when the user asks for ...

## LLMQuant Data Needed

Required:
- Describe the required data capability in natural language, including why it is needed.

Optional or future:
- Describe optional or future data capabilities, including how they would be used.

Freshness:
- State observation dates, filing periods, as-of dates, and stale-data notices.

Fallback:
- If a required input is unavailable, name the missing LLMQuant Data input and continue only with retrieved evidence.

## Workflow

1. Confirm identifiers, horizon, and output target.
2. Pull required LLMQuant Data.
3. Check coverage, dates, and missing fields.
4. Separate evidence from interpretation.
5. Produce the output format below.

## Output Format

1. **Answer**
2. **Evidence**
3. **Scenario / Sensitivity**
4. **Risks / Caveats**
5. **Data Used**

## Guardrails

- Do not invent missing values.
- Do not present model output as data.
- Do not make personalized financial advice claims.
