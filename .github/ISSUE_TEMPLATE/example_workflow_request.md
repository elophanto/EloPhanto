# Example workflow request: audit a messy signup flow

This is an example of the kind of request EloPhanto is built to handle.

## Workflow I want delegated

Audit a public signup/onboarding flow and return a proof-of-work report showing:

- where users get blocked or confused
- what fields, redirects, modals, or errors appear
- which steps need browser automation vs API checks
- what should be fixed first

## Context

A technical founder or operator has a web product with a working signup flow, but signups are not converting and the team does not know whether the problem is copy, UX, bugs, pricing, auth, or friction.

## Success criteria

A useful EloPhanto run would produce:

- a step-by-step browser trace
- screenshots or page-state evidence for each blocker
- a ranked list of fixes
- a small implementation plan or PR if the repo is available
- a clear recommendation: fix, simplify, instrument, or ignore

## Out of bounds

- no payment-card testing unless explicitly authorized
- no destructive account actions
- no scraping private user data
- no bypassing auth or rate limits

## Why this example exists

If you want EloPhanto to inspect one of your workflows, open a workflow request using the template in this repo or use the `/hire` page.
