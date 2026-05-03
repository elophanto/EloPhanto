---
name: data-consolidation
description: Consolidates extracted sales data into live reporting dashboards with territory, rep, and pipeline summaries. Adapted from msitarzewski/agency-agents.
---

## Triggers

- data consolidation
- sales dashboard
- territory summary
- rep performance
- pipeline snapshot
- sales metrics
- revenue attainment
- sales aggregation
- territory report
- quota attainment
- pipeline analysis
- sales trend
- top performers
- MTD YTD reporting

## Instructions

### Core Mission
Aggregate and consolidate sales metrics from all territories, representatives, and time periods into structured reports and dashboard views. Provide territory summaries, rep performance rankings, pipeline snapshots, trend analysis, and top performer highlights.

### Critical Rules
1. Always use latest data: queries pull the most recent metric_date per type.
2. Calculate attainment accurately: revenue / quota * 100, handle division by zero.
3. Aggregate by territory: group metrics for regional visibility.
4. Include pipeline data: merge lead pipeline with sales metrics for full picture.
5. Support multiple views: MTD, YTD, Year End summaries available on demand.

### Workflow Process
1. Receive request for dashboard or territory report.
2. Execute parallel queries for all data dimensions.
3. Aggregate and calculate derived metrics.
4. Structure response in dashboard-friendly JSON.
5. Include generation timestamp for staleness detection.

## Deliverables

### Dashboard Report
- Territory performance summary (YTD/MTD revenue, attainment, rep count)
- Individual rep performance with latest metrics
- Pipeline snapshot by stage (count, value, weighted value)
- Trend data over trailing 6 months
- Top 5 performers by YTD revenue

### Territory Report
- Territory-specific deep dive
- All reps within territory with their metrics
- Recent metric history (last 50 entries)

## Success Metrics

- Dashboard loads in < 1 second
- Reports refresh automatically every 60 seconds
- All active territories and reps represented
- Zero data inconsistencies between detail and summary views

## Verify

- Every non-trivial claim in the output is paired with a source link, file path, or query result, not stated as a bare assertion
- Sources span at least 2-3 independent origins; single-source conclusions are flagged as such
- Counter-evidence or limitations are explicitly listed, not omitted to make the narrative tidier
- Numbers in the deliverable carry units, time windows, and an as-of date (e.g., '$1.2M ARR as of 2026-04-30')
- Direct quotes are verbatim and cite their location; paraphrases are marked as such
- Out-of-date or unreachable sources are noted in the bibliography rather than silently dropped
