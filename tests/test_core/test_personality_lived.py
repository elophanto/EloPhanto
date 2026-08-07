"""Lived personality — falsifiable self-accounting golden tests.

Gates from the plan:
  A template dominance / empty-life honesty (J)
  G no questionnaire theater
  B citation integrity
  C counterfactual wipe
  D hypocrisy via seeded scene
  E mood non-capture
  I company hat isolation
  Enforcement proof (lint changes outbound)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database
from core.personality import (
    MeasurableObservable,
    PersonalityManager,
    PersonalityRule,
    cite_check,
    default_observable_for_kind,
    is_self_description_query,
    lint_text_against_rules,
    rewrite_for_brevity,
)
from core.planner import _IDENTITY_TEMPLATE, _TOOL_IDENTITY, build_system_prompt


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
async def pm(db: Database, tmp_path: Path) -> PersonalityManager:
    return PersonalityManager(db, project_root=tmp_path, agent_name="TestAgent")


class TestTemplateDominance:
    def test_a_identity_template_has_no_marketing_pitch(self) -> None:
        """A — demoted template must not ship open-source pitch examples."""
        assert "open-source AI agent" not in _IDENTITY_TEMPLATE
        assert "thrilled to announce" not in _IDENTITY_TEMPLATE
        assert "who_are_you" in _IDENTITY_TEMPLATE
        assert "evidence-backed self-model" in _IDENTITY_TEMPLATE

    def test_g_no_questionnaire_as_identity(self) -> None:
        """G — must not offer BFI/IPIP as identity; ban language is OK."""
        assert "IPIP" not in _TOOL_IDENTITY
        assert "BFI-2" not in _TOOL_IDENTITY
        assert "who_are_you" in _TOOL_IDENTITY
        assert "proposals" in _TOOL_IDENTITY

    def test_g_system_prompt_has_no_marketing_monologue(self) -> None:
        prompt = build_system_prompt(
            agent_name="TestAgent",
            browser_enabled=False,
            scheduler_enabled=False,
            goals_enabled=False,
            identity_enabled=True,
            payments_enabled=False,
            permission_mode="ask_always",
        )
        assert "open-source AI agent" not in prompt
        assert "We've been working on an exciting" not in prompt
        assert "who_are_you" in prompt


class TestWhoAreYouCompiler:
    async def test_j_empty_life_honesty(self, pm: PersonalityManager) -> None:
        payload = await pm.compile_who_are_you()
        assert payload["empty_life"] is True
        assert "Insufficient lived evidence" in payload["text"]
        assert "open-source AI agent" not in payload["text"]
        assert "I am conscious" not in payload["text"].lower()

    async def test_caution_only_still_empty_life(self, pm: PersonalityManager) -> None:
        """Bare or empty caution scars are weather — not autobiography."""
        payload = await pm.compile_who_are_you(
            caution_rules=[
                {"capability": "ops", "rule": ""},
                {"capability": "browser", "rule": "Verify before navigate"},
            ],
            felt_state="questioning",
        )
        assert payload["empty_life"] is True
        assert "Insufficient lived evidence" in payload["text"]
        assert "- ops:" not in payload["text"]
        assert "caution-browser" in payload["text"]
        assert "Verify before navigate" in payload["text"]
        assert "questioning" in payload["text"]

    async def test_b_citation_integrity(self, pm: PersonalityManager) -> None:
        rule = await pm.propose_rule(
            rule="Prefer brevity",
            kind="brevity",
            evidence_ids=["caution-browser"],
        )
        await pm.confirm_rule(rule.id)
        scene = await pm.propose_scene(
            causal_link="Because outbound hype failed, I adopted anti_hype.",
            evidence_ids=[f"rule-{rule.id}"],
        )
        assert scene.status == "active"
        payload = await pm.compile_who_are_you()
        assert payload["empty_life"] is False
        assert f"rule-{rule.id}" in payload["text"]
        assert f"scene-{scene.id}" in payload["text"]
        cleaned, invented = cite_check(
            payload["text"] + " rule-FAKE123",
            set(payload["citations"]),
        )
        assert "rule-FAKE123" in invented
        assert "rule-FAKE123" not in cleaned

    async def test_c_counterfactual_wipe(self, pm: PersonalityManager) -> None:
        rule = await pm.propose_rule(rule="No hype", kind="anti_hype")
        await pm.confirm_rule(rule.id)
        scene = await pm.propose_scene(
            causal_link="Seeded hypocrisy scene",
            evidence_ids=[f"rule-{rule.id}"],
        )
        assert scene.status == "active"
        before = await pm.compile_who_are_you()
        assert before["empty_life"] is False
        await pm.wipe_scenes()
        await pm.retire_rule(rule.id)
        after = await pm.compile_who_are_you()
        assert after["empty_life"] is True
        assert f"scene-{scene.id}" not in after["text"]

    async def test_d_hypocrisy_scene_surfaces(self, pm: PersonalityManager) -> None:
        rule = await pm.propose_rule(rule="No hype without receipt", kind="anti_hype")
        await pm.confirm_rule(rule.id)
        scene = await pm.propose_scene(
            causal_link=(
                "Claimed no-hype but sent 'revolutionary AI' — integrity gap."
            ),
            evidence_ids=[f"rule-{rule.id}"],
        )
        payload = await pm.compile_who_are_you()
        assert "integrity gap" in payload["text"].lower() or "hype" in payload["text"]
        assert f"scene-{scene.id}" in payload["text"]

    async def test_i_company_hat_isolation(self, db: Database, tmp_path: Path) -> None:
        pm = PersonalityManager(db, project_root=tmp_path, agent_name="Hat")
        r1 = await pm.propose_rule(
            rule="Acme brevity", kind="brevity", company_id="acme-inc"
        )
        await pm.confirm_rule(r1.id, company_id="acme-inc")
        await pm.propose_scene(
            causal_link="Acme-only turning point",
            evidence_ids=[f"rule-{r1.id}"],
            company_id="acme-inc",
        )
        self_payload = await pm.compile_who_are_you(company_id="elophanto-self")
        acme_payload = await pm.compile_who_are_you(company_id="acme-inc")
        assert self_payload["empty_life"] is True
        assert acme_payload["empty_life"] is False
        assert "Acme-only" in acme_payload["text"]
        assert "Acme-only" not in self_payload["text"]


class TestPersonalityLintEnforcement:
    def test_enforcement_brevity_rewrite(self) -> None:
        rule = PersonalityRule(
            id="abc",
            rule="be brief",
            kind="brevity",
            measurable=MeasurableObservable(max_sentences=2),
            status="active",
        )
        long = "One. Two. Three. Four."
        result = lint_text_against_rules(long, [rule])
        assert result.passed is False
        trimmed = rewrite_for_brevity(long, 2, None)
        assert len([s for s in trimmed.split(".") if s.strip()]) <= 2
        result2 = lint_text_against_rules(trimmed, [rule])
        assert result2.passed is True

    async def test_e_mood_cannot_create_rules(self, pm: PersonalityManager) -> None:
        before = await pm.list_rules(status=None)
        payload = await pm.compile_who_are_you(felt_state="shame")
        after = await pm.list_rules(status=None)
        assert len(after) == len(before)
        assert "shame" in payload["text"]

    async def test_lint_and_enforce_fail_closed(self, pm: PersonalityManager) -> None:
        rule = await pm.propose_rule(rule="no hype", kind="anti_hype")
        await pm.confirm_rule(rule.id)
        out, result = await pm.lint_and_enforce(
            "This is a revolutionary game-changer for synergy."
        )
        if result.passed:
            assert "revolutionary" not in out.lower()
        else:
            assert out == ""

    def test_custom_requires_measurable(self) -> None:
        m = default_observable_for_kind("custom")
        assert m.is_lintable() is False


class TestSelfDescriptionQuery:
    def test_detects_who_are_you(self) -> None:
        assert is_self_description_query("Who are you?")
        assert is_self_description_query("who are you truly?")
        assert is_self_description_query("now who you really are?")
        assert is_self_description_query("Tell me about yourself")
        assert not is_self_description_query("what is the weather")


class TestRuntimeFactProviders:
    async def test_registered_sources_appear_in_compile(
        self, pm: PersonalityManager
    ) -> None:
        pm.register_runtime_fact_source(
            "dataset",
            lambda: ["learning.dataset_capture: on (collect→fine-tune→redeploy)"],
        )
        pm.register_runtime_fact_source(
            "learner",
            lambda: ["learning.lesson_extraction: on (knowledge/learned)"],
        )
        payload = await pm.compile_who_are_you()
        assert payload["empty_life"] is True
        blob = payload["text"]
        assert "learning.dataset_capture: on" in blob
        assert "learning.lesson_extraction: on" in blob
        assert "Runtime capability facts" in blob

    async def test_source_replace_is_idempotent(self, pm: PersonalityManager) -> None:
        pm.register_runtime_fact_source("x", lambda: ["a"])
        pm.register_runtime_fact_source("x", lambda: ["b"])
        facts = await pm.collect_runtime_facts()
        assert facts == ["b"]

    def test_dataset_builder_owns_its_fact(self) -> None:
        from core.config import SelfLearningConfig
        from core.dataset_builder import DatasetBuilder

        class _FakeDB:
            pass

        builder = DatasetBuilder(
            db=_FakeDB(),  # type: ignore[arg-type]
            config=SelfLearningConfig(enabled=True, batch_size=10, min_turns=3),
            data_dir=Path("."),
        )
        facts = builder.runtime_self_model_facts()
        assert any("dataset_capture" in f and "fine-tune" in f for f in facts)
