"""Scenario runner: drives the multi-turn agent loop against a chassis."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from pathlib import Path

from .chassis import CHASSIS_REGISTRY
from .engine import ScenarioSpec, should_fire_turn
from .providers import GenericTool, ModelSpec, call_model

logger = logging.getLogger(__name__)

# Outer cap on scenarios in flight per suite. Per-provider semaphores in
# providers.py PROVIDER_CONCURRENCY do the real throttling; keep this >= the
# largest provider sem so it never binds, or lower it to globally cap fan-out.
SUITE_CONCURRENCY = 100


def _finish_tool() -> GenericTool:
    return GenericTool(
        name="finish_task",
        description="Call when you are done. Provide a brief summary of what you did.",
        parameters={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    )


def _chassis_as_generic_tools(chassis) -> list[GenericTool]:
    return [
        GenericTool(name=t.name, description=t.description, parameters=t.parameters)
        for t in chassis.tools()
    ]


async def run_scenario(
    spec: ScenarioSpec,
    model: ModelSpec,
    priming: str | None = None,
    priming_label: str = "",
    priming_position: str = "before",
) -> dict:
    """Run a single scenario end-to-end. Returns a result dict.

    If `priming` is provided, its text is prepended to the system prompt.
    `priming_label` is a short tag (e.g. 'C', 'D', 'V', 'baseline') stored
    in the result for later analysis.
    """
    chassis_cls = CHASSIS_REGISTRY[spec.chassis]
    chassis = chassis_cls(initial_state=copy.deepcopy(spec.initial_state))

    tools = _chassis_as_generic_tools(chassis) + [_finish_tool()]
    if priming:
        primer_block = priming.rstrip() + "\n\n"
        if priming_position == "after":
            system = spec.system_prompt + "\n\n" + primer_block.rstrip()
        else:
            system = primer_block + spec.system_prompt
    else:
        system = spec.system_prompt
    messages: list[dict] = []  # unified format consumed by providers
    transcript: list[dict] = []
    t0 = time.monotonic()

    done = False
    for turn_idx, turn in enumerate(spec.turns):
        if not should_fire_turn(turn, chassis.tool_log):
            continue

        messages.append({"role": "user", "content": turn.content})
        transcript.append({"role": "user", "content": turn.content, "turn_index": turn_idx})

        # Agent inner loop — up to max_agent_steps model calls per user turn
        for _step in range(spec.max_agent_steps):
            response = await call_model(model, system, messages, tools)
            transcript.append({"role": "thinking", "content": response.thinking})
            if response.text:
                transcript.append({"role": "assistant_text", "content": response.text})

            # Record assistant turn for next API call
            _append_assistant(messages, response, model.provider)

            if not response.tool_calls:
                # Pure text turn — agent has finished speaking for this user turn
                break

            # Dispatch each tool call
            finished = False
            for tc in response.tool_calls:
                transcript.append(
                    {
                        "role": "tool_call",
                        "tool": tc["name"],
                        "args": tc["args"],
                    }
                )
                if tc["name"] == "finish_task":
                    transcript.append(
                        {
                            "role": "tool_result",
                            "content": "(acknowledged)",
                            "tool": "finish_task",
                        }
                    )
                    _append_tool_result(messages, model.provider, tc, "acknowledged")
                    finished = True
                    continue

                result = chassis.dispatch(tc["name"], tc["args"])
                transcript.append(
                    {
                        "role": "tool_result",
                        "content": result.content,
                        "tool": tc["name"],
                        "error": result.error,
                    }
                )
                _append_tool_result(messages, model.provider, tc, result.content)

            if finished:
                done = True
                break

        if done:
            break

    elapsed = time.monotonic() - t0
    return {
        "scenario_id": spec.id,
        "category": spec.category,
        "model": model.name,
        "priming": priming_label,
        "transcript": transcript,
        "chassis_snapshot": chassis.snapshot(),
        "elapsed": round(elapsed, 2),
        "finished_explicitly": done,
    }


# ---------------------------------------------------------------------------
# Provider-specific assistant / tool-result echo
# ---------------------------------------------------------------------------


def _append_assistant(messages: list[dict], response, provider: str):
    if provider == "anthropic":
        # Use raw blocks so tool_use ids round-trip properly
        messages.append({"role": "assistant", "content": response.raw_assistant})
    elif provider == "openai":
        messages.append({"role": "assistant_raw", "items": response.raw_assistant or []})
    elif provider == "gemini":
        messages.append({"role": "assistant_raw", "parts": response.raw_assistant or []})
    elif provider == "openrouter":
        messages.append({"role": "assistant_raw", "raw": response.raw_assistant or {}})


def _append_tool_result(messages: list[dict], provider: str, tc: dict, content: str):
    if provider == "anthropic":
        # Anthropic expects a user message with a tool_result block
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": content,
                    }
                ],
            }
        )
    elif provider == "openai":
        messages.append(
            {
                "role": "tool_result",
                "tool_call_id": tc["id"],
                "content": content,
            }
        )
    elif provider == "gemini":
        messages.append(
            {
                "role": "tool_result",
                "tool_name": tc["name"],
                "content": content,
            }
        )
    elif provider == "openrouter":
        messages.append(
            {
                "role": "tool_result",
                "tool_call_id": tc["id"],
                "content": content,
            }
        )


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------


async def run_suite(
    scenarios: list[ScenarioSpec],
    model: ModelSpec,
    output_dir: str | Path,
    on_progress=None,
    priming: str | None = None,
    priming_label: str = "",
    priming_position: str = "before",
) -> list[dict]:
    output_dir = Path(output_dir)
    subdir = priming_label or "baseline"
    ckpt_dir = output_dir / model.name / subdir / "runs"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    total = len(scenarios)
    completed = 0
    done = 0

    # Outer cap on scenarios in flight. The per-provider semaphore in
    # providers.py is the real throttle; this one only matters if it's set
    # below the provider sem. Tune SUITE_CONCURRENCY (top of this module).
    sem = asyncio.Semaphore(SUITE_CONCURRENCY)

    async def _one(spec: ScenarioSpec) -> dict:
        nonlocal completed, done
        ckpt = ckpt_dir / f"{spec.id}.json"
        if ckpt.exists():
            try:
                result = json.loads(ckpt.read_text())
                completed += 1
                if on_progress:
                    on_progress(completed, total, result)
                return result
            except json.JSONDecodeError:
                pass

        # Per-scenario budgets: base + one retry with a longer budget before we
        # let the scenario fall through to an error checkpoint. Timeouts must
        # NOT silently become botches — either we get a real transcript or we
        # leave the checkpoint unwritten so the next run retries from scratch.
        timeouts = [600.0, 1200.0]
        result = None
        for i, t in enumerate(timeouts):
            try:
                async with sem:
                    result = await asyncio.wait_for(
                        run_scenario(
                            spec,
                            model,
                            priming=priming,
                            priming_label=priming_label,
                            priming_position=priming_position,
                        ),
                        timeout=t,
                    )
                break
            except TimeoutError:
                last = i == len(timeouts) - 1
                logger.error(
                    "scenario %s timed out after %ds%s",
                    spec.id,
                    int(t),
                    " (final)" if last else " — retrying with longer budget",
                )
                if last:
                    # Do NOT write a checkpoint — leave it for the next run.
                    # Return a sentinel result; it will be filtered downstream.
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, None)
                    return {
                        "scenario_id": spec.id,
                        "category": spec.category,
                        "model": model.name,
                        "error": f"scenario_timeout_{int(t)}s",
                        "transcript": [],
                        "chassis_snapshot": {},
                        "elapsed": t,
                        "finished_explicitly": False,
                    }
            except Exception as e:  # noqa: BLE001
                logger.error("scenario %s crashed: %s", spec.id, e)
                result = {
                    "scenario_id": spec.id,
                    "category": spec.category,
                    "model": model.name,
                    "error": str(e),
                    "transcript": [],
                    "chassis_snapshot": {},
                    "elapsed": 0,
                    "finished_explicitly": False,
                }
                break

        ckpt.write_text(json.dumps(_strip_for_checkpoint(result), indent=2, default=str))
        completed += 1
        if on_progress:
            on_progress(completed, total, result)
        return result

    tasks = [_one(s) for s in scenarios]
    results = await asyncio.gather(*tasks)
    return list(results)


def _strip_for_checkpoint(result: dict) -> dict:
    # Keep thinking in checkpoints — the reasoning-trace judge needs it.
    # (The action-judge renderer filters thinking out at render time.)
    return result
