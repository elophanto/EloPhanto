---
name: executive-summaries
description: Transform complex business inputs into concise, actionable executive summaries using McKinsey SCQA, BCG Pyramid Principle, and Bain frameworks. Adapted from msitarzewski/agency-agents.
---

## Triggers

- executive summary
- summarize for executives
- C-suite briefing
- strategy summary
- business summary
- SCQA framework
- pyramid principle
- decision brief
- board summary
- management summary
- strategic overview
- key findings summary
- business impact summary
- action recommendations

## Instructions

### Intake and Analysis
- Review provided business content thoroughly
- Identify critical insights and quantifiable data points
- Map content to SCQA framework (Situation-Complication-Question-Answer)
- Assess data quality and identify gaps
- Use `web_search` to fill in missing industry context or benchmarks when needed

### Structure Development
- Apply Pyramid Principle to organize insights hierarchically
- Prioritize findings by business impact magnitude
- Quantify every claim with data from source material
- Identify strategic implications for each finding

### Executive Summary Generation
- Draft concise situation overview establishing context and urgency
- Present 3-5 key findings with bold strategic implications
- Quantify business impact with specific metrics and timeframes
- Structure 3-4 prioritized, actionable recommendations with clear ownership
- Use `knowledge_write` to store successful summary patterns

### Quality Standards
- Total length: 325-475 words (500 max)
- Every key finding must include at least 1 quantified or comparative data point
- Bold strategic implications in findings
- Order content by business impact
- Include specific timelines, owners, and expected results in recommendations
- Tone: Decisive, factual, and outcome-driven
- No assumptions beyond provided data

## Deliverables

### Executive Summary Template

```markdown
## 1. SITUATION OVERVIEW [50-75 words]
- What is happening and why it matters now
- Current vs. desired state gap

## 2. KEY FINDINGS [125-175 words]
- 3-5 most critical insights (each with at least 1 quantified or comparative data point)
- **Bold the strategic implication in each**
- Order by business impact

## 3. BUSINESS IMPACT [50-75 words]
- Quantify potential gain/loss (revenue, cost, market share)
- Note risk or opportunity magnitude (% or probability)
- Define time horizon for realization

## 4. RECOMMENDATIONS [75-100 words]
- 3-4 prioritized actions labeled (Critical / High / Medium)
- Each with: owner + timeline + expected result
- Include resource or cross-functional needs if material

## 5. NEXT STEPS [25-50 words]
- 2-3 immediate actions (30-day horizon or less)
- Identify decision point + deadline
```

## Success Metrics

- Summary enables executive decision in < 3 minutes reading time
- Every key finding includes quantified data points (100% compliance)
- Word count stays within 325-475 range (500 max)
- Strategic implications are bold and action-oriented
- Recommendations include owner, timeline, and expected result
- Executives request implementation based on the summary
- Zero assumptions made beyond provided data

## Verify

- Every non-trivial claim in the output is paired with a source link, file path, or query result, not stated as a bare assertion
- Sources span at least 2-3 independent origins; single-source conclusions are flagged as such
- Counter-evidence or limitations are explicitly listed, not omitted to make the narrative tidier
- Numbers in the deliverable carry units, time windows, and an as-of date (e.g., '$1.2M ARR as of 2026-04-30')
- Direct quotes are verbatim and cite their location; paraphrases are marked as such
- Out-of-date or unreachable sources are noted in the bibliography rather than silently dropped
