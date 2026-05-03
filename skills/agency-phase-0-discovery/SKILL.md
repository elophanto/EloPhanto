---
name: agency-phase-0-discovery
description: Intelligence and discovery phase — validate opportunity before committing resources. Adapted from msitarzewski/agency-agents.
---

## Triggers

- discovery phase
- market research
- opportunity validation
- competitive analysis
- market sizing
- user needs analysis
- regulatory scan
- technology landscape
- feasibility study
- go no-go decision
- TAM SAM SOM
- compliance scan
- data landscape assessment
- trend research
- user behavior analysis
- pain point identification
- pre-project validation
- intelligence gathering

## Instructions

Phase 0 validates the opportunity before committing resources. No building until the problem, market, and regulatory landscape are understood. Duration: 3-7 days.

### Pre-Conditions

Verify before starting:
1. Project brief or initial concept exists
2. Stakeholder sponsor identified
3. Budget for discovery phase approved

### Wave 1: Parallel Launch (Day 1)

Use `organization_spawn` or `swarm_spawn` to activate these agents in parallel:

**Market Intelligence Lead** (Trend Researcher):
- `goal_create`: Competitive landscape analysis (direct + indirect competitors)
- `goal_create`: Market sizing — TAM, SAM, SOM with methodology
- `goal_create`: Trend lifecycle mapping — where is this market in the adoption curve?
- `goal_create`: 3-6 month trend forecast with confidence intervals
- `goal_create`: Investment and funding trends in the space
- Require minimum 15 unique, verified sources. Timeline: 3 days.

**User Needs Analysis** (Feedback Synthesizer):
- `goal_create`: Multi-channel feedback collection plan (surveys, interviews, reviews, social)
- `goal_create`: Sentiment analysis across existing user touchpoints
- `goal_create`: Pain point identification and prioritization (RICE scored)
- `goal_create`: Feature request analysis with business value estimation
- `goal_create`: Churn risk indicators from feedback patterns
- Timeline: 3 days.

**User Behavior Analysis** (UX Researcher):
- `goal_create`: User interview plan (5-10 target users)
- `goal_create`: Persona development (3-5 primary personas)
- `goal_create`: Journey mapping for primary user flows
- `goal_create`: Usability heuristic evaluation of competitor products
- `goal_create`: Behavioral insights with statistical validation
- Timeline: 5 days.

### Wave 2: Parallel Launch (Day 1, independent of Wave 1)

**Data Landscape Assessment** (Analytics Reporter):
- `goal_create`: Existing data source audit
- `goal_create`: Signal identification (what can we measure?)
- `goal_create`: Baseline metrics establishment
- `goal_create`: Data quality assessment with completeness scoring
- `goal_create`: Analytics infrastructure recommendations
- Timeline: 2 days.

**Regulatory Scan** (Legal Compliance Checker):
- `goal_create`: Applicable regulatory frameworks (GDPR, CCPA, HIPAA, etc.)
- `goal_create`: Data handling requirements and constraints
- `goal_create`: Jurisdiction mapping for target markets
- `goal_create`: Compliance risk assessment with severity ratings
- `goal_create`: Blocking vs. manageable compliance issues
- Timeline: 3 days.

**Technology Landscape** (Tool Evaluator):
- `goal_create`: Technology stack assessment for the problem domain
- `goal_create`: Build vs. buy analysis for key components
- `goal_create`: Integration feasibility with existing systems
- `goal_create`: Open source vs. commercial evaluation
- `goal_create`: Technology risk assessment
- Timeline: 2 days.

### Convergence Point (Day 5-7)

All six agents deliver their reports. Use `organization_delegate` to an Executive Summary Generator to synthesize:

Input documents:
1. Trend Researcher -> Market Analysis Report
2. Feedback Synthesizer -> Synthesized Feedback Report
3. UX Researcher -> Research Findings Report
4. Analytics Reporter -> Data Audit Report
5. Legal Compliance Checker -> Compliance Requirements Matrix
6. Tool Evaluator -> Tech Stack Assessment

Output: Executive Summary (500 words max, SCQA format)
Decision required: GO / NO-GO / PIVOT

Use `knowledge_write` to persist all reports and the executive summary.

### Gate Decision

- **GO**: Proceed to Phase 1 (use `agency-phase-1-strategy` skill)
- **NO-GO**: Archive findings, document learnings, redirect resources
- **PIVOT**: Modify scope/direction based on findings, re-run targeted discovery

### Handoff to Phase 1

Use `knowledge_write` to persist the handoff package:
1. Market Analysis Report (Trend Researcher)
2. Synthesized Feedback Report (Feedback Synthesizer)
3. User Personas and Journey Maps (UX Researcher)
4. Data Audit Report (Analytics Reporter)
5. Compliance Requirements Matrix (Legal Compliance Checker)
6. Tech Stack Assessment (Tool Evaluator)
7. Executive Summary with GO decision
8. Key constraints identified (regulatory, technical, market timing)
9. Priority user needs for Sprint Prioritizer

## Deliverables

- [ ] Competitive landscape analysis with TAM/SAM/SOM
- [ ] Synthesized Feedback Report with priority matrix
- [ ] User personas (3-5) and journey maps
- [ ] Data Audit Report with signal map
- [ ] Compliance Requirements Matrix
- [ ] Tech Stack Assessment with recommendation matrix
- [ ] Executive Summary with GO/NO-GO/PIVOT recommendation
- [ ] Phase 0 -> Phase 1 Handoff Package

## Success Metrics

- Market opportunity validated with TAM > minimum viable threshold
- 3+ validated user pain points with supporting data
- No blocking compliance issues identified
- Key metrics and data sources identified
- Technology stack feasible and assessed
- Executive summary delivered with GO/NO-GO recommendation
- All reports completed within 7-day window

## Verify

- The deliverable for this phase exists as a concrete artifact (doc, ticket, board, repo) and its location is shared, not described
- Each commitment has an owner name, a due date, and a definition-of-done that someone other than the author could check
- Risks are listed with likelihood/impact and a named mitigation, not as a generic 'risks: TBD' bullet
- Dependencies on other teams/vendors/agents are explicit; an ack from each dependency is recorded or marked 'pending'
- Success criteria for the next phase are numeric or otherwise objectively testable
- A rollback / kill-switch / 'we will stop if X' criterion is written down before work starts
