---
name: agency-phase-4-hardening
description: Quality and hardening phase — the final quality gauntlet proving production readiness with evidence. Adapted from msitarzewski/agency-agents.
---

## Triggers

- hardening phase
- quality gate
- production readiness
- integration testing
- load testing
- compliance audit
- performance certification
- reality check
- security validation
- final QA
- cross-device testing
- regression testing
- stress testing
- pre-production
- hardening sprint
- quality assurance final

## Instructions

Phase 4 is the final quality gauntlet. The Reality Checker defaults to "NEEDS WORK" — you must prove production readiness with overwhelming evidence. First implementations typically need 2-3 revision cycles, and that's healthy. Duration: 3-7 days.

### Pre-Conditions

Verify before starting:
1. Phase 3 Quality Gate passed (all tasks QA'd)
2. Phase 3 Handoff Package received
3. All features implemented and individually verified

### Critical Mindset

The Reality Checker's default verdict is NEEDS WORK. Production readiness requires:
- Complete user journeys working end-to-end
- Cross-device consistency (desktop, tablet, mobile)
- Performance under load (not just happy path)
- Security validation (not just "we added auth")
- Specification compliance (every requirement, not most)

### Step 1: Evidence Collection (Day 1-2, All Parallel)

Use `organization_spawn` or `swarm_spawn` to activate in parallel:

**Evidence Collector — Comprehensive Visual Evidence**:
- Full screenshot suite: Desktop (1920x1080), Tablet (768x1024), Mobile (375x667) for every page/view
- Interaction evidence: navigation flows, form interactions, modals, accordions
- Theme evidence: light mode, dark mode, system preference detection
- Error state evidence: 404 pages, form validation, network errors, empty states
- Timeline: 2 days.

**API Tester — Full API Regression**:
- All endpoints tested (GET, POST, PUT, DELETE) with auth verification
- Input validation, error response verification
- Integration testing (cross-service, database, external APIs)
- Edge cases: rate limiting, large payloads, concurrent requests, malformed input
- Timeline: 2 days.

**Performance Benchmarker — Load Testing**:
- Load test at 10x expected traffic (P50, P95, P99 response times, throughput, error rate, resource utilization)
- Core Web Vitals: LCP < 2.5s, FID < 100ms, CLS < 0.1
- Database performance: query times, connection pool, index effectiveness
- Stress test: breaking point, graceful degradation, recovery time
- Timeline: 2 days.

**Legal Compliance Checker — Final Compliance Audit**:
- Privacy compliance: privacy policy, consent management, data subject rights, cookies
- Security compliance: encryption, authentication, input sanitization, OWASP Top 10
- Regulatory compliance: GDPR, CCPA, industry-specific requirements
- Accessibility compliance: WCAG 2.1 AA, screen reader, keyboard navigation
- Timeline: 2 days.

### Step 2: Analysis (Day 3-4, Parallel, after Step 1)

**Test Results Analyzer — Quality Metrics Aggregation**:
- Aggregate quality dashboard (overall score, category breakdown, issue severity distribution)
- Issue prioritization: Critical (must fix), High (should fix), Medium (next sprint), Low (backlog)
- Risk assessment: production readiness probability, remaining risk areas

**Workflow Optimizer — Process Efficiency Review**:
- Dev-QA loop efficiency (first-pass rate, average retries)
- Bottleneck identification, time-to-resolution
- Improvement recommendations for Phase 6 operations

**Infrastructure Maintainer — Production Readiness Check**:
- All services healthy, auto-scaling tested, load balancer verified, SSL/TLS valid
- Monitoring validated, alert rules tested, dashboards accessible, logs aggregating
- Disaster recovery: backups operational, recovery procedures tested, failover verified
- Security: firewall rules, access controls, secrets management, vulnerability scan clean

### Step 3: Final Judgment (Day 5-7, Sequential)

**Reality Checker — THE FINAL VERDICT**:
Use `organization_delegate` for the Reality Checker:

1. Reality Check Commands — verify what was actually built (ls, grep for claimed features)
2. QA Cross-Validation — cross-reference all previous QA findings
3. End-to-End Validation — test COMPLETE user journeys (not individual features)
4. Specification Reality Check — quote EXACT spec text vs. actual implementation, document EVERY gap

Verdict options:
- **READY**: Overwhelming evidence of production readiness (rare first pass) -> Phase 5
- **NEEDS WORK**: Specific issues with fix list (expected) -> return to Phase 3 Dev-QA loop
- **NOT READY**: Major architectural issues -> return to Phase 1/2

Expected: 2-3 revision cycles is normal. B/B+ rating on first pass is expected.

Use `knowledge_write` to persist all certification reports and the Reality Checker verdict.

## Deliverables

- [ ] Full screenshot evidence suite (desktop, tablet, mobile, all pages)
- [ ] API regression report (pass/fail per endpoint)
- [ ] Performance Certification Report (load test, Core Web Vitals, stress test)
- [ ] Compliance Certification Report (privacy, security, regulatory, accessibility)
- [ ] Quality Metrics Dashboard (aggregate scores, issue prioritization)
- [ ] Infrastructure Readiness Report (production environment validated)
- [ ] Reality Checker Integration Report with verdict

## Success Metrics

- All critical user journeys working end-to-end
- Cross-device consistency (desktop + tablet + mobile)
- P95 < 200ms, LCP < 2.5s, uptime > 99.9%
- Zero critical security vulnerabilities
- All regulatory requirements met
- 100% specification compliance
- Production environment validated and ready
- Reality Checker issues READY verdict
