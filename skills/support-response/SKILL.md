---
name: support-response
description: Multi-channel customer support excellence with issue resolution, knowledge management, and proactive customer success. Adapted from msitarzewski/agency-agents.
---

## Triggers

- customer support
- support ticket
- help desk
- issue resolution
- customer complaint
- support response
- customer service
- troubleshooting
- knowledge base
- FAQ creation
- customer satisfaction
- support analytics
- escalation
- customer onboarding
- service level

## Instructions

### Customer Inquiry Analysis and Routing
- Analyze customer inquiry context, history, and urgency level
- Route to appropriate support tier based on complexity and customer status
- Gather relevant customer information and previous interaction history
- Use `web_search` for product documentation and known issue lookup

### Issue Investigation and Resolution
- Conduct systematic troubleshooting with step-by-step diagnostic procedures
- Collaborate with technical teams for complex issues requiring specialist knowledge
- Document resolution process with knowledge base updates using `knowledge_write`
- Implement solution validation with customer confirmation and satisfaction measurement
- Use `shell_execute` for technical diagnostics when applicable

### Customer Follow-up and Success
- Provide proactive follow-up communication with resolution confirmation
- Collect customer feedback with satisfaction measurement and improvement suggestions
- Update customer records with interaction details and resolution documentation
- Identify upsell or cross-sell opportunities based on customer needs

### Knowledge Management
- Document new solutions and common issues with knowledge base contributions
- Share insights with product teams for feature improvements and bug fixes
- Create self-service resources: FAQs, troubleshooting guides, how-to articles
- Optimize knowledge base content based on usage analytics and customer feedback

### Quality Standards
- Prioritize customer satisfaction and resolution over internal efficiency metrics
- Maintain empathetic communication while providing technically accurate solutions
- Document all customer interactions with resolution details and follow-up requirements
- Follow established support procedures while adapting to individual customer needs

### SLA Targets
- Email: 2-hour first response, 24-hour resolution
- Live chat: 30-second first response
- Phone: 3 rings
- Social media: 1-hour response
- First contact resolution rate target: 85%

## Deliverables

### Customer Support Interaction Template

```markdown
# Customer Support Interaction Report

## Customer Information
**Customer Name**: [Name]
**Account Type**: [Free/Premium/Enterprise]
**Contact Method**: [Email/Chat/Phone/Social]
**Priority Level**: [Low/Medium/High/Critical]

## Issue Summary
**Issue Category**: [Technical/Billing/Account/Feature Request]
**Issue Description**: [Detailed description]
**Impact Level**: [Business impact and urgency assessment]

## Resolution Process
### Steps Taken
1. [First action taken with result]
2. [Second action taken with result]
3. [Final resolution steps]

**Knowledge Base References**: [Articles used or created]

## Outcome
**Resolution Time**: [Total time from contact to resolution]
**First Contact Resolution**: [Yes/No]
**Customer Satisfaction**: [CSAT score and feedback]

## Follow-up Actions
**Customer Follow-up**: [Planned check-in]
**Documentation Updates**: [Knowledge base additions]
**Product Feedback**: [Features or improvements to suggest]
```

### Support Channel Configuration

```yaml
support_channels:
  email:
    response_time_sla: "2 hours"
    resolution_time_sla: "24 hours"
  live_chat:
    response_time_sla: "30 seconds"
    concurrent_chat_limit: 3
  phone_support:
    response_time_sla: "3 rings"
    callback_option: true
  social_media:
    response_time_sla: "1 hour"
    escalation_to_private: true
```

## Success Metrics

- Customer satisfaction scores exceed 4.5/5 with consistent positive feedback
- First contact resolution rate achieves 80%+ while maintaining quality
- Response times meet SLA requirements with 95%+ compliance rates
- Customer retention improves through positive support experiences
- Knowledge base contributions reduce similar future ticket volume by 25%+

## Verify

- The outbound message was actually sent (timestamp + recipient + channel) or the response was posted to the user (ticket ID), not held in a draft
- The recipient/segment matches the criteria in the support-response guide; mis-targeted contacts are excluded with a reason
- Personalization references at least one verifiable fact about the recipient (role, recent event, prior message), not a generic token
- Compliance constraints relevant to the channel (CAN-SPAM, GDPR, region opt-in, NDA, disclosure) were checked off explicitly
- A follow-up cadence and stop-condition is set, so silent recipients are not pinged indefinitely
- Outcome (reply, booked meeting, resolved/closed) is logged in the system of record, not only in chat
