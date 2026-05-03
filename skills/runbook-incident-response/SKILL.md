---
name: runbook-incident-response
description: Incident response runbook — detection through post-mortem for production issues with severity-based response teams. Adapted from msitarzewski/agency-agents.
---

## Triggers

- incident response
- production down
- service outage
- system failure
- security breach
- data loss
- performance degradation
- error rate spike
- P0 incident
- P1 incident
- rollback needed
- hotfix deployment
- post-mortem
- root cause analysis
- incident triage
- on-call alert
- system recovery

## Instructions

Something is broken in production. Users are affected. Speed of response matters, but so does doing it right. This runbook covers detection through post-mortem. Duration: minutes to hours.

### Severity Classification

| Level | Definition | Examples | Response Time |
|-------|-----------|----------|--------------|
| P0 Critical | Service completely down, data loss, security breach | Database corruption, DDoS, auth failure | Immediate |
| P1 High | Major feature broken, significant degradation | Payment down, 50%+ error rate, 10x latency | < 1 hour |
| P2 Medium | Minor feature broken, workaround available | Search not working, non-critical API errors | < 4 hours |
| P3 Low | Cosmetic issue, minor inconvenience | Styling bug, typo, minor UI glitch | Next sprint |

### Response Teams by Severity

**P0 Critical** (use `organization_spawn` with all):
- Infrastructure Maintainer: Incident commander — assess scope, coordinate
- DevOps Automator: Deployment/rollback execution
- Backend Architect: Root cause investigation (system)
- Frontend Developer: Client-side investigation
- Support Responder: Status page updates, user notifications
- Executive Summary Generator: Real-time executive updates

**P1 High**:
- Infrastructure Maintainer: Incident commander
- DevOps Automator: Deployment support
- Relevant Developer Agent: Fix implementation
- Support Responder: User communication

**P2 Medium**:
- Relevant Developer Agent: Fix implementation
- Evidence Collector: Verify fix

**P3 Low**:
- Sprint Prioritizer: Add to backlog

### Step 1: Detection & Triage (0-5 minutes)

Trigger: Alert from monitoring / User report / Agent detection

Infrastructure Maintainer:
1. Acknowledge alert
2. Assess scope and impact (users affected, services impacted, data at risk?)
3. Classify severity (P0/P1/P2/P3)
4. Use `organization_spawn` to activate appropriate response team
5. Create incident channel/thread

### Step 2: Investigation (5-30 minutes)

Parallel investigation via `organization_delegate`:

- Infrastructure Maintainer: Check system metrics (CPU, memory, network, disk), review error logs, check recent deployments, verify external dependencies
- Backend Architect (P0/P1): Check database health, review API error rates, check service communication, identify failing component
- DevOps Automator: Review deployment history, check CI/CD status, prepare rollback, verify infrastructure state

Output: Root cause identified or narrowed to component.

### Step 3: Mitigation (15-60 minutes)

Decision tree:
- **Caused by recent deployment**: DevOps Automator executes rollback, Infrastructure Maintainer verifies recovery
- **Caused by infrastructure issue**: Infrastructure Maintainer scales/restarts/failovers, verify recovery
- **Caused by code bug**: Developer implements hotfix, Evidence Collector verifies, DevOps Automator deploys hotfix
- **Caused by external dependency**: Infrastructure Maintainer activates fallback/cache, Support Responder communicates to users

Throughout:
- Support Responder: Update status page every 15 minutes
- Executive Summary Generator: Brief stakeholders (P0 only)

### Step 4: Resolution Verification (Post-fix)

- Evidence Collector: Verify fix resolves issue, screenshot evidence, confirm no new issues
- Infrastructure Maintainer: Verify metrics returning to normal, confirm no cascading failures, monitor 30 minutes post-fix
- API Tester (if API-related): Run regression on affected endpoints, verify response times, confirm error rates at baseline

### Step 5: Post-Mortem (Within 48 hours)

Use `organization_delegate` to Workflow Optimizer:
1. Timeline reconstruction (when introduced, detected, resolved, total impact duration)
2. Root cause analysis (what failed, why, why not caught earlier, 5 Whys)
3. Impact assessment (users affected, revenue impact, reputation, data impact)
4. Prevention measures (monitoring improvements, testing improvements, process changes, infrastructure changes)
5. Action items with owners and deadlines

Use `knowledge_write` to persist post-mortem report. Sprint Prioritizer adds prevention tasks to backlog.

### Communication Templates

**Status Page Update**:
```
[TIMESTAMP] — [SERVICE NAME] Incident
Status: [Investigating / Identified / Monitoring / Resolved]
Impact: [Description of user impact]
Current action: [What we're doing]
Next update: [When to expect next update]
```

**Executive Update (P0 only)**:
```
INCIDENT BRIEF — [TIMESTAMP]
SITUATION: [Service] is [down/degraded] affecting [N users/% of traffic]
CAUSE: [Known/Under investigation] — [Brief description if known]
ACTION: [What's being done] — ETA [time estimate]
IMPACT: [Business impact — revenue, users, reputation]
NEXT UPDATE: [Timestamp]
```

### Escalation Matrix

| Condition | Escalate To |
|-----------|------------|
| P0 not resolved in 30 min | Studio Producer (additional resources, vendor escalation) |
| P1 not resolved in 2 hours | Project Shepherd (resource reallocation) |
| Data breach suspected | Legal Compliance Checker (regulatory notification) |
| User data affected | Legal Compliance Checker + Executive Summary Generator (GDPR/CCPA) |
| Revenue impact > threshold | Finance Tracker + Studio Producer (business impact assessment) |

## Deliverables

- [ ] Incident classified with severity level
- [ ] Response team activated within SLA
- [ ] Root cause identified
- [ ] Fix implemented and verified
- [ ] Status page updated throughout
- [ ] Stakeholders briefed (P0/P1)
- [ ] Post-mortem completed within 48 hours
- [ ] Prevention action items in backlog

## Success Metrics

- P0 detection to resolution: < 30 minutes
- P1 detection to resolution: < 2 hours
- P2 detection to resolution: < 4 hours
- Post-mortem completion rate: 100% for P0/P1
- Repeat incident rate: < 5%
- Status page update frequency during incident: every 15 minutes
- Mean time to detect (MTTD): < 5 minutes
- Mean time to resolve (MTTR): < 30 minutes

## Verify

- The deploy command was actually run and the build/log output (or deploy URL) is captured
- The deployed URL was opened and returned a 2xx; key routes were sampled, not just the index
- Environment variables required by the app are present in the target environment; missing-var failures were ruled out
- A rollback plan (previous deployment ID, git SHA, or one-line revert command) is documented before promoting to production
- Health/observability check (logs, error tracker, status page) was inspected post-deploy; baseline error rate is recorded
- DNS / domain / SSL configuration was confirmed, not assumed to carry over from previous deploys
