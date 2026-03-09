---
name: runbook-enterprise-feature
description: Enterprise feature development runbook — adding major features to existing products with compliance, security, and quality gates. Adapted from msitarzewski/agency-agents.
---

## Triggers

- enterprise feature
- major feature development
- enterprise compliance
- feature rollout
- canary deployment
- enterprise quality
- stakeholder alignment
- enterprise integration
- feature branch pipeline
- enterprise sprint
- large feature build
- compliance-driven feature
- enterprise architecture
- regulated feature development

## Instructions

This runbook covers adding a major feature to an existing enterprise product. Compliance, security, and quality gates are non-negotiable. Multiple stakeholders need alignment. The feature must integrate seamlessly with existing systems. Duration: 6-12 weeks.

### Agent Roster

**Core Team** (use `organization_spawn` to activate):
- Agents Orchestrator: Pipeline controller
- Project Shepherd: Cross-functional coordination
- Senior Project Manager: Spec-to-task conversion
- Sprint Prioritizer: Backlog management
- UX Architect: Technical foundation
- UX Researcher: User validation
- UI Designer: Component design
- Frontend Developer: UI implementation
- Backend Architect: API and system integration
- Senior Developer: Complex implementation
- DevOps Automator: CI/CD and deployment
- Evidence Collector: Visual QA
- API Tester: Endpoint validation
- Reality Checker: Final quality gate
- Performance Benchmarker: Load testing

**Compliance & Governance**:
- Legal Compliance Checker, Brand Guardian, Finance Tracker, Executive Summary Generator

**Quality Assurance**:
- Test Results Analyzer, Workflow Optimizer, Experiment Tracker

### Phase 1: Requirements & Architecture (Week 1-2)

**Week 1 — Stakeholder Alignment**:
- Project Shepherd: Stakeholder analysis + communication plan
- UX Researcher: User research on feature need
- Legal Compliance Checker: Compliance requirements scan
- Senior Project Manager: Spec-to-task conversion
- Finance Tracker: Budget framework

**Week 2 — Technical Architecture**:
- UX Architect: UX foundation + component architecture
- Backend Architect: System architecture + integration plan
- UI Designer: Component design + design system updates
- Sprint Prioritizer: RICE-scored backlog
- Brand Guardian: Brand impact assessment
- Quality Gate: Architecture Review (Project Shepherd + Reality Checker)

### Phase 2: Foundation (Week 3)

- DevOps Automator: Feature branch pipeline + feature flags
- Frontend Developer: Component scaffolding
- Backend Architect: API scaffold + database migrations
- Infrastructure Maintainer: Staging environment setup
- Quality Gate: Foundation verified (Evidence Collector)

### Phase 3: Build (Week 4-9)

Sprint 1-3 (use `agency-phase-3-build` skill mechanics):
- Agents Orchestrator: Dev-QA loop management
- Frontend Developer: UI implementation (task by task)
- Backend Architect: API implementation (task by task)
- Senior Developer: Complex/premium features
- Evidence Collector: QA every task with screenshots
- API Tester: Endpoint validation every API task
- Experiment Tracker: A/B test setup for key features

Bi-weekly:
- Project Shepherd: Stakeholder status update
- Executive Summary Generator: Executive briefing
- Finance Tracker: Budget tracking

Sprint Reviews with stakeholder demos.

### Phase 4: Hardening (Week 10-11)

**Week 10 — Evidence Collection**:
- Evidence Collector: Full screenshot suite
- API Tester: Complete regression suite
- Performance Benchmarker: Load test at 10x traffic
- Legal Compliance Checker: Final compliance audit
- Test Results Analyzer: Quality metrics dashboard
- Infrastructure Maintainer: Production readiness

**Week 11 — Final Judgment**:
- Reality Checker: Integration testing (default: NEEDS WORK)
- Fix cycle if needed (2-3 days)
- Re-verification
- Executive Summary Generator: Go/No-Go recommendation

### Phase 5: Rollout (Week 12)

- DevOps Automator: Canary deployment (5% -> 25% -> 100%)
- Infrastructure Maintainer: Real-time monitoring
- Analytics Reporter: Feature adoption tracking
- Support Responder: User support for new feature
- Feedback Synthesizer: Early feedback collection
- Executive Summary Generator: Launch report

### Stakeholder Communication Cadence

| Audience | Frequency | Format |
|----------|-----------|--------|
| Executive sponsors | Bi-weekly | SCQA summary (500 words max) |
| Product team | Weekly | Status report |
| Engineering team | Daily | Pipeline status |
| Compliance team | Monthly | Compliance status |
| Finance | Monthly | Budget report |

Use `knowledge_write` to persist all architecture docs, sprint results, and stakeholder reports.

## Deliverables

- [ ] Architecture Package with integration plan
- [ ] RICE-scored backlog with sprint assignments
- [ ] Feature branch CI/CD pipeline with feature flags
- [ ] All sprint tasks QA'd and passing
- [ ] Full regression suite (visual + API + performance)
- [ ] Compliance certification
- [ ] Canary deployment executed (5% -> 25% -> 100%)
- [ ] Feature adoption tracking active
- [ ] Stakeholder launch report

## Success Metrics

| Requirement | Threshold |
|-------------|-----------|
| Code coverage | > 80% |
| API response time | P95 < 200ms |
| Accessibility | WCAG 2.1 AA |
| Security | Zero critical vulnerabilities |
| Brand consistency | 95%+ adherence |
| Spec compliance | 100% |
| Load handling | 10x current traffic |
