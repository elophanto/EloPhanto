---
name: infrastructure-maintenance
description: System reliability, performance optimization, cloud architecture, and infrastructure automation maintaining 99.9%+ uptime. Adapted from msitarzewski/agency-agents.
---

## Triggers

- infrastructure maintenance
- system reliability
- server monitoring
- uptime optimization
- cloud architecture
- infrastructure as code
- backup recovery
- disaster recovery
- performance monitoring
- auto scaling
- security hardening
- capacity planning
- cost optimization infrastructure
- DevOps
- system health

## Instructions

### Infrastructure Assessment and Planning
- Assess current infrastructure health and performance using `shell_execute`
- Identify optimization opportunities and potential risks
- Plan infrastructure changes with rollback procedures
- Implement comprehensive monitoring before making any infrastructure changes

### Implementation with Monitoring
- Deploy infrastructure changes using Infrastructure as Code with version control
- Implement comprehensive monitoring with alerting for all critical metrics (CPU, memory, disk, network)
- Create automated testing procedures with health checks and performance validation
- Establish backup and recovery procedures with tested restoration processes
- Use `shell_execute` for deployment automation and monitoring checks

### Performance Optimization and Cost Management
- Analyze resource utilization with right-sizing recommendations
- Implement auto-scaling policies with cost optimization and performance targets
- Create capacity planning reports with growth projections and resource requirements
- Build cost management dashboards with spending analysis and optimization opportunities

### Security and Compliance Validation
- Conduct security audits with vulnerability assessments and remediation plans
- Implement compliance monitoring with audit trails (SOC2, ISO27001)
- Create incident response procedures with security event handling and notification
- Establish access control reviews with least privilege validation
- Use `web_search` to stay current on security advisories and patches

### Reliability Standards
- Create tested backup and recovery procedures for all critical systems
- Document all infrastructure changes with rollback procedures and validation steps
- Establish incident response procedures with clear escalation paths
- Validate security requirements for all infrastructure modifications

## Deliverables

### Infrastructure Health Report Template

```markdown
# Infrastructure Health and Performance Report

## Executive Summary

### System Reliability Metrics
**Uptime**: [%] (target: 99.9%)
**Mean Time to Recovery**: [hours] (target: <4 hours)
**Incident Count**: [critical], [minor]
**Performance**: [%] of requests under 200ms response time

### Cost Optimization Results
**Monthly Infrastructure Cost**: $[Amount] ([+/-]% vs. budget)
**Cost per User**: $[Amount]
**Optimization Savings**: $[Amount] achieved through right-sizing

### Action Items Required
1. **Critical**: [Infrastructure issue requiring immediate attention]
2. **Optimization**: [Cost or performance improvement opportunity]
3. **Strategic**: [Long-term infrastructure planning recommendation]

## Detailed Infrastructure Analysis
### System Performance
**CPU Utilization**: [Average and peak]
**Memory Usage**: [Current utilization with growth trends]
**Storage**: [Capacity utilization and growth projections]
**Network**: [Bandwidth usage and latency measurements]

### Security Posture
**Vulnerability Assessment**: [Security scan results]
**Patch Management**: [System update status]
**Compliance**: [Regulatory compliance status]

## Cost Analysis and Optimization
**Right-sizing**: [Instance optimization with projected savings]
**Reserved Capacity**: [Long-term commitment savings potential]
**Automation**: [Operational cost reduction through automation]
```

### Prometheus Alert Rules Template

```yaml
groups:
  - name: infrastructure.rules
    rules:
      - alert: HighCPUUsage
        expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
        for: 5m
        labels:
          severity: warning
      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
        for: 5m
        labels:
          severity: critical
      - alert: DiskSpaceLow
        expr: 100 - ((node_filesystem_avail_bytes * 100) / node_filesystem_size_bytes) > 85
        for: 2m
        labels:
          severity: warning
      - alert: ServiceDown
        expr: up == 0
        for: 1m
        labels:
          severity: critical
```

## Success Metrics

- System uptime exceeds 99.9% with mean time to recovery under 4 hours
- Infrastructure costs are optimized with 20%+ annual efficiency improvements
- Security compliance maintains 100% adherence to required standards
- Performance metrics meet SLA requirements with 95%+ target achievement
- Automation reduces manual operational tasks by 70%+ with improved consistency

## Verify

- Root cause is stated in one sentence and is supported by a concrete artifact (stack trace, log line, diff, profiler output)
- The reproducer is minimal and runs locally; the exact command and observed output are captured
- The fix was verified by re-running the reproducer and showing the previously-failing output now passes
- A regression test (or monitoring/alert) was added so the same bug is caught automatically next time
- Adjacent code paths that share the same failure mode were checked, not just the reported symptom
- If the fix touches security, performance, or data integrity, the trade-off is named and quantified
