"""Verify all knowledge files exist and have valid frontmatter."""

from __future__ import annotations

from pathlib import Path

import yaml

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge" / "system"

EXPECTED_FILES = [
    "identity.md",
    "architecture.md",
    "capabilities.md",
    "conventions.md",
    "changelog.md",
    "known-limitations.md",
]


class TestKnowledgeFiles:
    def test_all_files_exist(self) -> None:
        """All expected knowledge files exist."""
        for filename in EXPECTED_FILES:
            path = KNOWLEDGE_DIR / filename
            assert path.exists(), f"Missing knowledge file: {filename}"

    def test_all_files_have_frontmatter(self) -> None:
        """All knowledge files have valid YAML frontmatter."""
        for filename in EXPECTED_FILES:
            path = KNOWLEDGE_DIR / filename
            content = path.read_text()
            assert content.startswith("---"), f"{filename} missing frontmatter"

            parts = content.split("---", 2)
            assert len(parts) >= 3, f"{filename} has malformed frontmatter"

            meta = yaml.safe_load(parts[1])
            assert isinstance(meta, dict), f"{filename} frontmatter is not a dict"
            assert "title" in meta, f"{filename} missing 'title' in frontmatter"
            assert "scope" in meta, f"{filename} missing 'scope' in frontmatter"

    def test_all_files_have_content(self) -> None:
        """All knowledge files have non-empty body content."""
        for filename in EXPECTED_FILES:
            path = KNOWLEDGE_DIR / filename
            content = path.read_text()
            parts = content.split("---", 2)
            body = parts[2].strip() if len(parts) >= 3 else ""
            assert len(body) > 20, f"{filename} has too little content"
