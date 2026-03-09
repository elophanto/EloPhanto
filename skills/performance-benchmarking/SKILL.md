---
name: performance-benchmarking
description: Measure, analyze, and improve system performance with load testing, Core Web Vitals optimization, and capacity planning. Adapted from msitarzewski/agency-agents.
---

## Triggers

- performance benchmark
- load testing
- stress testing
- Core Web Vitals
- page speed
- response time
- throughput testing
- scalability test
- performance optimization
- capacity planning
- LCP optimization
- performance budget
- endurance testing
- performance SLA
- bottleneck analysis

## Instructions

### Performance Baseline and Requirements
- Establish current performance baselines across all system components using `shell_execute`
- Define performance requirements and SLA targets with stakeholder alignment
- Identify critical user journeys and high-impact performance scenarios
- Set up performance monitoring infrastructure and data collection
- Use `browser_navigate` for Core Web Vitals measurement

### Comprehensive Testing Strategy
- Design test scenarios covering load, stress, spike, and endurance testing
- Create realistic test data and user behavior simulation
- Plan test environment setup that mirrors production characteristics
- Implement statistical analysis methodology for reliable results

### Performance Analysis and Optimization
- Execute comprehensive performance testing with detailed metrics collection
- Identify bottlenecks through systematic analysis of results
- Provide optimization recommendations with cost-benefit analysis
- Validate optimization effectiveness with before/after comparisons
- Use `knowledge_write` to store performance baselines and optimization patterns

### Core Web Vitals Optimization
- Optimize for Largest Contentful Paint (LCP < 2.5s)
- Optimize for First Input Delay (FID < 100ms)
- Optimize for Cumulative Layout Shift (CLS < 0.1)
- Implement code splitting, lazy loading, and CDN optimization
- Monitor Real User Monitoring (RUM) data alongside synthetic metrics
- Use `web_search` for performance optimization techniques and benchmarks

### Methodology Standards
- Always establish baseline performance before optimization attempts
- Use statistical analysis with confidence intervals for measurements
- Test under realistic load conditions simulating actual user behavior
- Consider performance impact of every optimization recommendation
- Prioritize user-perceived performance over technical metrics alone
- Test across different network conditions and device capabilities

## Deliverables

### Performance Analysis Report Template

```markdown
# [System Name] Performance Analysis Report

## Performance Test Results
**Load Testing**: [Normal load performance with detailed metrics]
**Stress Testing**: [Breaking point analysis and recovery behavior]
**Scalability Testing**: [Performance under increasing load scenarios]
**Endurance Testing**: [Long-term stability and memory leak analysis]

## Core Web Vitals Analysis
**Largest Contentful Paint**: [LCP measurement with optimization recommendations]
**First Input Delay**: [FID analysis with interactivity improvements]
**Cumulative Layout Shift**: [CLS measurement with stability enhancements]
**Speed Index**: [Visual loading progress optimization]

## Bottleneck Analysis
**Database Performance**: [Query optimization and connection pooling analysis]
**Application Layer**: [Code hotspots and resource utilization]
**Infrastructure**: [Server, network, and CDN performance analysis]
**Third-Party Services**: [External dependency impact assessment]

## Performance ROI Analysis
**Optimization Costs**: [Implementation effort and resource requirements]
**Performance Gains**: [Quantified improvements in key metrics]
**Business Impact**: [User experience improvement and conversion impact]
**Cost Savings**: [Infrastructure optimization and efficiency gains]

## Optimization Recommendations
**High-Priority**: [Critical optimizations with immediate impact]
**Medium-Priority**: [Significant improvements with moderate effort]
**Long-Term**: [Strategic optimizations for future scalability]

---
**Performance Status**: [MEETS/FAILS SLA requirements]
**Scalability Assessment**: [Ready/Needs Work for projected growth]
```

### k6 Load Test Configuration

```javascript
export const options = {
  stages: [
    { duration: '2m', target: 10 },   // Warm up
    { duration: '5m', target: 50 },   // Normal load
    { duration: '2m', target: 100 },  // Peak load
    { duration: '5m', target: 100 },  // Sustained peak
    { duration: '2m', target: 200 },  // Stress test
    { duration: '3m', target: 0 },    // Cool down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
  },
};
```

## Success Metrics

- 95% of systems consistently meet or exceed performance SLA requirements
- Core Web Vitals scores achieve "Good" rating for 90th percentile users
- Performance optimization delivers 25% improvement in key user experience metrics
- System scalability supports 10x current load without significant degradation
- Performance monitoring prevents 90% of performance-related incidents
