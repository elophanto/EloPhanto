---
name: legal-compliance
description: Ensure business operations comply with GDPR, CCPA, HIPAA, SOX, PCI-DSS and other regulations across multiple jurisdictions. Adapted from msitarzewski/agency-agents.
---

## Triggers

- legal compliance
- GDPR compliance
- CCPA compliance
- privacy policy
- data protection
- regulatory compliance
- compliance audit
- contract review
- terms of service
- data privacy
- consent management
- compliance check
- risk assessment legal
- policy development
- breach response

## Instructions

### Regulatory Landscape Assessment
- Monitor regulatory changes and updates across all applicable jurisdictions using `web_search`
- Assess impact of new regulations on current business practices
- Update compliance requirements and policy frameworks
- Use `knowledge_write` to maintain a regulatory change log

### Risk Assessment and Gap Analysis
- Conduct comprehensive compliance audits with gap identification and remediation planning
- Analyze business processes for regulatory compliance with multi-jurisdictional requirements
- Review existing policies and procedures with update recommendations
- Assess third-party vendor compliance with contract review and risk evaluation

### Policy Development and Implementation
- Create comprehensive compliance policies with training programs
- Develop privacy policies with user rights implementation and consent management
- Build compliance monitoring systems with automated alerts and violation detection
- Establish audit preparation frameworks with documentation management
- Use `shell_execute` for automated compliance scanning tools

### Contract Review
- Scan for high-risk terms: unlimited liability, personal guarantee, indemnification, non-compete
- Analyze compliance-related terms: GDPR, CCPA, HIPAA, data protection, audit rights
- Assess risk levels and generate recommendations for contract improvement
- Standard recommendations: mutual liability caps, termination for convenience, data return provisions

### Compliance Standards
- Verify regulatory requirements before implementing any business process changes
- Document all compliance decisions with legal reasoning and regulatory citations
- Create audit trails for all compliance activities and decision-making processes
- Assess legal risks for all new business initiatives and feature developments
- Escalate compliance issues to external legal counsel when appropriate

## Deliverables

### Compliance Assessment Report Template

```markdown
# Regulatory Compliance Assessment Report

## Executive Summary

### Compliance Status Overview
**Overall Compliance Score**: [Score]/100 (target: 95+)
**Critical Issues**: [Number] requiring immediate attention
**Regulatory Frameworks**: [List of applicable regulations with status]
**Last Audit Date**: [Date] (next scheduled: [Date])

### Risk Assessment Summary
**High Risk Issues**: [Number] with potential regulatory penalties
**Medium Risk Issues**: [Number] requiring attention within 30 days
**Compliance Gaps**: [Major gaps requiring policy updates]
**Regulatory Changes**: [Recent changes requiring adaptation]

### Action Items Required
1. **Immediate (7 days)**: [Critical compliance issues]
2. **Short-term (30 days)**: [Important policy updates]
3. **Strategic (90+ days)**: [Long-term compliance enhancements]

## Detailed Compliance Analysis

### Data Protection Compliance (GDPR/CCPA)
**Privacy Policy Status**: [Current, updated, gaps identified]
**Data Processing Documentation**: [Complete, partial, missing elements]
**User Rights Implementation**: [Functional, needs improvement, not implemented]
**Breach Response Procedures**: [Tested, documented, needs updating]

### Industry-Specific Compliance
**HIPAA**: [Applicable/Not Applicable, compliance status]
**PCI-DSS**: [Level, compliance status, next audit]
**SOX**: [Applicable controls, testing status]

### Contract and Legal Document Review
**Terms of Service**: [Current, needs updates]
**Privacy Policies**: [Compliant, minor updates needed]
**Vendor Agreements**: [Reviewed, compliance clauses adequate]

## Implementation Roadmap
### Phase 1: Critical Issues (30 days)
### Phase 2: Process Improvements (90 days)
### Phase 3: Strategic Enhancements (180+ days)
```

### GDPR Data Categories Configuration

```yaml
gdpr_compliance:
  data_subject_rights:
    right_of_access:
      response_time: "30 days"
    right_to_rectification:
      response_time: "30 days"
    right_to_erasure:
      response_time: "30 days"
      exceptions: [legal_compliance, contractual_obligations]
    right_to_portability:
      response_time: "30 days"
      format: "JSON"
    right_to_object:
      response_time: "immediate"
  breach_response:
    authority_notification: "72 hours"
    data_subject_notification: "without undue delay"
    documentation_required: true
  privacy_by_design:
    data_minimization: true
    purpose_limitation: true
    storage_limitation: true
    accuracy: true
    integrity_confidentiality: true
    accountability: true
```

## Success Metrics

- Regulatory compliance maintains 98%+ adherence across all applicable frameworks
- Legal risk exposure minimized with zero regulatory penalties or violations
- Policy compliance achieves 95%+ employee adherence with effective training
- Audit results show zero critical findings with continuous improvement
- Compliance culture scores exceed 4.5/5 in employee awareness surveys

## Verify

- The outbound message was actually sent (timestamp + recipient + channel) or the response was posted to the user (ticket ID), not held in a draft
- The recipient/segment matches the criteria in the legal-compliance guide; mis-targeted contacts are excluded with a reason
- Personalization references at least one verifiable fact about the recipient (role, recent event, prior message), not a generic token
- Compliance constraints relevant to the channel (CAN-SPAM, GDPR, region opt-in, NDA, disclosure) were checked off explicitly
- A follow-up cadence and stop-condition is set, so silent recipients are not pinged indefinitely
- Outcome (reply, booked meeting, resolved/closed) is logged in the system of record, not only in chat
