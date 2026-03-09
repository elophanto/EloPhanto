---
name: accessibility-auditing
description: Audit interfaces against WCAG 2.2 standards, test with assistive technologies, and ensure inclusive design beyond what automated tools catch. Adapted from msitarzewski/agency-agents.
---

## Triggers

- accessibility audit
- WCAG compliance
- screen reader testing
- keyboard navigation
- accessibility check
- a11y audit
- ARIA review
- color contrast
- assistive technology
- inclusive design
- focus management
- alt text review
- accessible components
- Section 508
- accessibility remediation

## Instructions

### Automated Baseline Scan
- Run axe-core against all pages using `shell_execute`: `npx @axe-core/cli [url] --tags wcag2a,wcag2aa,wcag22aa`
- Run Lighthouse accessibility audit
- Check color contrast across the design system
- Review heading hierarchy and landmark structure
- Identify all custom interactive components for manual testing
- Use `browser_navigate` to inspect pages visually

### Manual Assistive Technology Testing
- Navigate every user journey with keyboard only -- no mouse
- Complete all critical flows with a screen reader (VoiceOver on macOS, NVDA on Windows)
- Test at 200% and 400% browser zoom for content overlap and horizontal scrolling
- Enable reduced motion and verify animations respect `prefers-reduced-motion`
- Enable high contrast mode and verify content remains visible and usable

### Component-Level Deep Dive
- Audit every custom interactive component against WAI-ARIA Authoring Practices
- Verify form validation announces errors to screen readers
- Test dynamic content (modals, toasts, live updates) for proper focus management
- Check all images, icons, and media for appropriate text alternatives
- Validate data tables for proper header associations

### Standards-Based Assessment
- Always reference specific WCAG 2.2 success criteria by number and name
- Classify severity: Critical, Serious, Moderate, Minor
- Never rely solely on automated tools -- they miss focus order, reading order, ARIA misuse, cognitive barriers
- Push for semantic HTML before ARIA -- the best ARIA is the ARIA you don't need
- Consider the full spectrum: visual, auditory, motor, cognitive, vestibular, situational disabilities

### Report and Remediation
- Document every issue with WCAG criterion, severity, evidence, and fix
- Prioritize by user impact -- a missing form label blocks task completion
- Provide code-level fix examples, not just descriptions
- Use `knowledge_write` to store remediation patterns
- Schedule re-audit after fixes are implemented

## Deliverables

### Accessibility Audit Report Template

```markdown
# Accessibility Audit Report

## Audit Overview
**Product/Feature**: [Name and scope]
**Standard**: WCAG 2.2 Level AA
**Date**: [Audit date]
**Tools Used**: [axe-core, Lighthouse, screen reader(s), keyboard testing]

## Testing Methodology
**Automated Scanning**: [Tools and pages scanned]
**Screen Reader Testing**: [VoiceOver/NVDA/JAWS -- OS and browser versions]
**Keyboard Testing**: [All interactive flows tested keyboard-only]
**Visual Testing**: [Zoom 200%/400%, high contrast, reduced motion]

## Summary
**Total Issues Found**: [Count]
- Critical: [Count] -- Blocks access entirely for some users
- Serious: [Count] -- Major barriers requiring workarounds
- Moderate: [Count] -- Causes difficulty but has workarounds
- Minor: [Count] -- Annoyances that reduce usability

**WCAG Conformance**: DOES NOT CONFORM / PARTIALLY CONFORMS / CONFORMS
**Assistive Technology Compatibility**: FAIL / PARTIAL / PASS

## Issues Found

### Issue 1: [Descriptive title]
**WCAG Criterion**: [Number -- Name] (Level A/AA/AAA)
**Severity**: Critical / Serious / Moderate / Minor
**User Impact**: [Who is affected and how]
**Location**: [Page, component, or element]
**Current State**: [code snippet]
**Recommended Fix**: [code snippet]
**Testing Verification**: [How to confirm the fix works]

## What's Working Well
- [Positive findings -- reinforce good patterns]

## Remediation Priority
### Immediate (Critical/Serious -- fix before release)
### Short-term (Moderate -- fix within next sprint)
### Ongoing (Minor -- address in regular maintenance)
```

### Keyboard Navigation Checklist

```markdown
## Global Navigation
- [ ] All interactive elements reachable via Tab
- [ ] Tab order follows visual layout logic
- [ ] Skip navigation link present and functional
- [ ] No keyboard traps
- [ ] Focus indicator visible on every interactive element
- [ ] Escape closes modals, dropdowns, overlays
- [ ] Focus returns to trigger element after modal closes
```

## Success Metrics

- Products achieve genuine WCAG 2.2 AA conformance, not just passing automated scans
- Screen reader users can complete all critical user journeys independently
- Keyboard-only users can access every interactive element without traps
- Accessibility issues caught during development, not after launch
- Teams build accessibility knowledge and prevent recurring issues
- Zero critical or serious accessibility barriers in production releases
