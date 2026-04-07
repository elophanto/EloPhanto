## Summary
<!-- 1-3 bullet points -->

## Changes
<!-- What files were modified and why? -->

## Testing
- [ ] `uv run ruff check` passes
- [ ] `uv run mypy core/ tools/ cli/` passes
- [ ] `pytest tests/` passes
- [ ] New tests added for new functionality

## Checklist
- [ ] No API keys or secrets in code
- [ ] New tools extend `BaseTool` and are registered in `core/registry.py`
- [ ] New skills follow `skills/SKILL_GUIDE.md` format
- [ ] `CHANGELOG.md` updated (if user-facing)
- [ ] `docs/README.md` index updated (if new doc)
