"""Judge panels and the refine-until-good loop.

The existing spawn tiers (``delegate``, ``swarm_*``, ``org_*``, ``kid_*``)
all share one shape: dispatch work, collect what comes back, continue. That
is fan-out, and it is the easy half. What none of them do is **converge** —
keep working until the result is actually good, judged by something other
than the model that produced it.

That gap shows up as the most common failure of agent work: the first draft
is returned as the answer. It is coherent, it is plausible, and nobody
checked it against anything. Asking the same model "is this good?" does not
help — it wrote it, and it will say yes.

This module is the missing primitive:

    produce → N independent judges, each with a distinct lens
            → accept, or feed the specific defects back and revise
            → repeat until the bar is met or the budget is spent

Five rules are enforced here rather than left to a prompt, because each one
is a way the loop otherwise degrades into theatre:

1. **Judges are independent.** Each sees the artifact, the reference, and
   its own lens — never another judge's verdict. Show them each other's
   scores and they converge on the first opinion voiced, which is one
   judge wearing five hats.

2. **A rejection must cite a specific defect.** A judge that fails
   something without naming what is wrong has its rejection discarded.
   Without this the loop never terminates: there is always a vaguer
   dimension on which something "could be stronger".

3. **A blocking finding fails regardless of score.** 4.6/5 with a security
   hole is not a pass. Scores average away exactly the defects that matter.

4. **The producer never judges its own work.** Self-assessment is what the
   panel exists to replace.

5. **It always terminates, and says so honestly.** Hitting the round cap
   without convergence returns ``converged=False`` and the outstanding
   findings — never a success claim. A loop that cannot fail is not a
   quality gate, it is a delay.

The engine is transport-agnostic: :func:`converge` takes ``produce`` and
``judge`` callables, so the same logic drives real subagents in production
and plain functions in tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# A finding shorter than this is not a defect report, it is a shrug.
_MIN_FINDING_CHARS = 12

# Vague rejections that name no defect. Matched against the whole finding;
# a judge that can only produce these has nothing actionable to say.
_VAGUE_FINDING_RE = re.compile(
    r"^\s*(?:could be (?:better|improved|stronger)|needs work|not good enough|"
    r"improve (?:this|it)|more detail|unclear|meh|weak|n/?a|none|-+)\s*\.?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Lens:
    """One reviewer's assigned perspective.

    Distinct lenses are the point. Five judges asked "is this good?" produce
    one opinion five times; five judges asked about correctness, coverage,
    fidelity to the reference, failure modes, and what is missing produce
    five different objections.
    """

    name: str
    brief: str
    blocking: bool = True

    def prompt_for(self, artifact: str, reference: str = "", goal: str = "") -> str:
        """The instruction handed to a judge wearing this lens."""
        parts = [
            f"You are reviewing work through one lens only: **{self.name}**.",
            f"What this lens looks for: {self.brief}",
            "",
            "Judge ONLY through your lens. Another reviewer covers the others.",
            "You have not seen any other reviewer's opinion, and must not guess it.",
            "",
        ]
        if goal:
            parts += [f"The work was supposed to achieve:\n{goal}", ""]
        if reference:
            parts += [
                "Compare against this reference — the standard to be matched "
                "or beaten:",
                reference,
                "",
            ]
        parts += [
            "The work under review:",
            artifact,
            "",
            "Reply with ONLY a JSON object:",
            '{"score": <1-5>, "passed": <true|false>, '
            '"findings": ["<specific defect>", ...]}',
            "",
            "Rules you are held to:",
            "- Every finding must name a SPECIFIC defect: what is wrong, where, "
            "and what it should be instead. 'Could be better' is discarded and "
            "your rejection with it.",
            "- If you cannot name a concrete defect, you must pass. Withholding "
            "approval without evidence is not rigour.",
            "- Score 5 only if you would ship this as-is against the reference.",
        ]
        return "\n".join(parts)


@dataclass
class Verdict:
    """One judge's assessment through one lens."""

    lens: str
    score: float = 0.0
    passed: bool = False
    findings: list[str] = field(default_factory=list)
    blocking: bool = True
    error: str = ""

    @property
    def actionable_findings(self) -> list[str]:
        """Findings specific enough to act on. Rule 2 lives here."""
        out: list[str] = []
        for f in self.findings:
            text = (f or "").strip()
            if len(text) < _MIN_FINDING_CHARS:
                continue
            if _VAGUE_FINDING_RE.match(text):
                continue
            out.append(text)
        return out

    @property
    def counts_as_rejection(self) -> bool:
        """A rejection only counts when it cites something actionable.

        This is what stops the loop spinning on taste. A judge that says no
        and cannot say why does not get to block the work.
        """
        if self.error:
            return False
        return not self.passed and bool(self.actionable_findings)


@dataclass
class QualityBar:
    """What "good enough" means for one run."""

    min_score: float = 4.0
    # Every blocking lens must pass, not just the average.
    require_all_blocking: bool = True
    max_rounds: int = 3
    # A judge that errored is not a pass; if too many fail, the panel is
    # not informative and the run should say so rather than accept by default.
    min_valid_verdicts: int = 1

    def __post_init__(self) -> None:
        self.min_score = max(1.0, min(float(self.min_score), 5.0))
        self.max_rounds = max(1, int(self.max_rounds))


@dataclass
class RoundOutcome:
    """What one produce-and-judge cycle established."""

    round_num: int
    artifact: str
    verdicts: list[Verdict]
    accepted: bool
    reason: str
    mean_score: float = 0.0

    @property
    def outstanding(self) -> list[str]:
        """Every actionable defect still on the table, lens-tagged."""
        items: list[str] = []
        for v in self.verdicts:
            for f in v.actionable_findings:
                items.append(f"[{v.lens}] {f}")
        return items


@dataclass
class ConvergenceResult:
    """The whole run. Honest about whether it actually got there."""

    converged: bool
    artifact: str
    rounds: list[RoundOutcome] = field(default_factory=list)
    reason: str = ""

    @property
    def rounds_used(self) -> int:
        return len(self.rounds)

    @property
    def final_verdicts(self) -> list[Verdict]:
        return self.rounds[-1].verdicts if self.rounds else []

    @property
    def outstanding(self) -> list[str]:
        return self.rounds[-1].outstanding if self.rounds else []

    def summary(self) -> dict[str, Any]:
        return {
            "converged": self.converged,
            "rounds_used": self.rounds_used,
            "reason": self.reason,
            "final_scores": {v.lens: v.score for v in self.final_verdicts},
            "outstanding_findings": self.outstanding,
        }


def assess(verdicts: list[Verdict], bar: QualityBar) -> tuple[bool, str, float]:
    """Decide whether a set of verdicts clears the bar.

    Pure and separately testable — this is the rule that decides whether the
    loop stops, so it should be readable without running an agent.
    """
    valid = [v for v in verdicts if not v.error]
    if len(valid) < bar.min_valid_verdicts:
        return (
            False,
            f"only {len(valid)} judge(s) returned a usable verdict; "
            f"need {bar.min_valid_verdicts}",
            0.0,
        )

    mean = sum(v.score for v in valid) / len(valid)

    # Rule 3: a cited blocking defect fails regardless of the average.
    blocking_rejections = [v for v in valid if v.blocking and v.counts_as_rejection]
    if bar.require_all_blocking and blocking_rejections:
        lenses = ", ".join(v.lens for v in blocking_rejections)
        return False, f"blocking lens rejected with specific findings: {lenses}", mean

    if mean < bar.min_score:
        return False, f"mean score {mean:.2f} below bar {bar.min_score:.2f}", mean

    return True, f"all blocking lenses passed; mean {mean:.2f}", mean


def parse_verdict(raw: str, lens: Lens) -> Verdict:
    """Parse a judge's reply. Malformed output is an error, not a pass.

    Defaulting a broken verdict to "passed" would let a panel that has
    silently stopped working wave everything through — the exact failure
    that makes review theatre.
    """
    text = (raw or "").strip()
    if not text:
        return Verdict(lens=lens.name, blocking=lens.blocking, error="empty reply")

    payload: Any = None
    try:
        payload = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                payload = json.loads(match.group(0))
            except ValueError:
                payload = None

    if not isinstance(payload, dict):
        return Verdict(
            lens=lens.name,
            blocking=lens.blocking,
            error=f"unparseable verdict: {text[:160]}",
        )

    raw_findings = payload.get("findings") or []
    if isinstance(raw_findings, str):
        raw_findings = [raw_findings]
    findings = [str(f) for f in raw_findings if str(f).strip()]

    try:
        score = float(payload.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(score, 5.0))

    passed = bool(payload.get("passed", False))

    return Verdict(
        lens=lens.name,
        score=score,
        passed=passed,
        findings=findings,
        blocking=lens.blocking,
    )


async def run_panel(
    artifact: str,
    lenses: list[Lens],
    judge: Callable[[str, Lens], Awaitable[str]],
    *,
    reference: str = "",
    goal: str = "",
    max_concurrency: int = 4,
) -> list[Verdict]:
    """Run every lens over *artifact*, concurrently and independently.

    Judges never see each other's output — that independence is the whole
    reason a panel beats one reviewer. A judge that raises is recorded as an
    errored verdict rather than dropped, so :func:`assess` can tell "nobody
    objected" from "nobody answered".
    """
    if not lenses:
        return []

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _one(lens: Lens) -> Verdict:
        async with semaphore:
            try:
                reply = await judge(
                    lens.prompt_for(artifact, reference=reference, goal=goal), lens
                )
            except Exception as exc:  # pragma: no cover — transport-dependent
                logger.warning("panel: lens %r failed: %s", lens.name, exc)
                return Verdict(
                    lens=lens.name, blocking=lens.blocking, error=str(exc)[:200]
                )
            return parse_verdict(reply, lens)

    return list(await asyncio.gather(*(_one(lens) for lens in lenses)))


async def converge(
    *,
    produce: Callable[[int, list[str]], Awaitable[str]],
    judge: Callable[[str, Lens], Awaitable[str]],
    lenses: list[Lens],
    bar: QualityBar | None = None,
    reference: str = "",
    goal: str = "",
    max_concurrency: int = 4,
) -> ConvergenceResult:
    """Produce, judge, revise — until the bar is met or the rounds run out.

    ``produce(round_num, findings)`` builds the artifact. On round 1
    ``findings`` is empty; afterwards it carries every outstanding
    lens-tagged defect, so the reviser is answering specific objections
    rather than being told to "make it better".

    Returns a :class:`ConvergenceResult` whose ``converged`` flag is the
    honest answer. A caller that ignores it and ships anyway has made that
    choice explicitly, which is the point.
    """
    quality_bar = bar or QualityBar()
    rounds: list[RoundOutcome] = []
    findings: list[str] = []
    artifact = ""

    for round_num in range(1, quality_bar.max_rounds + 1):
        try:
            artifact = await produce(round_num, list(findings))
        except Exception as exc:
            reason = f"production failed in round {round_num}: {exc}"
            logger.error("panel: %s", reason)
            return ConvergenceResult(
                converged=False, artifact=artifact, rounds=rounds, reason=reason
            )

        if not (artifact or "").strip():
            reason = f"round {round_num} produced nothing"
            return ConvergenceResult(
                converged=False, artifact=artifact, rounds=rounds, reason=reason
            )

        verdicts = await run_panel(
            artifact,
            lenses,
            judge,
            reference=reference,
            goal=goal,
            max_concurrency=max_concurrency,
        )
        accepted, reason, mean = assess(verdicts, quality_bar)
        outcome = RoundOutcome(
            round_num=round_num,
            artifact=artifact,
            verdicts=verdicts,
            accepted=accepted,
            reason=reason,
            mean_score=round(mean, 2),
        )
        rounds.append(outcome)
        logger.info(
            "panel round %d/%d: %s (mean %.2f)",
            round_num,
            quality_bar.max_rounds,
            "ACCEPTED" if accepted else "rejected",
            mean,
        )

        if accepted:
            return ConvergenceResult(
                converged=True, artifact=artifact, rounds=rounds, reason=reason
            )

        findings = outcome.outstanding
        if not findings:
            # Rejected, but nobody could say why. Continuing would be the
            # loop chasing its own tail, so stop and report it as what it
            # is: not converged, no actionable defect.
            return ConvergenceResult(
                converged=False,
                artifact=artifact,
                rounds=rounds,
                reason=(
                    f"{reason}; no actionable findings to revise against — "
                    "the panel withheld approval without citing a defect"
                ),
            )

    return ConvergenceResult(
        converged=False,
        artifact=artifact,
        rounds=rounds,
        reason=(
            f"hit the {quality_bar.max_rounds}-round cap without meeting the "
            f"bar; {len(findings)} finding(s) still outstanding"
        ),
    )


# ── Built-in lens packs ─────────────────────────────────────────────────
#
# Named sets for common review jobs. A caller can always supply their own;
# these exist so the usual case does not start with a blank page, and so the
# lenses are genuinely distinct rather than five rewordings of "be good".

LENS_PACKS: dict[str, list[Lens]] = {
    "code": [
        Lens(
            "correctness",
            "Logic errors, wrong edge-case handling, off-by-one, incorrect "
            "assumptions. Name the input that produces the wrong output.",
        ),
        Lens(
            "failure-modes",
            "What happens on malformed input, empty collections, concurrent "
            "access, network failure, or a missing dependency.",
        ),
        Lens(
            "fidelity",
            "Does it actually do what was asked, and match the reference "
            "implementation's behaviour and conventions where one is given.",
        ),
        Lens(
            "simplicity",
            "Unnecessary abstraction, duplicated logic, dead branches, or a "
            "simpler formulation that loses nothing.",
            blocking=False,
        ),
    ],
    "writing": [
        Lens(
            "accuracy",
            "Claims that are wrong, unsupported, or overstated relative to "
            "the evidence given.",
        ),
        Lens(
            "completeness",
            "Questions the reader will obviously ask that go unanswered.",
        ),
        Lens(
            "fidelity",
            "Does it match the reference in voice, structure, and depth.",
        ),
        Lens(
            "concision",
            "Padding, repetition, and sentences that carry no information.",
            blocking=False,
        ),
    ],
    "analysis": [
        Lens(
            "evidence",
            "Conclusions not supported by the data shown; confident claims "
            "resting on thin or missing evidence.",
        ),
        Lens(
            "coverage",
            "Material angles, competitors, or scenarios left unexamined.",
        ),
        Lens(
            "fidelity",
            "Does it answer the question actually asked, at the depth the "
            "reference sets.",
        ),
        Lens(
            "falsifiability",
            "Claims stated so vaguely they could not be wrong.",
            blocking=False,
        ),
    ],
}


def resolve_lenses(
    pack: str = "", custom: list[dict[str, Any]] | None = None
) -> list[Lens]:
    """Build the lens list from a named pack, custom definitions, or both."""
    lenses: list[Lens] = []
    if pack:
        lenses.extend(LENS_PACKS.get(pack, []))
    for entry in custom or []:
        name = str(entry.get("name", "")).strip()
        brief = str(entry.get("brief", "")).strip()
        if not name or not brief:
            continue
        lenses.append(
            Lens(name=name, brief=brief, blocking=bool(entry.get("blocking", True)))
        )
    return lenses
