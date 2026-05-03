# Project Naming

## Description
Before starting any new project, validate that the domain name is available.
If the domain is taken, pick a different name before writing any code.

## Triggers
- new project
- project name
- domain name
- saas
- startup
- launch
- product
- side project
- naming
- domain available
- revenue target
- business idea

## Instructions

### Domain-First Naming Protocol

BEFORE writing any code, creating any files, or setting up any project:

1. **Pick a name** — Choose a short, memorable project name
2. **Check the domain** — Run `whois <name>.com` via shell_execute (or .io, .ai, etc.)
   - Look for "No match" / "NOT FOUND" / "Domain not found" = available
   - If whois is not installed, use `nslookup <name>.com` — NXDOMAIN = likely available
   - As a fallback, navigate to a domain registrar (e.g. namecheap.com) and search
3. **Domain taken? Change the name.** Do NOT proceed with a name whose domain is taken.
   Try variations:
   - Add a prefix/suffix: get*, use*, try*, *app, *hq, *labs
   - Combine words differently
   - Use alternative TLDs (.ai, .io, .dev, .so) only if .com is truly impossible
4. **Repeat until you find an available domain**
5. **Only then** start creating the project with that name

### Rules

- **Never skip the domain check.** A project without an available domain can't launch.
- **Prefer .com** — It's the default expectation. Use alternatives only as last resort.
- Check at least 3 name variations before giving up on .com
- The domain check takes seconds. Renaming a project after building it takes hours.
- Once you find an available name, note it in your scratchpad before proceeding.

### Anti-patterns

- Starting to code before checking the domain
- Assuming a domain is available without checking
- Picking a generic/common word as a name (always taken)
- Checking availability via Google search (unreliable)
- Using a taken domain and planning to "figure it out later"

## Verify

- The deliverable for this phase exists as a concrete artifact (doc, ticket, board, repo) and its location is shared, not described
- Each commitment has an owner name, a due date, and a definition-of-done that someone other than the author could check
- Risks are listed with likelihood/impact and a named mitigation, not as a generic 'risks: TBD' bullet
- Dependencies on other teams/vendors/agents are explicit; an ack from each dependency is recorded or marked 'pending'
- Success criteria for the next phase are numeric or otherwise objectively testable
- A rollback / kill-switch / 'we will stop if X' criterion is written down before work starts
