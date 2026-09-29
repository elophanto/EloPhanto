"""``elophanto bench`` — the benchmark built from the agent's own history.

  capture   turn checkpoints that passed every gate into cases
  run       replay the cases: the model runs live, every tool call is
            answered from the recording, nothing real runs
  history   the recorded runs and what produced each score

See docs/95-LEARNING-LOOP.md, Phase E.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from core.config import load_config
from core.database import Database

console = Console()


async def _db(config: Any) -> Database:
    db_path = Path(config.database.db_path)
    if not db_path.is_absolute():
        db_path = config.project_root / db_path
    db = Database(db_path)
    await db.initialize()
    return db


@click.group("bench")
def bench_cmd() -> None:
    """Measure the agent on replays of its own verified work."""


@bench_cmd.command("capture")
@click.option("--config", "config_path", default=None, type=click.Path())
@click.option(
    "--limit", default=50, show_default=True, help="Most recent passed attempts"
)
@click.option("--overwrite", is_flag=True, help="Rewrite cases that already exist")
def capture_cmd(config_path: str | None, limit: int, overwrite: bool) -> None:
    """Write a case for each recent checkpoint attempt that passed every gate."""

    async def _run() -> None:
        from core.bench import capture, cases_dir

        config = load_config(config_path)
        db = await _db(config)
        try:
            directory = cases_dir(config)
            written = await capture(db, directory, limit=limit, overwrite=overwrite)
            total = len(list(directory.glob("*.json"))) if directory.exists() else 0
            console.print(f"{len(written)} new case(s) · {total} in {directory}")
        finally:
            await db.close()

    asyncio.run(_run())


@bench_cmd.command("run")
@click.option("--config", "config_path", default=None, type=click.Path())
@click.option(
    "--limit", default=None, type=int, help="Cases to run (default bench.max_cases)"
)
@click.option("--case", "case_ids", multiple=True, help="Run only these case ids")
@click.option(
    "--metric",
    is_flag=True,
    help="Print only `bench_score: <x>` on the last line (for experiment_run)",
)
def run_cmd(
    config_path: str | None, limit: int | None, case_ids: tuple[str, ...], metric: bool
) -> None:
    """Replay the cases and record the score. Spends model quota; runs no tools."""

    async def _run() -> None:
        from core.agent import Agent
        from core.bench import cases_dir, load_cases, run_bench

        config = load_config(config_path)
        # A measurement opens no windows and starts no campus.
        config.society.enabled = False
        cases = load_cases(cases_dir(config))
        if case_ids:
            cases = [c for c in cases if c.id in set(case_ids)]
        cases = cases[: limit or config.bench.max_cases]
        if not cases:
            console.print("No cases. Run [bold]elophanto bench capture[/bold] first.")
            if metric:
                print("bench_score: 0")
            raise SystemExit(1)
        agent = Agent(config)
        await agent.initialize()
        try:
            run = await run_bench(
                agent,
                cases,
                db=agent._db,
                time_budget=float(config.bench.time_budget_seconds),
            )
        finally:
            await agent.shutdown()
        if not metric:
            table = Table(title=f"Benchmark {run.fingerprint}")
            for col in ("case", "result", "steps", "misses", "cost", "why"):
                table.add_column(col)
            for r in run.results:
                table.add_row(
                    r["id"],
                    "pass" if r["passed"] else "fail",
                    f"{r['steps']}/{r['recorded_steps']}",
                    str(r["misses"]),
                    f"${r['cost_usd']:.3f}",
                    r["reason"][:70],
                )
            console.print(table)
            console.print(
                f"Score: {run.passed}/{len(run.results)} ({run.score:.0%}) · "
                f"mean steps {run.mean_steps:.1f}"
            )
        print(f"bench_score: {run.score:.4f}")

    asyncio.run(_run())


@bench_cmd.command("history")
@click.option("--config", "config_path", default=None, type=click.Path())
@click.option("--limit", default=10, show_default=True)
def history_cmd(config_path: str | None, limit: int) -> None:
    """The recorded runs, newest first."""

    async def _run() -> None:
        from core.bench import history

        config = load_config(config_path)
        db = await _db(config)
        try:
            rows = await history(db, limit)
        finally:
            await db.close()
        if not rows:
            console.print("No benchmark runs yet.")
            return
        table = Table()
        for col in ("when", "score", "passed", "mean steps", "cost", "fingerprint"):
            table.add_column(col)
        for r in rows:
            table.add_row(
                str(r["created_at"])[:16],
                f"{float(r['score']):.0%}",
                f"{r['passed']}/{r['cases']}",
                f"{float(r['mean_steps']):.1f}",
                f"${float(r['cost_usd']):.2f}",
                str(r["fingerprint"]),
            )
        console.print(table)

    asyncio.run(_run())
