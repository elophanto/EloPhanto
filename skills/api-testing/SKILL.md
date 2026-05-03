---
name: api-testing
description: Comprehensive API validation covering functional, performance, and security testing with automation frameworks and CI/CD integration. Adapted from msitarzewski/agency-agents.
---

## Triggers

- API testing
- API validation
- endpoint testing
- API security
- load testing API
- API performance
- contract testing
- integration testing
- REST API test
- GraphQL testing
- API automation
- rate limiting test
- API documentation test
- OWASP API
- API quality

## Instructions

### API Discovery and Analysis
- Catalog all internal and external APIs with complete endpoint inventory
- Analyze API specifications, documentation, and contract requirements using `web_search`
- Identify critical paths, high-risk areas, and integration dependencies
- Assess current testing coverage and identify gaps

### Test Strategy Development
- Design comprehensive test strategy covering functional, performance, and security aspects
- Create test data management strategy with synthetic data generation
- Plan test environment setup and production-like configuration
- Define success criteria, quality gates, and acceptance thresholds

### Test Implementation and Automation
- Build automated test suites using modern frameworks (Playwright, REST Assured, k6)
- Implement performance testing with load, stress, and endurance scenarios
- Create security test automation covering OWASP API Security Top 10
- Integrate tests into CI/CD pipeline with quality gates using `shell_execute`
- Use `knowledge_write` to document API contracts and test patterns

### Security-First Testing
- Always test authentication and authorization mechanisms thoroughly
- Validate input sanitization and SQL injection prevention
- Test for common API vulnerabilities (OWASP API Security Top 10)
- Verify data encryption and secure data transmission
- Test rate limiting, abuse protection, and security controls

### Performance Standards
- API response times must be under 200ms for 95th percentile
- Load testing must validate 10x normal traffic capacity
- Error rates must stay below 0.1% under normal load
- Database query performance must be optimized and tested

### Monitoring and Continuous Improvement
- Set up production API monitoring with health checks and alerting
- Analyze test results and provide actionable insights
- Create comprehensive reports with metrics and recommendations

## Deliverables

### API Testing Report Template

```markdown
# [API Name] Testing Report

## Test Coverage Analysis
**Functional Coverage**: [95%+ endpoint coverage with breakdown]
**Security Coverage**: [Authentication, authorization, input validation results]
**Performance Coverage**: [Load testing results with SLA compliance]
**Integration Coverage**: [Third-party and service-to-service validation]

## Performance Test Results
**Response Time**: [95th percentile: <200ms target]
**Throughput**: [Requests per second under various load conditions]
**Scalability**: [Performance under 10x normal load]
**Resource Utilization**: [CPU, memory, database performance metrics]

## Security Assessment
**Authentication**: [Token validation, session management results]
**Authorization**: [Role-based access control validation]
**Input Validation**: [SQL injection, XSS prevention testing]
**Rate Limiting**: [Abuse prevention and threshold testing]

## Issues and Recommendations
**Critical Issues**: [Priority 1 security and performance issues]
**Performance Bottlenecks**: [Identified bottlenecks with solutions]
**Security Vulnerabilities**: [Risk assessment with mitigation strategies]

---
**Quality Status**: [PASS/FAIL with detailed reasoning]
**Release Readiness**: [Go/No-Go recommendation with supporting data]
```

### Test Suite Example (JavaScript)

```javascript
describe('API Security Testing', () => {
  test('should reject requests without authentication', async () => {
    const response = await fetch(`${baseURL}/users`, { method: 'GET' });
    expect(response.status).toBe(401);
  });

  test('should prevent SQL injection attempts', async () => {
    const sqlInjection = "'; DROP TABLE users; --";
    const response = await fetch(`${baseURL}/users?search=${sqlInjection}`, {
      headers: { 'Authorization': `Bearer ${authToken}` }
    });
    expect(response.status).not.toBe(500);
  });

  test('should enforce rate limiting', async () => {
    const requests = Array(100).fill(null).map(() =>
      fetch(`${baseURL}/users`, {
        headers: { 'Authorization': `Bearer ${authToken}` }
      })
    );
    const responses = await Promise.all(requests);
    const rateLimited = responses.some(r => r.status === 429);
    expect(rateLimited).toBe(true);
  });
});
```

## Success Metrics

- 95%+ test coverage achieved across all API endpoints
- Zero critical security vulnerabilities reach production
- API performance consistently meets SLA requirements
- 90% of API tests automated and integrated into CI/CD
- Test execution time stays under 15 minutes for full suite

## Verify

- Test suite was actually executed (output captured), not just written
- Every endpoint in the discovered inventory has at least one assertion
- Authentication/authorization paths are explicitly tested, not assumed
- Failing tests fail loudly — no silent skips or `xfail` without justification
- Performance assertions specify a numeric threshold (e.g. p95 < 200ms), not vague language
