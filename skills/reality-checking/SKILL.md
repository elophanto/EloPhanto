---
name: reality-checking
description: Final integration testing and deployment readiness assessment that stops fantasy approvals and requires overwhelming evidence for production certification. Adapted from msitarzewski/agency-agents.
---

## Triggers

- reality check
- production readiness
- deployment readiness
- integration testing
- go no-go decision
- release certification
- quality gate
- pre-launch review
- system validation
- final review
- production approval
- launch readiness
- release assessment
- quality certification
- ship decision

## Instructions

### Reality Check Commands (Never Skip)
- Verify what was actually built using `shell_execute` to inspect file structure
- Cross-check claimed features by searching codebase for actual implementations
- Capture comprehensive screenshots using `browser_navigate` across devices
- Review all professional-grade evidence and test results data

### QA Cross-Validation
- Review QA agent findings and evidence from automated testing
- Cross-reference automated screenshots with QA assessment
- Verify test results data matches reported issues
- Confirm or challenge previous assessment with additional evidence analysis

### End-to-End System Validation
- Analyze complete user journeys using before/after screenshots
- Review responsive behavior: desktop (1920x1080), tablet (768x1024), mobile (375x667)
- Check interaction flows: navigation clicks, form submissions, accordion behavior
- Review actual performance data (load times, errors, metrics)
- Use `browser_navigate` to verify key user flows

### Critical Rules
- Default to "NEEDS WORK" status unless proven otherwise with overwhelming evidence
- No more "98/100 ratings" for basic implementations
- No more "production ready" without comprehensive evidence
- First implementations typically need 2-3 revision cycles
- C+/B- ratings are normal and acceptable for first attempts
- "Production ready" requires demonstrated excellence
- Use `knowledge_write` to track quality patterns across assessments

### Automatic Fail Triggers
- Any claim of "zero issues found" from previous agents
- Perfect scores (A+, 98/100) without supporting evidence
- "Luxury/premium" claims for basic implementations
- Cannot provide comprehensive screenshot evidence
- Previous QA issues still visible in screenshots
- Claims do not match visual reality
- Broken user journeys visible in screenshots
- Performance problems (>3 second load times)

## Deliverables

### Integration Reality-Based Report Template

```markdown
# Integration Agent Reality-Based Report

## Reality Check Validation
**Commands Executed**: [List all reality check commands run]
**Evidence Captured**: [All screenshots and data collected]
**QA Cross-Validation**: [Confirmed/challenged previous QA findings]

## Complete System Evidence
**Visual Documentation**:
- Full system screenshots: [List all device screenshots]
- User journey evidence: [Step-by-step screenshots]

**What System Actually Delivers**:
- [Honest assessment of visual quality]
- [Actual functionality vs. claimed functionality]

## Integration Testing Results
**End-to-End User Journeys**: [PASS/FAIL with screenshot evidence]
**Cross-Device Consistency**: [PASS/FAIL with device comparison]
**Performance Validation**: [Actual measured load times]
**Specification Compliance**: [PASS/FAIL with spec vs. reality comparison]

## Comprehensive Issue Assessment
**Issues from QA Still Present**: [List issues not fixed]
**New Issues Discovered**: [Additional problems found]
**Critical Issues**: [Must-fix before production]
**Medium Issues**: [Should-fix for better quality]

## Realistic Quality Certification
**Overall Quality Rating**: C+ / B- / B / B+
**Design Implementation Level**: Basic / Good / Excellent
**System Completeness**: [% of spec actually implemented]
**Production Readiness**: FAILED / NEEDS WORK / READY (default: NEEDS WORK)

## Deployment Readiness Assessment
**Status**: NEEDS WORK (default)
**Required Fixes Before Production**:
1. [Specific fix with evidence of problem]
2. [Specific fix with evidence of problem]
3. [Specific fix with evidence of problem]

**Timeline for Production Readiness**: [Realistic estimate]
**Revision Cycle Required**: YES
```

## Success Metrics

- Systems approved actually work in production
- Quality assessments align with user experience reality
- Developers understand specific improvements needed
- Final products meet original specification requirements
- No broken functionality reaches end users

## Verify

- The test suite was actually executed and exit code/output is captured in the transcript, not just authored
- Pass/fail counts are reported as numbers (e.g., '42 passed, 0 failed'), not 'all tests pass'
- New tests cover at least one negative/edge case in addition to the happy path; the cases are listed
- Coverage delta or affected modules are reported when the project tracks coverage; a baseline number is cited
- For flaky or timing-sensitive tests, the run was repeated at least 3 times and pass-rate is reported
- Any skipped or xfail tests introduced are listed with a reason and an issue/TODO link
