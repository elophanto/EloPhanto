---
name: agency-phase-2-foundation
description: Foundation and scaffolding phase — build technical and operational foundation before feature development. Adapted from msitarzewski/agency-agents.
---

## Triggers

- foundation phase
- scaffolding
- project setup
- CI/CD pipeline
- infrastructure setup
- design system implementation
- database setup
- API scaffold
- environment setup
- monitoring setup
- dev environment
- project scaffolding
- component library
- theme system
- deployment pipeline

## Instructions

Phase 2 builds the technical and operational foundation that all subsequent work depends on. Get the skeleton standing before adding muscle. After this phase, every developer has a working environment, a deployable pipeline, and a design system to build with. Duration: 3-5 days.

### Pre-Conditions

Verify before starting:
1. Phase 1 Quality Gate passed (Architecture Package approved)
2. Phase 1 Handoff Package received
3. All architecture documents finalized

### Workstream A: Infrastructure (Day 1-3, Parallel)

Use `organization_spawn` or `swarm_spawn` to activate in parallel:

**DevOps Automator — CI/CD Pipeline + Infrastructure**:
- Input: Backend Architect system architecture + deployment requirements
- `goal_create`: CI/CD Pipeline (security scanning, testing, build/containerization, deployment, rollback)
- `goal_create`: Infrastructure as Code (environment provisioning, container orchestration, network/security config)
- `goal_create`: Environment Configuration (secrets management, env vars, multi-environment parity)
- Files to create: .github/workflows/ci-cd.yml, infrastructure/ templates, docker-compose.yml, Dockerfiles
- Timeline: 3 days.

**Infrastructure Maintainer — Cloud Infrastructure + Monitoring**:
- Input: DevOps Automator infrastructure + Backend Architect architecture
- `goal_create`: Cloud Resource Provisioning (compute, storage, networking, auto-scaling, load balancer)
- `goal_create`: Monitoring Stack (Prometheus/DataDog, Grafana dashboards)
- `goal_create`: Logging and Alerting (centralized logs, alert rules, on-call notifications)
- `goal_create`: Security Hardening (firewall rules, SSL/TLS, access control policies)
- Timeline: 3 days.

**Studio Operations — Process Setup**:
- Input: Sprint Prioritizer plan + coordination needs
- `goal_create`: Git Workflow (branch strategy, PR review process, merge policies)
- `goal_create`: Communication Channels (team channels, notification routing, status cadence)
- `goal_create`: Documentation Templates (PR template, issue template, decision log)
- `goal_create`: Collaboration Tools (project board, sprint tracking configuration)
- Timeline: 2 days.

### Workstream B: Application Foundation (Day 1-4, Parallel)

**Frontend Developer — Project Scaffolding + Component Library**:
- Input: UX Architect CSS Design System + Brand Guardian identity
- `goal_create`: Project Scaffolding (framework setup, TypeScript, build tooling, testing framework)
- `goal_create`: Design System Implementation (CSS tokens, base components, theme system, responsive utilities)
- `goal_create`: Application Shell (routing, layout components, error boundary, loading states)
- Timeline: 3 days.

**Backend Architect — Database + API Foundation**:
- Input: System Architecture Specification + Database Schema Design
- `goal_create`: Database Setup (schema deployment/migrations, indexes, seed data, connection pooling)
- `goal_create`: API Scaffold (framework setup, route structure, middleware stack, health checks)
- `goal_create`: Authentication System (auth provider, JWT/session management, RBAC scaffold)
- `goal_create`: Service Communication (API versioning, serialization, error standardization)
- Timeline: 4 days.

**UX Architect — CSS System Implementation**:
- Input: Brand Guardian identity + Phase 1 CSS Design System spec
- `goal_create`: Design Tokens Implementation (CSS custom properties, brand palette, typography scale)
- `goal_create`: Layout System (container system, grid patterns, flexbox utilities)
- `goal_create`: Theme System (light/dark variables, system preference detection, theme toggle, smooth transitions)
- Timeline: 2 days.

### Verification Checkpoint (Day 4-5)

Use `organization_delegate` to an Evidence Collector for verification with screenshot evidence:
1. CI/CD pipeline executes successfully
2. Application skeleton loads in browser (desktop + mobile)
3. Theme toggle works (light + dark)
4. API health check responds
5. Database is accessible (migration status)
6. Monitoring dashboards are active
7. Component library renders

### Gate Decision

Dual sign-off: DevOps Automator (infrastructure) + Evidence Collector (visual)

- **PASS**: Working skeleton with full DevOps pipeline -> Phase 3
- **FAIL**: Specific infrastructure or application issues -> Fix and re-verify

Use `knowledge_write` to persist all foundation artifacts and verification evidence.

## Deliverables

- [ ] Working CI/CD pipeline (builds, tests, deploys)
- [ ] Database schema deployed with all tables/indexes
- [ ] API scaffold responding on health check
- [ ] Frontend skeleton renders in browser
- [ ] Monitoring dashboards showing metrics
- [ ] Design system tokens implemented
- [ ] Theme toggle functional (light/dark/system)
- [ ] Git workflow and processes documented
- [ ] Evidence Collector verification screenshots

## Success Metrics

- CI/CD pipeline builds, tests, and deploys without errors
- Database schema deployed with all tables and indexes
- API scaffold responding on health check endpoint
- Frontend skeleton renders in browser (desktop + mobile)
- Monitoring dashboards showing metrics
- Design system tokens implemented and component library rendering
- Theme toggle functional (light/dark/system)
- Git workflow and processes documented
