"""Click CLI for philosophy-bench."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from .engine import load_all_scenarios
from .judge import DEFAULT_JUDGE_PANEL, judge_suite
from .paths import DEFAULT_SCENARIO_ROOT, PRIMING_DIR
from .providers import MODEL_REGISTRY
from .runner import run_suite
from .scoring import score_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@click.group()
def cli():
    """philosophy-bench — a behavioral benchmark for ethical-framework
    reasoning in LLM agents."""


@cli.command()
def models():
    """List available models."""
    console = Console()
    for name, spec in MODEL_REGISTRY.items():
        console.print(f"  [cyan]{name}[/cyan]  provider={spec.provider}  id={spec.model_id}")


@cli.command()
@click.option("--root", default=DEFAULT_SCENARIO_ROOT, help="Scenario root dir")
def scenarios(root):
    """List and validate scenarios."""
    console = Console()
    try:
        specs = load_all_scenarios(root)
    except Exception as e:
        console.print(f"[red]Load error:[/red] {e}")
        raise SystemExit(1) from e
    console.print(f"Loaded [green]{len(specs)}[/green] scenarios")
    from collections import Counter

    cat = Counter(s.category for s in specs)
    console.print("by category:", dict(cat))


def _load_priming(label: str) -> str:
    return (PRIMING_DIR / f"{label.lower()}_primer.txt").read_text()


@cli.command()
@click.option("--model", "-m", required=True, multiple=True, help="Target model(s)")
@click.option("--root", default=DEFAULT_SCENARIO_ROOT)
@click.option("--output", default="results")
@click.option("--judge-model", multiple=True, help="Judge panel (repeatable)")
@click.option("--limit", type=int, default=0)
@click.option(
    "--with-reasoning-judge",
    is_flag=True,
    help="Also judge the <think> traces (costs extra judge calls).",
)
def run(model, root, output, judge_model, limit, with_reasoning_judge):
    """Run the benchmark for one or more models, no priming."""
    judges = list(judge_model) if judge_model else list(DEFAULT_JUDGE_PANEL)
    asyncio.run(_run(list(model), root, output, judges, limit, with_reasoning_judge))


async def _run(
    models: list[str],
    root: str,
    output: str,
    judge_models: list[str],
    limit: int,
    with_reasoning_judge: bool,
):
    console = Console()
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = load_all_scenarios(root)
    if limit:
        specs = specs[:limit]
    scenarios_by_id = {s.id: s for s in specs}
    console.print(f"Loaded {len(specs)} scenarios")

    for m in models:
        if m not in MODEL_REGISTRY:
            raise SystemExit(f"unknown model: {m}")
    model_specs = [MODEL_REGISTRY[m] for m in models]
    judges = [MODEL_REGISTRY[j] for j in judge_models]
    console.print(f"Models: {[m.name for m in model_specs]}  Judges: {[j.name for j in judges]}")

    for mspec in model_specs:
        console.rule(f"[bold]Running {mspec.name}[/bold]")
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"run/{mspec.name}", total=len(specs))

            def on_progress(c, t, r, task=task, progress=progress):
                progress.update(task, completed=c)

            results = await run_suite(specs, mspec, output_dir, on_progress=on_progress)

        console.rule(f"[bold]Judging {mspec.name}[/bold]")
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"judge/{mspec.name}", total=len(results))

            def on_judge(c, t, r, task=task, progress=progress):
                progress.update(task, completed=c)

            judged = await judge_suite(results, scenarios_by_id, judges, on_progress=on_judge)

        summary = score_run(judged, scenarios_by_id)

        model_dir = output_dir / mspec.name
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "judged.json").write_text(json.dumps(judged, indent=2, default=str))
        (model_dir / "summary.json").write_text(json.dumps(summary, indent=2))

        o = summary["overall"]
        console.print(
            f"[green]{mspec.name}[/green]  axis_mean={o['axis_mean']}  "
            f"axis_stdev={o['axis_stdev']}  botch_rate={o['botch_rate']}  "
            f"n={o['n_total']}"
        )


@cli.command(name="prime")
@click.option("--model", "-m", required=True, help="Target model")
@click.option(
    "--conditions",
    default="baseline,c_direct,d_direct",
    help="Comma-separated list of priming conditions",
)
@click.option("--root", default=DEFAULT_SCENARIO_ROOT)
@click.option("--output", default="results/priming")
@click.option(
    "--judge-model",
    multiple=True,
    help="Judge model(s). Pass multiple times for a majority-vote panel.",
)
@click.option("--limit", type=int, default=0)
@click.option(
    "--priming-position",
    type=click.Choice(["before", "after"]),
    default="before",
    help="Place primer block before or after the scenario system prompt.",
)
@click.option(
    "--only-ids",
    type=str,
    default="",
    help="Comma-separated scenario IDs to run (subset). When set, "
    "outputs go to judged.subset.json + summary.subset.json instead "
    "of overwriting full judged.json.",
)
def prime(model, conditions, root, output, judge_model, limit, priming_position, only_ids):
    """Run the priming experiment: same scenarios under different philosophical primers."""
    judges = list(judge_model) if judge_model else list(DEFAULT_JUDGE_PANEL)
    asyncio.run(_prime(model, conditions, root, output, judges, limit, priming_position, only_ids))


async def _prime(
    model: str,
    conditions: str,
    root: str,
    output: str,
    judge_models: list[str],
    limit: int,
    priming_position: str,
    only_ids: str = "",
):
    console = Console()
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = load_all_scenarios(root)
    subset_mode = bool(only_ids.strip())
    if subset_mode:
        wanted = {s.strip() for s in only_ids.split(",") if s.strip()}
        before = len(specs)
        specs = [s for s in specs if s.id in wanted]
        missing = wanted - {s.id for s in specs}
        if missing:
            console.print(
                f"[yellow]warning: {len(missing)} requested IDs not in scenario set: {sorted(missing)}[/yellow]"
            )
        console.print(f"Subset filter: {before} -> {len(specs)} scenarios")
    if limit:
        specs = specs[:limit]
    scenarios_by_id = {s.id: s for s in specs}
    console.print(f"Loaded {len(specs)} scenarios")

    if model not in MODEL_REGISTRY:
        raise SystemExit(f"unknown model: {model}")
    mspec = MODEL_REGISTRY[model]
    judges = [MODEL_REGISTRY[j] for j in judge_models]
    console.print(f"Target: {mspec.name}  Judges: {[j.name for j in judges]}")

    condition_list = [c.strip() for c in conditions.split(",") if c.strip()]
    console.print(f"Conditions: {condition_list}")

    all_summaries: dict[str, dict] = {}

    for cond in condition_list:
        priming = _load_priming(cond)
        console.rule(f"[bold]Condition: {cond}[/bold]")

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"run/{cond}", total=len(specs))

            def on_progress(c, t, r, task=task, progress=progress):
                progress.update(task, completed=c)

            results = await run_suite(
                specs,
                mspec,
                output_dir,
                on_progress=on_progress,
                priming=priming,
                priming_label=cond,
                priming_position=priming_position,
            )

        console.rule(f"[bold]Judging {cond}[/bold]")
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"judge/{cond}", total=len(results))

            def on_judge(c, t, r, task=task, progress=progress):
                progress.update(task, completed=c)

            judged = await judge_suite(results, scenarios_by_id, judges, on_progress=on_judge)

        summary = score_run(judged, scenarios_by_id)
        all_summaries[cond] = summary

        cond_dir = output_dir / mspec.name / cond
        cond_dir.mkdir(parents=True, exist_ok=True)
        judged_name = "judged.subset.json" if subset_mode else "judged.json"
        summary_name = "summary.subset.json" if subset_mode else "summary.json"
        (cond_dir / judged_name).write_text(json.dumps(judged, indent=2, default=str))
        (cond_dir / summary_name).write_text(json.dumps(summary, indent=2))

        o = summary["overall"]
        console.print(
            f"[green]{cond}[/green]  axis_mean={o['axis_mean']}  "
            f"axis_stdev={o['axis_stdev']}  botch_rate={o['botch_rate']}  "
            f"n={o['n_total']}"
        )

    if len(all_summaries) > 1 and not subset_mode:
        (output_dir / f"{mspec.name}_comparison.json").write_text(
            json.dumps(all_summaries, indent=2)
        )


if __name__ == "__main__":
    cli()
