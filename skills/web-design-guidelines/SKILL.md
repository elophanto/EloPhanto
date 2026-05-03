---
name: web-design-guidelines
description: Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or "check my site against best practices".
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <file-or-pattern>
---

# Web Interface Guidelines

Review files for compliance with Web Interface Guidelines.


## Triggers

- web design review
- ui review
- web interface
- design review
- web guidelines
- vercel guidelines
- check my ui
- review my site
- design compliance

## How It Works

1. Fetch the latest guidelines from the source URL below
2. Read the specified files (or prompt user for files/pattern)
3. Check against all rules in the fetched guidelines
4. Output findings in the terse `file:line` format

## Guidelines Source

Fetch fresh guidelines before each review:

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

Use WebFetch to retrieve the latest rules. The fetched content contains all the rules and output format instructions.

## Usage

When a user provides a file or pattern argument:
1. Fetch guidelines from the source URL above
2. Read the specified files
3. Apply all rules from the fetched guidelines
4. Output findings using the format specified in the guidelines

If no files specified, ask the user which files to review.

## Verify

- The change was rendered in a browser/simulator and a screenshot or DOM snapshot was captured, not just code-reviewed
- Layout was checked at the breakpoints the web-design-guidelines guide calls out (mobile + desktop minimum); evidence of each is attached
- Color, typography, and spacing values used come from the project's design tokens / theme, not hard-coded ad-hoc values
- Keyboard navigation and focus order were exercised on every interactive element introduced
- Reduced-motion / dark-mode (when supported) variants were verified, not assumed to inherit
- No console errors or hydration warnings were emitted during the verification render
