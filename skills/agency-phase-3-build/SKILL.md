---
name: agency-phase-3-build
description: Build and iterate phase — implement all features through continuous Dev-QA loops with orchestrated multi-agent sprints. Adapted from msitarzewski/agency-agents.
---

## Triggers

- build phase
- sprint execution
- dev qa loop
- feature implementation
- sprint planning
- task assignment
- parallel build
- agents orchestrator
- build iterate
- sprint review
- sprint retrospective
- task failure handling
- dev loop
- QA loop
- implementation sprint
- feature development

## Instructions

Phase 3 implements all features through continuous Dev-QA loops. Every task is validated before the next begins. This is where the bulk of the work happens and where orchestration delivers the most value. Duration: 2-12 weeks.

### Pre-Conditions

Verify before starting:
1. Phase 2 Quality Gate passed (foundation verified)
2. Sprint Prioritizer backlog available with RICE scores
3. CI/CD pipeline operational
4. Design system and component library ready
5. API scaffold with auth system ready

### The Dev-QA Loop — Core Mechanic

The Agents Orchestrator manages every task through this cycle:

```
FOR EACH task IN sprint_backlog (ordered by RICE score):
  1. ASSIGN task to appropriate Developer Agent
  2. Developer IMPLEMENTS task
  3. Evidence Collector TESTS task (screenshots: desktop, tablet, mobile + acceptance criteria + brand check)
  4. IF PASS: Mark task complete, move to next
     ELIF FAIL AND attempts < 3: Send QA feedback to Developer, fix, retry
     ELIF attempts >= 3: ESCALATE to Orchestrator (reassign, decompose, defer, or accept)
  5. UPDATE pipeline status report
```

Use `organization_spawn` with the Agents Orchestrator role to manage this loop. Use `organization_delegate` for individual task assignments.

### Agent Assignment Matrix

| Task Category | Primary Agent | QA Agent |
|--------------|--------------|----------|
| React/Vue/Angular UI | Frontend Developer | Evidence Collector |
| REST/GraphQL API | Backend Architect | API Tester |
| Database operations | Backend Architect | API Tester |
| Mobile (iOS/Android) | Mobile App Builder | Evidence Collector |
| ML model/pipeline | AI Engineer | Test Results Analyzer |
| CI/CD/Infrastructure | DevOps Automator | Performance Benchmarker |
| Premium/complex feature | Senior Developer | Evidence Collector |
| Quick prototype/POC | Rapid Prototyper | Evidence Collector |
| Performance optimization | Performance Benchmarker | Performance Benchmarker |

### Parallel Build Tracks

For full deployments, four tracks run simultaneously:

**Track A: Core Product Development** (Agents Orchestrator):
- Frontend Developer, Backend Architect, AI Engineer, Senior Developer
- QA: Evidence Collector, API Tester, Test Results Analyzer
- 2-week sprint cadence

**Track B: Growth & Marketing Preparation** (Project Shepherd):
- Growth Hacker: Design viral loops and referral mechanics
- Content Creator: Build launch content pipeline
- Social Media Strategist: Plan cross-platform campaign
- App Store Optimizer: Prepare store listing (if mobile)

**Track C: Quality & Operations** (Agents Orchestrator):
- Evidence Collector: Screenshot QA for every task
- API Tester: Endpoint validation for every API task
- Performance Benchmarker: Periodic load testing
- Workflow Optimizer: Process improvement identification
- Experiment Tracker: A/B test setup for validated features

**Track D: Brand & Experience Polish** (Brand Guardian):
- UI Designer: Component refinement
- Brand Guardian: Periodic brand consistency audit
- Visual Storyteller: Visual narrative assets
- Whimsy Injector: Micro-interactions and delight moments

### Sprint Execution Template

**Sprint Planning (Day 1)**: Sprint Prioritizer reviews backlog, selects tasks by velocity, assigns to agents, identifies dependencies, sets sprint goal.

**Daily Execution**: Orchestrator manages Dev-QA loops, tracks status:
- Tasks completed today
- Tasks in QA / in development / blocked
- QA pass rate

**Sprint Review (Day N)**: Project Shepherd facilitates demo, reviews QA evidence, collects stakeholder feedback.

**Sprint Retrospective**: Workflow Optimizer leads — what went well, what to improve, process efficiency metrics.

### Task Failure Handling

- Attempt 1: Send specific QA feedback to developer
- Attempt 2: Send accumulated feedback, consider reassignment
- Attempt 3: ESCALATE — reassign, decompose, revise approach, accept with limitations, or defer

### Gate Decision

Gate Keeper: Agents Orchestrator

- **PASS**: Feature-complete application -> Phase 4
- **CONTINUE**: More sprints needed -> Continue Phase 3
- **ESCALATE**: Systemic issues -> Studio Producer intervention

Use `knowledge_write` to persist sprint results, QA evidence, and status reports.

## Deliverables

- [ ] All sprint tasks pass QA (100% completion)
- [ ] All API endpoints validated
- [ ] Performance baselines met (P95 < 200ms)
- [ ] Brand consistency verified (95%+ adherence)
- [ ] No critical bugs (zero P0/P1 open)
- [ ] All acceptance criteria met
- [ ] Code review completed for all PRs
- [ ] Sprint review summaries and retrospective action items

## Success Metrics

- 100% sprint task completion with QA pass
- All API endpoints validated via regression
- P95 response time < 200ms
- Brand consistency 95%+ adherence
- Zero P0/P1 open bugs
- All acceptance criteria met per task
- Code review completed for all PRs
- First-pass QA rate improving sprint over sprint

## Verify

- The deliverable for this phase exists as a concrete artifact (doc, ticket, board, repo) and its location is shared, not described
- Each commitment has an owner name, a due date, and a definition-of-done that someone other than the author could check
- Risks are listed with likelihood/impact and a named mitigation, not as a generic 'risks: TBD' bullet
- Dependencies on other teams/vendors/agents are explicit; an ack from each dependency is recorded or marked 'pending'
- Success criteria for the next phase are numeric or otherwise objectively testable
- A rollback / kill-switch / 'we will stop if X' criterion is written down before work starts
