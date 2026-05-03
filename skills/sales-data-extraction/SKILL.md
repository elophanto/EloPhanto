---
name: sales-data-extraction
description: Monitors Excel files and extracts key sales metrics (MTD, YTD, Year End) for internal live reporting pipelines. Adapted from msitarzewski/agency-agents.
---

## Triggers

- sales data extraction
- Excel parsing
- metric extraction
- sales import
- file monitoring
- spreadsheet processing
- MTD extraction
- YTD extraction
- revenue extraction
- quota attainment calculation
- sales pipeline import
- Excel file watcher
- data ingestion

## Instructions

### Core Mission
Monitor designated Excel file directories for new or updated sales reports. Extract key metrics (Month to Date, Year to Date, Year End projections), normalize, and persist them for downstream reporting and distribution.

### Critical Rules
1. Never overwrite existing metrics without a clear update signal (new file version).
2. Always log every import: file name, rows processed, rows failed, timestamps.
3. Match representatives by email or full name; skip unmatched rows with a warning.
4. Handle flexible schemas: use fuzzy column name matching for revenue, units, deals, quota.
5. Detect metric type from sheet names (MTD, YTD, Year End) with sensible defaults.

### File Monitoring
- Watch directory for .xlsx and .xls files using filesystem watchers.
- Ignore temporary Excel lock files (~$).
- Wait for file write completion before processing.

### Metric Extraction
- Parse all sheets in a workbook.
- Map columns flexibly: revenue/sales/total_sales, units/qty/quantity, etc.
- Calculate quota attainment automatically when quota and revenue are present.
- Handle currency formatting ($, commas) in numeric fields.

### Data Persistence
- Bulk insert extracted metrics into database.
- Use transactions for atomicity.
- Record source file in every metric row for audit trail.

### Workflow Process
1. File detected in watch directory.
2. Log import as "processing".
3. Read workbook, iterate sheets.
4. Detect metric type per sheet.
5. Map rows to representative records.
6. Insert validated metrics into database.
7. Update import log with results.
8. Emit completion event for downstream agents.

## Deliverables

- Filesystem watcher for Excel file directories
- Flexible column mapping engine for varying Excel formats
- Metric extraction pipeline (MTD, YTD, Year End)
- Database persistence layer with transaction support
- Import audit log with per-file and per-row tracking
- Completion event emitter for downstream agent coordination

## Success Metrics

- 100% of valid Excel files processed without manual intervention
- < 2% row-level failures on well-formatted reports
- < 5 second processing time per file
- Complete audit trail for every import

## Verify

- Every non-trivial claim in the output is paired with a source link, file path, or query result, not stated as a bare assertion
- Sources span at least 2-3 independent origins; single-source conclusions are flagged as such
- Counter-evidence or limitations are explicitly listed, not omitted to make the narrative tidier
- Numbers in the deliverable carry units, time windows, and an as-of date (e.g., '$1.2M ARR as of 2026-04-30')
- Direct quotes are verbatim and cite their location; paraphrases are marked as such
- Out-of-date or unreachable sources are noted in the bibliography rather than silently dropped
