---
name: agency-phase-6-operate
description: Operate and evolve phase — sustained operations with continuous improvement for live products. Adapted from msitarzewski/agency-agents.
---

## Triggers

- operate phase
- continuous improvement
- ongoing operations
- incident response
- growth operations
- financial operations
- compliance monitoring
- strategic review
- retention analysis
- churn analysis
- monthly review
- quarterly review
- operational cadence
- product operations
- live product management
- post-launch operations

## Instructions

Phase 6 provides sustained operations with continuous improvement. The product is live — now make it thrive. This phase has no end date; it runs as long as the product is in market.

### Pre-Conditions

Verify before starting:
1. Phase 5 Quality Gate passed (stable launch)
2. Phase 5 Handoff Package received
3. Operational cadences established
4. Baseline metrics documented

### Operational Cadences

**Continuous (Always Active)**:
- Infrastructure Maintainer: System uptime, performance, security (SLA: 99.9% uptime, < 30min MTTR)
- Support Responder: Customer support, issue resolution (SLA: < 4hr first response)
- DevOps Automator: Deployment pipeline, hotfixes (multiple deploys/day capability)

**Daily**:
- Analytics Reporter: KPI dashboard update, daily metrics snapshot
- Support Responder: Issue triage and resolution, ticket summary
- Infrastructure Maintainer: System health check, health status report

**Weekly**:
- Analytics Reporter: Weekly performance analysis
- Feedback Synthesizer: User feedback synthesis
- Sprint Prioritizer: Backlog grooming + sprint planning
- Growth Hacker: Growth channel optimization
- Project Shepherd: Cross-team coordination, weekly status update

**Bi-Weekly**:
- Feedback Synthesizer: Deep feedback analysis
- Experiment Tracker: A/B test analysis
- Content Creator: Content calendar execution

**Monthly**:
- Executive Summary Generator: C-suite reporting
- Finance Tracker: Financial performance review
- Legal Compliance Checker: Regulatory monitoring
- Trend Researcher: Market intelligence update
- Brand Guardian: Brand consistency audit

**Quarterly**:
- Studio Producer: Strategic portfolio review
- Workflow Optimizer: Process efficiency audit
- Performance Benchmarker: Performance regression testing
- Tool Evaluator: Technology stack review, tech debt assessment

### Continuous Improvement Loop

Use `organization_spawn` to run the improvement cycle:
1. MEASURE (Analytics Reporter)
2. ANALYZE (Feedback Synthesizer + Data Analytics Reporter)
3. PLAN (Sprint Prioritizer + Studio Producer)
4. BUILD (Phase 3 Dev-QA Loop — mini-cycles using `agency-phase-3-build` skill)
5. VALIDATE (Evidence Collector + Reality Checker)
6. DEPLOY (DevOps Automator)
7. Return to MEASURE

### Feature Development in Phase 6

New features follow a compressed cycle:
1. Sprint Prioritizer selects feature from backlog
2. Appropriate Developer Agent implements
3. Evidence Collector validates (Dev-QA loop)
4. DevOps Automator deploys (feature flag or direct)
5. Experiment Tracker monitors (A/B test if applicable)
6. Analytics Reporter measures impact
7. Feedback Synthesizer collects user response

### Incident Response Protocol

Use `runbook-incident-response` skill for detailed procedures.

Severity Levels:
- P0 Critical: Service down, data loss, security breach -> Immediate response
- P1 High: Major feature broken, significant degradation -> < 1 hour
- P2 Medium: Minor feature issue, workaround available -> < 4 hours
- P3 Low: Cosmetic issue, minor inconvenience -> Next sprint

Sequence: Detection -> Triage -> Response -> Resolution -> Post-Mortem

### Growth Operations (Monthly Growth Review)

- Channel Performance Analysis (acquisition by channel, CAC by channel, conversion rates, LTV:CAC)
- Experiment Results (A/B tests, statistical significance, winner implementation)
- Retention Analysis (cohort curves, churn risk, re-engagement results, feature adoption)
- Growth Roadmap Update (next month experiments, budget reallocation, new channels, viral coefficient)

### Financial Operations (Monthly)

- Revenue Analysis (MRR/ARR, revenue by segment, expansion revenue, churn impact)
- Cost Analysis (infrastructure, marketing spend, team/resource costs, tool costs)
- Unit Economics (CAC trends, LTV trends, LTV:CAC ratio, payback period)
- Forecasting (3-month rolling revenue, cost forecast, cash flow, budget variance)

### Compliance Operations (Monthly)

- Regulatory Monitoring (new regulations, changes, enforcement actions, deadline tracking)
- Privacy Compliance (data subject requests, consent management, retention policy, cross-border transfers)
- Security Compliance (vulnerability scans, patch management, access control review, incident log)
- Audit Readiness (documentation currency, evidence collection, training completion, policy acknowledgment)

### Quarterly Strategic Review (Studio Producer)

- Market Position Assessment (competitive landscape, market share, brand perception, customer satisfaction)
- Product Strategy (feature roadmap, tech debt, platform expansion, partnerships)
- Growth Strategy (channel effectiveness, new markets, pricing, expansion)
- Organizational Health (process efficiency, team performance, resource allocation, capability needs)

Use `knowledge_write` to persist all operational reports, reviews, and strategic plans.

## Deliverables

- [ ] Daily KPI dashboards and health reports
- [ ] Weekly analytics and feedback summaries
- [ ] Monthly executive summaries and financial reports
- [ ] Monthly compliance status reports
- [ ] Quarterly strategic reviews with updated roadmaps
- [ ] Incident post-mortems with prevention measures
- [ ] Continuous improvement cycle documentation

## Success Metrics

| Category | Metric | Target |
|----------|--------|--------|
| Reliability | System uptime | > 99.9% |
| Reliability | MTTR | < 30 minutes |
| Growth | MoM user growth | > 20% |
| Growth | Activation rate | > 60% |
| Retention | Day 7 retention | > 40% |
| Retention | Day 30 retention | > 20% |
| Financial | LTV:CAC ratio | > 3:1 |
| Financial | Portfolio ROI | > 25% |
| Quality | NPS score | > 50 |
| Quality | Support resolution time | < 4 hours |
| Compliance | Regulatory adherence | > 98% |
| Efficiency | Deployment frequency | Multiple/day |
| Efficiency | Process improvement | 20%/quarter |
