---
name: analytics-reporting
description: Transform raw data into actionable business insights with dashboards, statistical analysis, and KPI tracking. Adapted from msitarzewski/agency-agents.
---

## Triggers

- analytics report
- dashboard creation
- KPI tracking
- data visualization
- statistical analysis
- business metrics
- customer segmentation
- marketing attribution
- data insights
- trend analysis
- performance dashboard
- revenue analysis
- forecasting
- data quality
- business intelligence

## Instructions

### Data Discovery and Validation
- Assess data quality and completeness before analysis using `shell_execute` for data inspection
- Identify key business metrics and stakeholder requirements
- Establish statistical significance thresholds and confidence levels
- Validate data accuracy with cross-referencing and consistency checks

### Analysis Framework Development
- Design analytical methodology with clear hypothesis and success metrics
- Create reproducible data pipelines with version control and documentation
- Implement statistical testing and confidence interval calculations
- Build automated data quality monitoring and anomaly detection

### Insight Generation and Visualization
- Develop interactive dashboards with drill-down capabilities
- Create executive summaries with key findings and actionable recommendations
- Design A/B test analysis with statistical significance testing
- Build predictive models with accuracy measurement and confidence intervals
- Use `knowledge_write` to store analytical frameworks and findings for reuse

### Business Impact Measurement
- Track analytical recommendation implementation and business outcome correlation
- Create feedback loops for continuous analytical improvement
- Establish KPI monitoring with automated alerting for threshold breaches
- Use `web_search` to gather industry benchmarks for comparative analysis

### Technical Capabilities
- SQL optimization for complex analytical queries and data warehouse management
- Python/R programming for statistical analysis and machine learning
- RFM customer segmentation with lifetime value calculation
- Multi-touch marketing attribution modeling
- A/B testing design with proper statistical power analysis

## Deliverables

### Analysis Report Template

```markdown
# [Analysis Name] - Business Intelligence Report

## Executive Summary

### Key Findings
**Primary Insight**: [Most important business insight with quantified impact]
**Secondary Insights**: [2-3 supporting insights with data evidence]
**Statistical Confidence**: [Confidence level and sample size validation]
**Business Impact**: [Quantified impact on revenue, costs, or efficiency]

### Immediate Actions Required
1. **High Priority**: [Action with expected impact and timeline]
2. **Medium Priority**: [Action with cost-benefit analysis]
3. **Long-term**: [Strategic recommendation with measurement plan]

## Detailed Analysis

### Data Foundation
**Data Sources**: [List with quality assessment]
**Sample Size**: [Number of records with statistical power analysis]
**Time Period**: [Analysis timeframe with seasonality considerations]
**Data Quality Score**: [Completeness, accuracy, consistency metrics]

### Statistical Analysis
**Methodology**: [Statistical methods with justification]
**Hypothesis Testing**: [Null and alternative hypotheses with results]
**Confidence Intervals**: [95% confidence intervals for key metrics]
**Effect Size**: [Practical significance assessment]

### Business Metrics
**Current Performance**: [Baseline metrics with trend analysis]
**Performance Drivers**: [Key factors influencing outcomes]
**Benchmark Comparison**: [Industry or internal benchmarks]
**Improvement Opportunities**: [Quantified improvement potential]

## Recommendations

### Implementation Roadmap
**Phase 1 (30 days)**: [Immediate actions with success metrics]
**Phase 2 (90 days)**: [Medium-term initiatives with measurement plan]
**Phase 3 (6 months)**: [Long-term strategic changes with evaluation criteria]

### Success Measurement
**Primary KPIs**: [Key performance indicators with targets]
**Secondary Metrics**: [Supporting metrics with benchmarks]
**Monitoring Frequency**: [Review schedule and reporting cadence]
```

### Executive Dashboard SQL Template

```sql
WITH monthly_metrics AS (
  SELECT
    DATE_TRUNC('month', date) as month,
    SUM(revenue) as monthly_revenue,
    COUNT(DISTINCT customer_id) as active_customers,
    AVG(order_value) as avg_order_value,
    SUM(revenue) / COUNT(DISTINCT customer_id) as revenue_per_customer
  FROM transactions
  WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH)
  GROUP BY DATE_TRUNC('month', date)
),
growth_calculations AS (
  SELECT *,
    LAG(monthly_revenue, 1) OVER (ORDER BY month) as prev_month_revenue,
    (monthly_revenue - LAG(monthly_revenue, 1) OVER (ORDER BY month)) /
     LAG(monthly_revenue, 1) OVER (ORDER BY month) * 100 as revenue_growth_rate
  FROM monthly_metrics
)
SELECT
  month, monthly_revenue, active_customers, avg_order_value,
  revenue_per_customer, revenue_growth_rate,
  CASE
    WHEN revenue_growth_rate > 10 THEN 'High Growth'
    WHEN revenue_growth_rate > 0 THEN 'Positive Growth'
    ELSE 'Needs Attention'
  END as growth_status
FROM growth_calculations
ORDER BY month DESC;
```

## Success Metrics

- Analysis accuracy exceeds 95% with proper statistical validation
- Business recommendations achieve 70%+ implementation rate by stakeholders
- Dashboard adoption reaches 95% monthly active usage by target users
- Analytical insights drive measurable business improvement (20%+ KPI improvement)
- Stakeholder satisfaction with analysis quality and timeliness exceeds 4.5/5

## Verify

- Every non-trivial claim in the output is paired with a source link, file path, or query result, not stated as a bare assertion
- Sources span at least 2-3 independent origins; single-source conclusions are flagged as such
- Counter-evidence or limitations are explicitly listed, not omitted to make the narrative tidier
- Numbers in the deliverable carry units, time windows, and an as-of date (e.g., '$1.2M ARR as of 2026-04-30')
- Direct quotes are verbatim and cite their location; paraphrases are marked as such
- Out-of-date or unreachable sources are noted in the bibliography rather than silently dropped
