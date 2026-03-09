---
name: agency-strategy
description: NEXUS multi-agent orchestration strategy — the complete operational playbook for coordinating specialized AI agents across project phases. Adapted from msitarzewski/agency-agents.
---

## Triggers

- NEXUS strategy
- multi-agent orchestration
- agency strategy
- agent coordination
- project pipeline
- NEXUS pipeline
- agent roster
- deployment mode
- NEXUS full
- NEXUS sprint
- NEXUS micro
- coordination matrix
- agent division
- quality gates
- risk management framework
- pipeline status
- project phases
- agency playbook

## Instructions

NEXUS (Network of EXperts, Unified in Strategy) transforms independent AI specialists into a synchronized intelligence network. This is the master strategy document governing all phases, agent coordination, handoff protocols, and quality gates.

### What NEXUS Solves

Individual agents are powerful but without coordination produce conflicting decisions, duplicated effort, quality gaps at handoffs, and no shared context. NEXUS defines WHO activates at each phase, WHAT they deliver, HOW work flows between agents, and WHEN quality gates trigger.

### Deployment Modes

**NEXUS-Full** (New product, 8-16 weeks):
- All 7 phases (0-6)
- 30+ agents across all divisions
- Complete quality gate system
- Full handoff protocol

**NEXUS-Sprint** (Major feature, 4-8 weeks):
- Phases 1-5 (skip deep discovery)
- 15-25 agents
- Compressed timelines
- Existing infrastructure leveraged

**NEXUS-Micro** (Quick fix or campaign, 1-2 weeks):
- Phases 3-5 only (build, verify, deploy)
- 5-10 agents
- Minimal ceremony
- Fastest time-to-delivery

### The Seven Phases

Use the corresponding skill for each phase:

1. **Phase 0 — Intelligence & Discovery** (`agency-phase-0-discovery`): Validate opportunity. 3-7 days, 6 agents.
2. **Phase 1 — Strategy & Architecture** (`agency-phase-1-strategy`): Define what to build. 5-10 days, 8 agents.
3. **Phase 2 — Foundation & Scaffolding** (`agency-phase-2-foundation`): Build technical foundation. 3-5 days, 6 agents.
4. **Phase 3 — Build & Iterate** (`agency-phase-3-build`): Implement features via Dev-QA loops. 2-12 weeks, 15-30+ agents.
5. **Phase 4 — Quality & Hardening** (`agency-phase-4-hardening`): Prove production readiness. 3-7 days, 8 agents.
6. **Phase 5 — Launch & Growth** (`agency-phase-5-launch`): Go-to-market execution. 2-4 weeks, 12 agents.
7. **Phase 6 — Operate & Evolve** (`agency-phase-6-operate`): Sustained operations. Ongoing, 12+ agents.

### Agent Division Structure

**Engineering Division**: Frontend Developer, Backend Architect, AI Engineer, DevOps Automator, Infrastructure Maintainer, Mobile App Builder, Senior Developer, Rapid Prototyper, XR Developers, Terminal Integration Specialist, LSP/Index Engineer

**Design Division**: UX Architect, UI Designer, Brand Guardian, Visual Storyteller, Whimsy Injector

**Testing Division**: Evidence Collector, API Tester, Performance Benchmarker, Test Results Analyzer

**Product Division**: Studio Producer, Sprint Prioritizer, Senior Project Manager, Project Shepherd, Agents Orchestrator

**Research Division**: Trend Researcher, UX Researcher, Feedback Synthesizer, Tool Evaluator

**Growth Division**: Growth Hacker, Content Creator, Social Media Strategist, Twitter Engager, TikTok Strategist, Instagram Curator, Reddit Community Builder, App Store Optimizer

**Support Division**: Support Responder, Executive Summary Generator, Finance Tracker, Legal Compliance Checker, Workflow Optimizer, Experiment Tracker, Analytics Reporter, Data Analytics Reporter, Studio Operations

### Core Mechanics

**Dev-QA Loop**: Developer implements -> Evidence Collector tests -> PASS/FAIL -> max 3 retries -> escalate. This is the heartbeat of Phase 3.

**Quality Gates**: Every phase boundary requires evidence-based gate passage. No advancing without proof. Gate keepers vary by phase.

**Handoff Protocol**: Use `agent-handoff` skill templates. Consistent handoffs prevent context loss.

**Agent Activation**: Use `agent-activation` skill templates. Copy, customize placeholders, deploy via `organization_spawn` or `organization_delegate`.

### Coordination Matrix

| Phase | Primary Coordinator | Gate Keeper |
|-------|-------------------|-------------|
| Phase 0 | Agents Orchestrator | Executive Summary Generator |
| Phase 1 | Studio Producer | Studio Producer + Reality Checker |
| Phase 2 | DevOps Automator | DevOps Automator + Evidence Collector |
| Phase 3 | Agents Orchestrator | Agents Orchestrator |
| Phase 4 | Reality Checker | Reality Checker (sole authority) |
| Phase 5 | Project Shepherd | Studio Producer + Analytics Reporter |
| Phase 6 | Studio Producer | Studio Producer |

### Risk Management Framework

| Risk Category | Detection | Response |
|--------------|-----------|----------|
| Technical debt | Tool Evaluator quarterly review | Sprint Prioritizer allocates 20% capacity |
| Scope creep | Sprint Prioritizer MoSCoW enforcement | Project Shepherd change management |
| Quality regression | Evidence Collector + Performance Benchmarker | Agents Orchestrator escalation |
| Security vulnerability | Legal Compliance Checker + DevOps Automator | Incident response protocol |
| Market shift | Trend Researcher monthly intelligence | Studio Producer strategic pivot |

### Quick-Start Guide

1. Determine deployment mode (Full/Sprint/Micro)
2. Activate Agents Orchestrator with project spec using `agent-activation` skill
3. Follow phase sequence starting from appropriate phase
4. Use handoff templates (`agent-handoff` skill) at every boundary
5. Enforce quality gates — no exceptions

Use `knowledge_write` to persist the project's NEXUS configuration, agent roster, and coordination decisions.

## Deliverables

- [ ] Deployment mode selected (Full/Sprint/Micro)
- [ ] Agent roster defined for the project
- [ ] Phase sequence planned
- [ ] Coordination matrix established
- [ ] Quality gate criteria defined per phase
- [ ] Risk management framework active
- [ ] Handoff protocol in use

## Success Metrics

- All phases complete with quality gates passed
- Zero context loss at handoff boundaries
- Dev-QA first-pass rate improving sprint over sprint
- All agents activated with complete context
- Quality gate criteria met with evidence
- Risk detection and response within SLA
- Deployment mode appropriate for project scope
