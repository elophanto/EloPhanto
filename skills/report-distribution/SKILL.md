---
name: report-distribution
description: Automates distribution of consolidated sales reports to representatives based on territorial parameters with audit trailing. Adapted from msitarzewski/agency-agents.
---

## Triggers

- report distribution
- email reports
- territory routing
- scheduled reports
- distribution automation
- report delivery
- manager summary
- distribution audit
- report scheduling
- sales report email
- delivery tracking
- distribution log

## Instructions

### Core Mission
Automate the distribution of consolidated sales reports to representatives based on their territorial assignments. Support scheduled daily and weekly distributions, plus manual on-demand sends. Track all distributions for audit and compliance.

### Critical Rules
1. Territory-based routing: reps only receive reports for their assigned territory.
2. Manager summaries: admins and managers receive company-wide roll-ups.
3. Log everything: every distribution attempt is recorded with status (sent/failed).
4. Schedule adherence: daily reports at 8:00 AM weekdays, weekly summaries every Monday at 7:00 AM.
5. Graceful failures: log errors per recipient, continue distributing to others.

### Workflow Process
1. Scheduled job triggers or manual request received.
2. Query territories and associated active representatives.
3. Generate territory-specific or company-wide report via Data Consolidation Agent.
4. Format report as HTML email.
5. Send via SMTP transport.
6. Log distribution result (sent/failed) per recipient.
7. Surface distribution history in reports UI.

## Deliverables

### Email Reports
- HTML-formatted territory reports with rep performance tables
- Company summary reports with territory comparison tables
- Professional styling consistent with branding

### Distribution Schedules
- Daily territory reports (Mon-Fri, 8:00 AM)
- Weekly company summary (Monday, 7:00 AM)
- Manual distribution trigger via admin dashboard

### Audit Trail
- Distribution log with recipient, territory, status, timestamp
- Error messages captured for failed deliveries
- Queryable history for compliance reporting

## Success Metrics

- 99%+ scheduled delivery rate
- All distribution attempts logged
- Failed sends identified and surfaced within 5 minutes
- Zero reports sent to wrong territory

## Verify

- Every non-trivial claim in the output is paired with a source link, file path, or query result, not stated as a bare assertion
- Sources span at least 2-3 independent origins; single-source conclusions are flagged as such
- Counter-evidence or limitations are explicitly listed, not omitted to make the narrative tidier
- Numbers in the deliverable carry units, time windows, and an as-of date (e.g., '$1.2M ARR as of 2026-04-30')
- Direct quotes are verbatim and cite their location; paraphrases are marked as such
- Out-of-date or unreachable sources are noted in the bibliography rather than silently dropped
