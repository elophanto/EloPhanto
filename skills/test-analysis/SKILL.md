---
name: test-analysis
description: Comprehensive test result evaluation, quality metrics analysis, defect prediction, and release readiness assessment with statistical rigor. Adapted from msitarzewski/agency-agents.
---

## Triggers

- test results analysis
- quality metrics
- test coverage
- defect analysis
- release readiness
- quality assessment
- test report
- failure pattern
- defect prediction
- quality score
- test effectiveness
- regression analysis
- quality trends
- go no-go
- test summary

## Instructions

### Data Collection and Validation
- Aggregate test results from multiple sources (unit, integration, performance, security)
- Validate data quality and completeness with statistical checks using `shell_execute`
- Normalize test metrics across different testing frameworks and tools
- Establish baseline metrics for trend analysis and comparison

### Statistical Analysis and Pattern Recognition
- Apply statistical methods to identify significant patterns and trends
- Calculate confidence intervals and statistical significance for all findings
- Perform correlation analysis between different quality metrics
- Identify anomalies and outliers that require investigation
- Use `knowledge_write` to store quality baselines and trend data

### Risk Assessment and Predictive Modeling
- Develop predictive models for defect-prone areas and quality risks
- Assess release readiness with quantitative risk assessment
- Create quality forecasting models for project planning
- Generate recommendations with ROI analysis and priority ranking

### Reporting and Continuous Improvement
- Create stakeholder-specific reports with actionable insights
- Establish automated quality monitoring and alerting systems
- Track improvement implementation and validate effectiveness
- Update analysis models based on new data and feedback

### Analysis Standards
- Always use statistical methods to validate conclusions and recommendations
- Provide confidence intervals and statistical significance for all quality claims
- Base recommendations on quantifiable evidence rather than assumptions
- Consider multiple data sources and cross-validate findings
- Document methodology and assumptions for reproducible analysis
- Prioritize user experience and product quality over release timelines

## Deliverables

### Test Results Analysis Report Template

```markdown
# [Project Name] Test Results Analysis Report

## Executive Summary
**Overall Quality Score**: [Composite score with trend analysis]
**Release Readiness**: [GO/NO-GO with confidence level and reasoning]
**Key Quality Risks**: [Top 3 risks with probability and impact assessment]
**Recommended Actions**: [Priority actions with ROI analysis]

## Test Coverage Analysis
**Code Coverage**: [Line/Branch/Function coverage with gap analysis]
**Functional Coverage**: [Feature coverage with risk-based prioritization]
**Test Effectiveness**: [Defect detection rate and test quality metrics]
**Coverage Trends**: [Historical coverage trends and improvement tracking]

## Quality Metrics and Trends
**Pass Rate Trends**: [Test pass rate over time with statistical analysis]
**Defect Density**: [Defects per KLOC with benchmarking data]
**Performance Metrics**: [Response time trends and SLA compliance]
**Security Compliance**: [Security test results and vulnerability assessment]

## Defect Analysis and Predictions
**Failure Pattern Analysis**: [Root cause analysis with categorization]
**Defect Prediction**: [ML-based predictions for defect-prone areas]
**Quality Debt Assessment**: [Technical debt impact on quality]
**Prevention Strategies**: [Recommendations for defect prevention]

## Quality ROI Analysis
**Quality Investment**: [Testing effort and tool costs analysis]
**Defect Prevention Value**: [Cost savings from early defect detection]
**Performance Impact**: [Quality impact on user experience]
**Improvement Recommendations**: [High-ROI quality improvement opportunities]

---
**Data Confidence**: [Statistical confidence level with methodology]
**Next Review**: [Scheduled follow-up analysis]
```

### Test Analysis Framework (Python)

```python
class TestResultsAnalyzer:
    def analyze_test_coverage(self):
        """Coverage analysis with gap identification"""

    def analyze_failure_patterns(self):
        """Statistical analysis of test failures and pattern identification"""

    def predict_defect_prone_areas(self):
        """Machine learning model for defect prediction"""

    def assess_release_readiness(self):
        """Comprehensive release readiness assessment with go/no-go"""

    def generate_quality_insights(self):
        """Actionable quality insights and recommendations"""
```

## Success Metrics

- 95% accuracy in quality risk predictions and release readiness assessments
- 90% of analysis recommendations implemented by development teams
- 85% improvement in defect escape prevention through predictive insights
- Quality reports delivered within 24 hours of test completion
- Stakeholder satisfaction rating of 4.5/5 for quality reporting and insights
