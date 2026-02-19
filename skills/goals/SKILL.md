# Goal Decomposition

## Description
Best practices for decomposing complex goals into executable checkpoints.

## Triggers
- goal
- plan
- long-term
- multi-step
- project
- achieve
- milestone

## Instructions

### Decomposition Principles
1. **Concrete over abstract** — Each checkpoint should produce a tangible artifact
   or verifiable outcome, not "think about X"
2. **3-10 checkpoints** — Too few = checkpoints too complex. Too many = overhead.
3. **Research before action** — First checkpoint should always gather information
4. **Verify before proceeding** — Include verification steps as success_criteria,
   not as separate checkpoints
5. **Front-load unknowns** — Put uncertain/risky checkpoints early so failure is cheap

### Success Criteria Rules
- Must be **objectively verifiable** — "file exists at path X", "3 positions found",
  "test passes"
- No subjective criteria — avoid "good quality", "well-written"
- Include quantities when possible — "at least 3", "under 500 words"

### When to Revise
- New information invalidates assumptions (company isn't hiring)
- A checkpoint reveals the plan is missing steps
- User provides feedback that changes direction
- 2+ checkpoint failures suggest wrong approach

### Anti-patterns
- Don't create a goal for tasks completable in <5 tool calls
- Don't make checkpoints that depend on external timing ("wait for response")
  — instead pause the goal and set a scheduled reminder to resume
- Don't put all complexity in one checkpoint — if a checkpoint needs 50+ tool
  calls, it should be split

## Examples

### Good Decomposition
Goal: "Get a job at company X"
1. Research X (culture, stack, recent news) — criteria: summary written
2. Find open positions — criteria: 3+ positions listed with URLs
3. Tailor resume — criteria: resume file updated, relevant skills highlighted
4. Draft cover letter — criteria: cover letter file created, <400 words
5. Submit application — criteria: confirmation page screenshot saved

### Bad Decomposition
Goal: "Get a job at company X"
1. Do research (too vague, no criteria)
2. Apply (too broad, should be multiple steps)
3. Wait for response (depends on external timing)

## Notes
- Always check if a goals/SKILL.md is relevant before creating a goal
- The goal system handles persistence, context, and auto-continuation automatically
- Use goal_status to check progress at any time
