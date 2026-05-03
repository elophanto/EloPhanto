---
name: agency-phase-5-launch
description: Launch and growth phase — coordinate go-to-market execution across all channels for maximum impact. Adapted from msitarzewski/agency-agents.
---

## Triggers

- launch phase
- go to market
- product launch
- marketing campaign launch
- deployment day
- blue-green deployment
- launch checklist
- growth activation
- user acquisition
- launch week
- post-launch
- launch optimization
- channel activation
- launch coordination
- release management

## Instructions

Phase 5 coordinates go-to-market execution across all channels simultaneously. Maximum impact at launch. Every marketing agent fires in concert while engineering ensures stability. Duration: 2-4 weeks (T-7 through T+14).

### Pre-Conditions

Verify before starting:
1. Phase 4 Quality Gate passed (Reality Checker READY verdict)
2. Phase 4 Handoff Package received
3. Production deployment plan approved
4. Marketing content pipeline ready (from Phase 3 Track B)

### T-7: Pre-Launch Week

Use `organization_spawn` to activate content and technical preparation in parallel:

**Content & Campaign Preparation**:
- Content Creator: Finalize all launch content, queue in publishing platforms, prepare response templates
- Social Media Strategist: Finalize cross-platform campaign assets, schedule teasers, coordinate influencers
- Growth Hacker: Arm viral mechanics (referral codes, sharing incentives), configure growth tracking, set up funnel analytics
- App Store Optimizer (if mobile): Finalize store listing, submit for review, configure in-app review prompts

**Technical Preparation**:
- DevOps Automator: Prepare blue-green deployment, verify rollback procedures, configure feature flags, test pipeline
- Infrastructure Maintainer: Configure auto-scaling for 10x traffic, verify monitoring/alerting, test disaster recovery
- Project Shepherd: Distribute launch checklist, confirm dependencies, set up launch day comms, brief stakeholders

### T-1: Launch Eve Final Checklist

Technical: Blue-green tested, rollback verified, auto-scaling configured, monitoring live, incident response on standby, feature flags configured.

Content: All content queued/scheduled, email sequences armed, social posts scheduled, blog posts ready, press materials distributed.

Marketing: Viral mechanics tested, referral system operational, analytics tracking verified, ad campaigns ready, community engagement plan ready.

Support: Support team briefed, FAQ/help docs published, escalation procedures confirmed, feedback collection active.

### T-0: Launch Day

**Hour 0 — Deployment**: Use `organization_delegate` to DevOps Automator:
1. Execute blue-green deployment to production
2. Run health checks on all services
3. Verify database migrations complete
4. Confirm all endpoints responding
5. Switch traffic to new deployment
6. Monitor error rates for 15 minutes
7. Confirm DEPLOYMENT SUCCESSFUL or ROLLBACK

**Hour 1-2 — Marketing Activation**: Activate platform agents in parallel:
- Twitter Engager: Publish launch thread, engage with responses, monitor mentions
- Reddit Community Builder: Authentic launch announcement, engage with comments
- Instagram Curator: Publish visual content, stories with demos
- TikTok Strategist: Publish launch videos, monitor viral potential

**Hour 2-8 — Monitoring & Response**:
- Support Responder: Handle inquiries, document common issues, escalate technical problems
- Analytics Reporter: Real-time metrics dashboard, hourly reports, channel attribution
- Feedback Synthesizer: Monitor all channels, categorize feedback, identify critical issues

### T+1 to T+7: Post-Launch Week

Daily cadence:
- Morning: Analytics Reporter (daily metrics), Feedback Synthesizer (feedback summary), Infrastructure Maintainer (system health), Growth Hacker (channel performance)
- Afternoon: Content Creator (response content), Social Media Strategist (engagement optimization), Experiment Tracker (A/B results), Support Responder (issue resolution)
- Evening: Executive Summary Generator (stakeholder briefing), Project Shepherd (coordination), DevOps Automator (hotfixes if needed)

### T+7 to T+14: Optimization Week

- Growth Hacker: Analyze first-week data, optimize funnels, scale winning channels, refine viral mechanics
- Analytics Reporter: Week 1 comprehensive analysis, cohort analysis, retention curves
- Experiment Tracker: Launch systematic A/B tests (onboarding, pricing, feature discovery)
- Executive Summary Generator: Week 1 executive summary, key metrics vs. targets, recommendations

### Gate Decision

Dual sign-off: Studio Producer (strategic) + Analytics Reporter (data)

- **STABLE**: Product launched, systems stable, growth active -> Phase 6
- **CRITICAL**: Major issues requiring immediate engineering response -> Hotfix cycle
- **ROLLBACK**: Fundamental problems -> Revert deployment, return to Phase 4

Use `knowledge_write` to persist launch metrics, feedback themes, and system performance baselines.

## Deliverables

- [ ] Successful zero-downtime deployment
- [ ] All marketing channels activated
- [ ] Real-time monitoring dashboard operational
- [ ] User support operational
- [ ] Feedback loop operational
- [ ] Week 1 analytics report
- [ ] Week 1 executive summary
- [ ] Growth channel performance analysis
- [ ] A/B test results from launch experiments

## Success Metrics

- Zero-downtime deployment successful
- Systems stable (no P0/P1 in 48 hours)
- User acquisition channels active and tracking
- Feedback loop operational
- Stakeholders informed with executive summaries
- Support operational with < 4hr response time
- Growth metrics tracking and optimizing

## Verify

- The deliverable for this phase exists as a concrete artifact (doc, ticket, board, repo) and its location is shared, not described
- Each commitment has an owner name, a due date, and a definition-of-done that someone other than the author could check
- Risks are listed with likelihood/impact and a named mitigation, not as a generic 'risks: TBD' bullet
- Dependencies on other teams/vendors/agents are explicit; an ack from each dependency is recorded or marked 'pending'
- Success criteria for the next phase are numeric or otherwise objectively testable
- A rollback / kill-switch / 'we will stop if X' criterion is written down before work starts
