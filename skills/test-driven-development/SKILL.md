---
name: test-driven-development
description: Enforces the Red-Green-Refactor TDD cycle. Write a failing test first, implement minimal code to pass, then refactor. Prevents writing code before tests exist.
---

## Triggers

- tdd
- test driven development
- test first
- write tests
- red green refactor
- test driven
- write test first
- failing test
- test before code
- strict testing

## Instructions

### The Red-Green-Refactor Cycle

You MUST follow this exact cycle for every piece of functionality:

#### Step 1: RED — Write a failing test

Before writing ANY implementation code, write a test that:
- Tests the specific behavior you're about to implement
- Is clear about what it expects (exact values, not vague assertions)
- FAILS when you run it (because the code doesn't exist yet)

```bash
# Run the test and VERIFY it fails
shell_execute: pytest tests/test_feature.py -v
# Expected: FAILED (red)
```

If the test passes without implementation, your test is wrong. Delete it
and write a better one that actually tests the new behavior.

#### Step 2: GREEN — Write minimal code to pass

Write the MINIMUM code needed to make the test pass. Not more.

Rules:
- Only write code that makes the failing test pass
- Don't add features the test doesn't cover
- Don't optimize yet
- Don't handle edge cases the test doesn't test
- Hard-code values if that's all the test requires

```bash
# Run the test and VERIFY it passes
shell_execute: pytest tests/test_feature.py -v
# Expected: PASSED (green)
```

#### Step 3: REFACTOR — Clean up while green

Now that the test passes, improve the code:
- Remove duplication
- Improve naming
- Extract functions/classes
- Optimize if needed

After EVERY change, run the test again:
```bash
shell_execute: pytest tests/test_feature.py -v
# Expected: still PASSED (green)
```

If the test breaks during refactoring, undo and try a smaller change.

### Critical Rules

1. **NEVER write implementation before the test.** If you catch yourself
   writing a function before its test exists, STOP. Delete the function.
   Write the test first.

2. **NEVER skip the RED step.** You must observe the test failing before
   writing implementation. This verifies the test actually tests something.

3. **One test at a time.** Don't write 10 tests then implement. Write ONE
   test, make it pass, then write the next test.

4. **Tests must be specific.** `assert result is not None` is not a test.
   `assert result == {"status": "ok", "count": 3}` is a test.

5. **Run tests after EVERY change.** Not after 5 changes. After every
   single change. The test suite is your safety net — use it constantly.

6. **If you break existing tests, fix them FIRST.** Don't continue adding
   features with broken tests in the background.

### Test File Organization

```
project/
  src/
    feature.py          # Implementation
  tests/
    test_feature.py     # Tests for feature.py
    conftest.py         # Shared fixtures
```

- Test file mirrors source file: `src/auth.py` -> `tests/test_auth.py`
- One test function per behavior, not per method
- Use descriptive names: `test_login_with_invalid_password_returns_401`

### Common Testing Patterns

**Arrange-Act-Assert:**
```python
def test_user_creation():
    # Arrange
    data = {"name": "Alice", "email": "alice@example.com"}

    # Act
    user = create_user(data)

    # Assert
    assert user.name == "Alice"
    assert user.email == "alice@example.com"
    assert user.id is not None
```

**Testing exceptions:**
```python
def test_invalid_email_raises():
    with pytest.raises(ValueError, match="invalid email"):
        create_user({"name": "Alice", "email": "not-an-email"})
```

**Testing side effects:**
```python
def test_send_welcome_email(mocker):
    mock_send = mocker.patch("app.email.send")
    create_user({"name": "Alice", "email": "alice@example.com"})
    mock_send.assert_called_once_with("alice@example.com", subject="Welcome!")
```

### Framework Commands

| Language | Run Tests | Watch Mode |
|----------|----------|------------|
| Python | `pytest -v` | `pytest-watch` |
| JavaScript | `npm test` | `npm test -- --watch` |
| TypeScript | `npx jest --verbose` | `npx jest --watch` |
| Rust | `cargo test` | `cargo watch -x test` |
| Go | `go test ./...` | `gotestsum --watch` |

### Tools to Use

- `shell_execute` — Run test commands
- `file_write` / `file_patch` — Write test files and implementation
- `file_read` — Read existing code to understand what to test
- `self_read_source` — Explore project structure

### When NOT to Use TDD

- Throwaway scripts or one-off explorations
- Configuration files
- Static content (HTML, CSS, markdown)
- When the user explicitly says "skip tests" or "no tests needed"

For everything else: Red. Green. Refactor. Every time.

## Verify

- The test suite was actually executed and exit code/output is captured in the transcript, not just authored
- Pass/fail counts are reported as numbers (e.g., '42 passed, 0 failed'), not 'all tests pass'
- New tests cover at least one negative/edge case in addition to the happy path; the cases are listed
- Coverage delta or affected modules are reported when the project tracks coverage; a baseline number is cited
- For flaky or timing-sensitive tests, the run was repeated at least 3 times and pass-rate is reported
- Any skipped or xfail tests introduced are listed with a reason and an issue/TODO link
