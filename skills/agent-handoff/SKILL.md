---
name: agent-handoff
description: Standardized handoff templates for agent-to-agent work transfer, QA feedback loops, escalations, and phase gates. Adapted from msitarzewski/agency-agents.
---

## Triggers

- agent handoff
- work transfer
- QA feedback
- task handoff
- phase gate handoff
- sprint handoff
- incident handoff
- escalation report
- QA pass
- QA fail
- task escalation
- context transfer
- agent coordination
- handoff template
- work assignment

## Instructions

Consistent handoffs prevent context loss — the number one cause of multi-agent coordination failure. Use these templates for every agent-to-agent transfer. Apply via `organization_delegate` or `knowledge_write` as appropriate.

### 1. Standard Handoff Template

Use for any agent-to-agent work transfer:

```
NEXUS Handoff Document

Metadata:
- From: [Agent Name] ([Division])
- To: [Agent Name] ([Division])
- Phase: Phase [N] — [Phase Name]
- Task Reference: [Task ID]
- Priority: [Critical / High / Medium / Low]
- Timestamp: [ISO 8601]

Context:
- Project: [Name]
- Current State: [What has been completed — be specific]
- Relevant Files: [file paths with descriptions]
- Dependencies: [What this depends on]
- Constraints: [Technical, timeline, resource]

Deliverable Request:
- What is needed: [Specific, measurable deliverable]
- Acceptance criteria: [Measurable criteria list]
- Reference materials: [Links to specs, designs, previous work]

Quality Expectations:
- Must pass: [Specific quality criteria]
- Evidence required: [What proof looks like]
- Handoff to next: [Who receives output, what format needed]
```

### 2. QA Feedback Loop — PASS

Use when Evidence Collector or other QA agent approves a task:

```
NEXUS QA Verdict: PASS

Task: [ID] — [Description]
Developer Agent: [Name] | QA Agent: [Name]
Attempt: [N] of 3

Evidence:
- Screenshots: Desktop (1920x1080), Tablet (768x1024), Mobile (375x667)
- Functional: [All acceptance criteria verified]
- Brand Consistency: Verified (colors, typography, spacing)
- Accessibility: Verified (keyboard, contrast, semantic HTML)
- Performance: [Load time measured, within range]

Notes: [Observations, minor suggestions, positive callouts]
Next Action: Orchestrator marks complete, advances to next task.
```

### 3. QA Feedback Loop — FAIL

Use when QA rejects a task:

```
NEXUS QA Verdict: FAIL

Task: [ID] — [Description]
Developer Agent: [Name] | QA Agent: [Name]
Attempt: [N] of 3

Issues Found:
Issue 1: [Category] — [Severity: Critical/High/Medium/Low]
- Description: [Exact problem]
- Expected: [Per acceptance criteria]
- Actual: [What happens]
- Evidence: [Screenshot/test output]
- Fix instruction: [Specific, actionable]
- Files to modify: [Exact paths]

Acceptance Criteria Status:
- [x] [Criterion 1] — passed
- [ ] [Criterion 2] — FAILED (see Issue 1)

Retry Instructions:
1. Fix ONLY the listed issues
2. Do NOT introduce new features or changes
3. Re-submit when all issues addressed
4. This is attempt [N] of 3 maximum
If attempt 3 fails: Escalation to Agents Orchestrator
```

### 4. Escalation Report

Use when a task exceeds 3 retry attempts:

```
NEXUS Escalation Report

Task: [ID] — [Description]
Developer Agent: [Name] | QA Agent: [Name]
Attempts Exhausted: 3/3
Escalation To: [Orchestrator / Studio Producer]

Failure History:
- Attempt 1: Issues [summary], fixes applied [summary], result FAIL [why]
- Attempt 2: Issues [summary], fixes applied [summary], result FAIL [why]
- Attempt 3: Issues [summary], fixes applied [summary], result FAIL [why]

Root Cause Analysis:
- Why task keeps failing: [Analysis]
- Systemic issue: [One-off or pattern?]
- Complexity assessment: [Properly scoped?]

Recommended Resolution:
- [ ] Reassign to different developer agent
- [ ] Decompose into smaller sub-tasks
- [ ] Revise approach (architecture/design change)
- [ ] Accept current state with documented limitations
- [ ] Defer to future sprint

Impact: Blocking [tasks], Timeline impact [assessment], Quality impact [assessment]
Decision needed by: [Deadline]
```

### 5. Phase Gate Handoff

Use when transitioning between phases:

```
NEXUS Phase Gate Handoff

From Phase: [N] — [Name]
To Phase: [N+1] — [Name]
Gate Keeper(s): [Agent Names]
Gate Result: [PASSED / FAILED]

Gate Criteria Results:
| Criterion | Threshold | Result | Evidence |
|-----------|-----------|--------|----------|
| [Criterion] | [Threshold] | PASS/FAIL | [Reference] |

Documents Carried Forward:
1. [Document] — [Purpose for next phase]

Key Constraints: [From this phase's findings]

Agent Activation for Next Phase:
| Agent | Role | Priority (Immediate/Day 2/As needed) |

Risks Carried Forward:
| Risk | Severity | Mitigation | Owner |
```

### 6. Sprint Handoff

Use at sprint boundaries:

```
NEXUS Sprint Handoff

Sprint: [Number] | Duration: [Start] -> [End]
Sprint Goal: [Statement]
Velocity: [Planned] / [Actual] story points

Completion Status:
| Task ID | Description | Status | QA Attempts | Notes |

Quality Metrics:
- First-pass QA rate: [X]%
- Average retries: [N]
- Tasks completed: [X/Y]
- Story points delivered: [N]

Carried Over: [Tasks with reasons and RICE scores]

Retrospective:
- What went well: [Successes]
- What to improve: [Improvements]
- Action items: [Specific changes]

Next Sprint: [Goal, key tasks, dependencies]
```

### 7. Incident Handoff

Use during incident response:

```
NEXUS Incident Handoff

Severity: [P0-P3]
Detected by: [Agent or system]
Detection time: [Timestamp]
Assigned to: [Agent]
Status: [Investigating / Mitigating / Resolved / Post-mortem]

What happened: [Description]
Impact: [Who/what affected, severity]
Timeline: [HH:MM — Event entries]

Current State:
- Systems affected: [List]
- Workaround available: [Yes/No + description]
- Estimated resolution: [Time]

Actions Taken: [List with results]

For Next Responder:
- What's been tried
- What hasn't been tried
- Suspected root cause
- Relevant logs/metrics to check

Stakeholder Communication:
- Last update: [Timestamp]
- Next update due: [Timestamp]
- Channel: [Where updates posted]
```

Use `knowledge_write` to persist all handoff documents for audit trail and context continuity.

## Deliverables

- [ ] Appropriate handoff template selected for situation
- [ ] All fields filled with specific, actionable content
- [ ] Evidence attached (screenshots, test results, metrics)
- [ ] Next action clearly defined
- [ ] Handoff persisted via knowledge_write

## Success Metrics

- Zero context loss between agent handoffs
- All handoffs include measurable acceptance criteria
- QA feedback includes specific fix instructions
- Escalations include root cause analysis
- Phase gates have evidence for every criterion
- Sprint handoffs include retrospective action items
