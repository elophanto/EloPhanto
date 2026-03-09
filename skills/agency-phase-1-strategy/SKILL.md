---
name: agency-phase-1-strategy
description: Strategy and architecture phase — define what to build, how to structure it, and what success looks like. Adapted from msitarzewski/agency-agents.
---

## Triggers

- strategy phase
- architecture planning
- system architecture
- brand identity
- budget planning
- sprint planning
- feature prioritization
- technical architecture
- project architecture
- design system planning
- resource allocation
- ROI planning
- backlog creation
- task breakdown
- RICE scoring
- MoSCoW classification

## Instructions

Phase 1 defines what we're building, how it's structured, and what success looks like — before writing a single line of code. Every architectural decision is documented, every feature prioritized, every dollar accounted for. Duration: 5-10 days.

### Pre-Conditions

Verify before starting:
1. Phase 0 Quality Gate passed (GO decision)
2. Phase 0 Handoff Package received
3. Stakeholder alignment on project scope

### Step 1: Strategic Framing (Day 1-3, Parallel)

Use `organization_spawn` or `swarm_spawn` to activate in parallel:

**Studio Producer — Strategic Portfolio Alignment**:
- Input: Phase 0 Executive Summary + Market Analysis Report
- `goal_create`: Strategic Portfolio Plan with project positioning
- `goal_create`: Vision, objectives, and ROI targets
- `goal_create`: Resource allocation strategy
- `goal_create`: Risk/reward assessment
- `goal_create`: Success criteria and milestone definitions
- Timeline: 3 days.

**Brand Guardian — Brand Identity System**:
- Input: Phase 0 UX Research (personas, journey maps)
- `goal_create`: Brand Foundation (purpose, vision, mission, values, personality)
- `goal_create`: Visual Identity System (colors, typography, spacing as CSS variables)
- `goal_create`: Brand Voice and Messaging Architecture
- `goal_create`: Logo system specifications (if new brand)
- `goal_create`: Brand usage guidelines
- Timeline: 3 days.

**Finance Tracker — Budget and Resource Planning**:
- Input: Studio Producer strategic plan + Phase 0 Tech Stack Assessment
- `goal_create`: Comprehensive project budget with category breakdown
- `goal_create`: Resource cost projections (agents, infrastructure, tools)
- `goal_create`: ROI model with break-even analysis
- `goal_create`: Cash flow timeline
- `goal_create`: Financial risk assessment with contingency reserves
- Timeline: 2 days.

### Step 2: Technical Architecture (Day 3-7, Parallel, after Step 1)

**UX Architect — Technical Architecture + UX Foundation**:
- Input: Brand Guardian visual identity + Phase 0 UX Research
- `goal_create`: CSS Design System (variables, tokens, scales)
- `goal_create`: Layout Framework (Grid/Flexbox patterns, responsive breakpoints)
- `goal_create`: Component Architecture (naming conventions, hierarchy)
- `goal_create`: Information Architecture (page flow, content hierarchy)
- `goal_create`: Theme System (light/dark/system toggle)
- `goal_create`: Accessibility Foundation (WCAG 2.1 AA baseline)
- Timeline: 4 days.

**Backend Architect — System Architecture**:
- Input: Phase 0 Tech Stack Assessment + Compliance Requirements
- `goal_create`: Architecture pattern (microservices/monolith/serverless/hybrid)
- `goal_create`: Database Schema Design with indexing strategy
- `goal_create`: API Design Specification with versioning
- `goal_create`: Authentication and Authorization Architecture
- `goal_create`: Security Architecture (defense in depth)
- `goal_create`: Scalability Plan (horizontal scaling strategy)
- Timeline: 4 days.

**AI Engineer — ML Architecture** (if applicable):
- Input: Backend Architect system architecture + Phase 0 Data Audit
- `goal_create`: ML System Design (model selection, data pipeline, inference strategy)
- `goal_create`: AI Ethics and Safety Framework
- `goal_create`: Model monitoring and retraining plan
- `goal_create`: Integration points with main application
- `goal_create`: Cost projections for ML infrastructure
- Condition: Only activate if project includes AI/ML features. Timeline: 3 days.

**Senior Project Manager — Spec-to-Task Conversion**:
- Input: ALL Phase 0 documents + Architecture specs
- `goal_create`: Comprehensive Task List with acceptance criteria per task
- `goal_create`: Work Breakdown Structure with dependencies
- `goal_create`: Critical path identification
- `goal_create`: Risk register for implementation
- Rules: Do NOT add features not in the specification. Quote exact text from requirements. Be realistic about effort estimates.
- Timeline: 3 days.

### Step 3: Prioritization (Day 7-10, Sequential, after Step 2)

**Sprint Prioritizer — Feature Prioritization**:
- Input: Task List, System Architecture, UX Architecture, Budget, Strategic Plan
- `goal_create`: RICE-scored backlog (Reach, Impact, Confidence, Effort)
- `goal_create`: Sprint assignments with velocity-based estimation
- `goal_create`: Dependency map with critical path
- `goal_create`: MoSCoW classification (Must/Should/Could/Won't)
- `goal_create`: Release plan with milestone mapping
- Validation: Studio Producer confirms strategic alignment.
- Timeline: 2 days.

### Gate Decision

Dual sign-off required: Studio Producer (strategic) + Reality Checker (technical)

- **APPROVED**: Proceed to Phase 2 with full Architecture Package
- **REVISE**: Specific items need rework (return to relevant Step)
- **RESTRUCTURE**: Fundamental architecture issues (restart Phase 1)

Use `knowledge_write` to persist the entire Architecture Package.

## Deliverables

- [ ] Strategic Portfolio Plan (Studio Producer)
- [ ] Brand Identity System (Brand Guardian)
- [ ] Financial Plan with ROI Projections (Finance Tracker)
- [ ] CSS Design System + UX Architecture (UX Architect)
- [ ] System Architecture Specification (Backend Architect)
- [ ] ML System Design (AI Engineer — if applicable)
- [ ] Comprehensive Task List with acceptance criteria (Senior PM)
- [ ] Prioritized Sprint Plan with RICE scores (Sprint Prioritizer)
- [ ] Phase 1 -> Phase 2 Handoff Package

## Success Metrics

- Architecture covers 100% of spec requirements
- Brand system complete (logo, colors, typography, voice)
- All technical components have implementation path
- Budget approved and within constraints
- Sprint plan is velocity-based and realistic
- Security architecture defined
- Compliance requirements integrated into architecture
