"""Multi-provider LLM calling with dynamic tool use and thinking.

Single dispatch layer over four providers (Anthropic, OpenAI, Google Gemini,
OpenRouter). Each scenario can pass its own tool set rather than a fixed tool;
returns all tool calls from a turn plus any final text, so scenarios can run
multi-tool agentic loops.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# Inline-XML tool-call parser. Some Qwen-family models served through
# OpenAI-compatible endpoints render tool calls as Llama-3.1 XML rather than
# the OpenAI tool_calls field:
#   <tool_call>
#   <function=NAME>
#   <parameter=KEY>VALUE</parameter>
#   ...
#   </function>
#   </tool_call>
# Server-side parsers occasionally miss them and pass the XML through as plain
# text. We parse both the Llama-style (function + parameter tags) and the
# JSON-in-XML variant, converting either to a canonical
# {"name": ..., "args": {...}} dict the runner expects.

_TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FUNCTION_RE = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.DOTALL)
_PARAMETER_RE = re.compile(r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _coerce_value(s: str):
    """Best-effort type recovery. Tool parameters come in as raw strings; when
    they look like JSON, parse — otherwise leave as string."""
    s = s.strip()
    if not s:
        return s
    if (
        s[0] in "[{"
        or s in ("true", "false", "null")
        or s.lstrip("-").replace(".", "", 1).isdigit()
    ):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    return s


def _parse_inline_tool_calls(text: str) -> list[dict]:
    calls: list[dict] = []
    for i, outer in enumerate(_TOOL_CALL_RE.finditer(text or "")):
        body = outer.group(1).strip()
        # Try Qwen native JSON format first
        json_match = _JSON_OBJECT_RE.search(body)
        if json_match:
            try:
                payload = json.loads(json_match.group(0))
                name = payload.get("name")
                args = payload.get("arguments")
                if args is None:
                    args = payload.get("args") or {}
                if name:
                    calls.append({"name": name, "args": args, "id": f"xml_{i}"})
                    continue
            except json.JSONDecodeError:
                pass
        # Fall through to Llama-3.1 XML: <function=NAME>...<parameter=K>V</parameter>...</function>
        fn = _FUNCTION_RE.search(body)
        if fn:
            name = fn.group(1)
            inner = fn.group(2)
            args = {k: _coerce_value(v) for k, v in _PARAMETER_RE.findall(inner)}
            calls.append({"name": name, "args": args, "id": f"xml_{i}"})
    return calls


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str  # "anthropic" | "openai" | "gemini" | "openrouter"
    model_id: str
    thinking_config: dict = field(default_factory=dict)
    temperature: float = 0.7


MODEL_REGISTRY: dict[str, ModelSpec] = {
    # Anthropic
    "opus-4": ModelSpec(
        "opus-4",
        "anthropic",
        "claude-opus-4-20250514",
        {"stream": True},
    ),
    "opus-4.1": ModelSpec(
        "opus-4.1",
        "anthropic",
        "claude-opus-4-1-20250805",
        {"thinking": "enabled", "budget_tokens": 10000, "stream": True},
    ),
    "opus-4.5": ModelSpec(
        "opus-4.5",
        "anthropic",
        "claude-opus-4-5-20251101",
        {"thinking": "enabled", "budget_tokens": 10000},
    ),
    "opus-4.6": ModelSpec(
        "opus-4.6",
        "anthropic",
        "claude-opus-4-6",
        {"thinking": "adaptive", "effort": "medium"},
    ),
    "opus-4.7": ModelSpec(
        "opus-4.7",
        "anthropic",
        "claude-opus-4-7",
        {"thinking": "adaptive", "effort": "medium"},
    ),
    "sonnet-4": ModelSpec(
        "sonnet-4",
        "anthropic",
        "claude-sonnet-4-20250514",
        {"stream": True},
    ),
    "sonnet-4.5": ModelSpec(
        "sonnet-4.5",
        "anthropic",
        "claude-sonnet-4-5",
        {"thinking": "enabled", "budget_tokens": 10000},
    ),
    "sonnet-4.6": ModelSpec(
        "sonnet-4.6",
        "anthropic",
        "claude-sonnet-4-6",
        {"thinking": "adaptive", "effort": "medium"},
    ),
    "haiku-4.5": ModelSpec(
        "haiku-4.5",
        "anthropic",
        "claude-haiku-4-5-20251001",
        {"thinking": "enabled", "budget_tokens": 8000},
    ),
    # OpenAI
    "gpt-5": ModelSpec(
        "gpt-5",
        "openai",
        "gpt-5",
        {"reasoning_effort": "medium"},
    ),
    "gpt-5.1": ModelSpec(
        "gpt-5.1",
        "openai",
        "gpt-5.1",
        {"reasoning_effort": "medium"},
    ),
    "gpt-5.2": ModelSpec(
        "gpt-5.2",
        "openai",
        "gpt-5.2",
        {"reasoning_effort": "medium"},
    ),
    "gpt-5.3": ModelSpec(
        "gpt-5.3",
        "openai",
        "gpt-5.3-chat-latest",
        {"reasoning_effort": "medium"},
    ),
    "gpt-5.4": ModelSpec(
        "gpt-5.4",
        "openai",
        "gpt-5.4",
        {"reasoning_effort": "medium"},
    ),
    # Google
    "gemini-2.5-flash-lite": ModelSpec(
        "gemini-2.5-flash-lite",
        "gemini",
        "gemini-2.5-flash-lite",
        {},
    ),
    "gemini-2.5-flash": ModelSpec(
        "gemini-2.5-flash",
        "gemini",
        "gemini-2.5-flash",
        {},
    ),
    "gemini-2.5-pro": ModelSpec(
        "gemini-2.5-pro",
        "gemini",
        "gemini-2.5-pro",
        {},
    ),
    "gemini-3-pro": ModelSpec(
        "gemini-3-pro",
        "gemini",
        "gemini-3-pro-preview",
        {"thinking_level": "MEDIUM"},
    ),
    "gemini-3.1-pro": ModelSpec(
        "gemini-3.1-pro",
        "gemini",
        "gemini-3.1-pro-preview",
        {"thinking_level": "MEDIUM"},
    ),
    "gemini-3-flash": ModelSpec(
        "gemini-3-flash",
        "gemini",
        "gemini-3-flash-preview",
        {"thinking_level": "MEDIUM"},
    ),
    "gemini-3.1-flash-lite": ModelSpec(
        "gemini-3.1-flash-lite",
        "gemini",
        "gemini-3.1-flash-lite-preview",
        {"thinking_level": "MEDIUM"},
    ),
    # OpenRouter (OpenAI-compatible; uses Chat Completions API)
    "deepseek-v3.2": ModelSpec(
        "deepseek-v3.2",
        "openrouter",
        "deepseek/deepseek-v3.2",
        {},
    ),
    "minimax-m2.7": ModelSpec(
        "minimax-m2.7",
        "openrouter",
        "minimax/minimax-m2.7",
        {},
    ),
    "kimi-k2.5": ModelSpec(
        "kimi-k2.5",
        "openrouter",
        "moonshotai/kimi-k2.5",
        {},
    ),
    "qwen-3.6-plus": ModelSpec(
        "qwen-3.6-plus",
        "openrouter",
        "qwen/qwen3.6-plus",
        {},
    ),
    "qwen-3.5-27b": ModelSpec(
        "qwen-3.5-27b",
        "openrouter",
        "qwen/qwen3.5-27b",
        {},
    ),
    "glm-5": ModelSpec(
        "glm-5",
        "openrouter",
        "z-ai/glm-5",
        {},
    ),
    # xAI Grok via OpenRouter. `reasoning_effort: medium` opts into xAI's
    # reasoning-token output; Grok 4.1/4.2 return a readable
    # `reasoning.summary` in this mode. Grok 4 original returned only opaque
    # encrypted tokens (an xAI policy choice) so it's dropped from the bench.
    "grok-4.1": ModelSpec(
        "grok-4.1",
        "openrouter",
        "x-ai/grok-4.1-fast",
        {"reasoning_effort": "medium"},
    ),
    "grok-4.2": ModelSpec(
        "grok-4.2",
        "openrouter",
        "x-ai/grok-4.20",
        {"reasoning_effort": "medium"},
    ),
}


# ---------------------------------------------------------------------------
# Generic tool schema (used internally; translated per-provider at call time)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenericTool:
    """Provider-agnostic tool spec. `parameters` is a JSON schema object."""

    name: str
    description: str
    parameters: dict


# ---------------------------------------------------------------------------
# Per-provider tool translation
# ---------------------------------------------------------------------------


def _anthropic_tools(tools: list[GenericTool]) -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
    ]


def _openai_tools(tools: list[GenericTool]) -> list[dict]:
    return [
        {
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        }
        for t in tools
    ]


_GEMINI_TYPE_MAP = {
    "object": "OBJECT",
    "array": "ARRAY",
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
}


def _to_gemini_schema(schema: dict):
    from google.genai import types as genai_types

    t = schema.get("type", "object")
    kwargs: dict = {"type": _GEMINI_TYPE_MAP.get(t, "STRING")}
    if "description" in schema:
        kwargs["description"] = schema["description"]
    if "enum" in schema:
        kwargs["enum"] = schema["enum"]
    if t == "object":
        props = schema.get("properties", {})
        if props:
            kwargs["properties"] = {k: _to_gemini_schema(v) for k, v in props.items()}
        if schema.get("required"):
            kwargs["required"] = schema["required"]
    elif t == "array":
        if "items" in schema:
            kwargs["items"] = _to_gemini_schema(schema["items"])
    return genai_types.Schema(**kwargs)


def _gemini_tools(tools: list[GenericTool]):
    from google.genai import types as genai_types

    return [
        genai_types.Tool(
            function_declarations=[
                genai_types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=_to_gemini_schema(t.parameters),
                )
                for t in tools
            ]
        )
    ]


# ---------------------------------------------------------------------------
# Clients (lazy singletons)
# ---------------------------------------------------------------------------

_anthropic_client = None
_openai_client = None
_gemini_client = None
_openrouter_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.AsyncAnthropic()
    return _anthropic_client


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        import openai

        _openai_client = openai.AsyncOpenAI()
    return _openai_client


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        _gemini_client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY"),
            http_options={"timeout": 600_000},
        )
    return _gemini_client


def _get_openrouter_client():
    global _openrouter_client
    if _openrouter_client is None:
        import openai

        _openrouter_client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
        )
    return _openrouter_client


# ---------------------------------------------------------------------------
# Per-provider concurrency semaphores
# ---------------------------------------------------------------------------
#
# Tune here. The CLI runs the target phase fully before judging
# (cli.py `_run` / `_prime`), so a target run and a judge run never share a
# semaphore in time — one number per provider is enough.
PROVIDER_CONCURRENCY: dict[str, int] = {
    "anthropic": 50,
    "openai": 50,
    "gemini": 50,
    "openrouter": 50,
}
DEFAULT_CONCURRENCY = 50

_provider_semaphores: dict[str, asyncio.Semaphore] = {}


def get_semaphore(provider: str) -> asyncio.Semaphore:
    if provider not in _provider_semaphores:
        limit = PROVIDER_CONCURRENCY.get(provider, DEFAULT_CONCURRENCY)
        _provider_semaphores[provider] = asyncio.Semaphore(limit)
    return _provider_semaphores[provider]


def reset_semaphores():
    _provider_semaphores.clear()


# ---------------------------------------------------------------------------
# Unified response
# ---------------------------------------------------------------------------


@dataclass
class ModelResponse:
    """Result of one model turn.

    tool_calls: list of {"name": str, "args": dict, "id": str|None}
    text: free-form text the model emitted alongside (or instead of) tool calls
    thinking: extended-thinking text (may be empty)
    raw_assistant: provider-native assistant message block for echo-back in next turn
    """

    tool_calls: list[dict]
    text: str
    thinking: str
    raw_assistant: object = None  # provider-specific, for conversation continuation


# ---------------------------------------------------------------------------
# Provider callers
# ---------------------------------------------------------------------------

MAX_RETRIES = 2
RETRY_BASE_DELAY = 2.0


async def call_anthropic(
    spec: ModelSpec,
    system: str,
    messages: list[dict],
    tools: list[GenericTool],
) -> ModelResponse:
    client = _get_anthropic_client()
    sem = get_semaphore("anthropic")

    # Structured system with cache_control on the long prefix. When a primer
    # is present we route via runner adding "─── BEGIN ───" anchor; the system
    # string is identical across every scenario in a (model, condition) run so
    # Anthropic's prompt cache gets a hit rate approaching 1.0 within a
    # condition run, and for judge runs each scenario+rubric is also repeated.
    # Cache TTL default is 5 min; within-condition fan-out is typically <5 min.
    if len(system) > 1024:  # cacheable only above ~1k tokens
        system_blocks = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    else:
        system_blocks = system

    kwargs: dict = {
        "model": spec.model_id,
        "max_tokens": 16000,
        "system": system_blocks,
        "messages": messages,
        "tools": _anthropic_tools(tools),
    }
    tc = spec.thinking_config
    if tc.get("thinking") == "adaptive":
        kwargs["thinking"] = {"type": "adaptive"}
        if tc.get("effort"):
            kwargs["output_config"] = {"effort": tc["effort"]}
    elif tc.get("thinking") == "enabled":
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": tc.get("budget_tokens", 8000)}
    else:
        kwargs["temperature"] = spec.temperature

    async with sem:
        if tc.get("stream"):
            # Streaming path: required for older / slower models (e.g. opus-4,
            # opus-4.1) whose full-completion requests exceed the 10-minute
            # non-streaming horizon. Assemble the final message from the stream.
            async with client.messages.stream(**kwargs) as stream:
                resp = await stream.get_final_message()
        else:
            resp = await client.messages.create(**kwargs)

    thinking = ""
    text = ""
    tool_calls = []
    assistant_blocks = []
    for block in resp.content:
        if block.type == "thinking":
            thinking += block.thinking + "\n"
            b = {"type": "thinking", "thinking": block.thinking}
            if getattr(block, "signature", None):
                b["signature"] = block.signature
            assistant_blocks.append(b)
        elif block.type == "text":
            text += block.text
            assistant_blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            tool_calls.append({"name": block.name, "args": dict(block.input), "id": block.id})
            assistant_blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return ModelResponse(tool_calls, text.strip(), thinking.strip(), assistant_blocks)


async def call_openai(
    spec: ModelSpec,
    system: str,
    messages: list[dict],
    tools: list[GenericTool],
) -> ModelResponse:
    client = _get_openai_client()
    sem = get_semaphore("openai")

    # OpenAI Responses API: use `input` list of items.
    # Messages in our format: {"role": "user|assistant", "content": str}
    # plus echo-back tool results as {"role": "tool_result", ...}
    input_list: list[dict] = []
    for m in messages:
        if m.get("role") == "tool_result":
            input_list.append(
                {
                    "type": "function_call_output",
                    "call_id": m["tool_call_id"],
                    "output": m["content"],
                }
            )
        elif m.get("role") == "assistant_raw":
            # previously-returned assistant items (function_call items etc.)
            # Strip output-only fields (status, etc.) that OpenAI rejects on input.
            for item in m["items"]:
                clean = {k: v for k, v in item.items() if k not in ("status",)}
                input_list.append(clean)
        else:
            input_list.append({"role": m["role"], "content": m["content"]})

    reasoning_effort = spec.thinking_config.get("reasoning_effort", "medium")
    # Deterministic cache key off the system prefix (instructions) → same prefix
    # across scenarios hits the same cache slot. Responses API also caches
    # automatically on prefix hash, but a stable key improves hit rate and
    # helps with cross-process consistency.
    import hashlib

    cache_key = hashlib.sha256(system.encode()).hexdigest()[:32]

    async with sem:
        resp = await client.responses.create(
            model=spec.model_id,
            instructions=system,
            input=input_list,
            tools=_openai_tools(tools),
            reasoning={"effort": reasoning_effort, "summary": "auto"},
            prompt_cache_key=cache_key,
        )

    thinking = ""
    text = ""
    tool_calls = []
    raw_items = []
    for item in resp.output:
        if item.type == "reasoning":
            if getattr(item, "summary", None):
                for s in item.summary:
                    if hasattr(s, "text"):
                        thinking += s.text + "\n"
            raw_items.append(item.model_dump() if hasattr(item, "model_dump") else dict(item))
        elif item.type == "function_call":
            args = json.loads(item.arguments) if item.arguments else {}
            tool_calls.append({"name": item.name, "args": args, "id": item.call_id})
            raw_items.append(item.model_dump() if hasattr(item, "model_dump") else dict(item))
        elif item.type == "message":
            for c in item.content:
                if hasattr(c, "text"):
                    text += c.text
            raw_items.append(item.model_dump() if hasattr(item, "model_dump") else dict(item))
    return ModelResponse(tool_calls, text.strip(), thinking.strip(), raw_items)


async def call_gemini(
    spec: ModelSpec,
    system: str,
    messages: list[dict],
    tools: list[GenericTool],
) -> ModelResponse:
    from google.genai import types as genai_types

    client = _get_gemini_client()
    sem = get_semaphore("gemini")

    contents = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            contents.append(
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=m["content"])],
                )
            )
        elif role == "assistant":
            contents.append(
                genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(text=m["content"])],
                )
            )
        elif role == "assistant_raw":
            # m["parts"] is a list of {"text":...}, {"function_call":{...}}, or {"thought":True,"text":...}
            # Each may carry a thought_signature that must round-trip.
            parts = []
            for p in m["parts"]:
                sig = p.get("thought_signature")
                kwargs: dict = {}
                if p.get("thought"):
                    kwargs["thought"] = True
                    kwargs["text"] = p.get("text", "")
                elif "function_call" in p:
                    fc = p["function_call"]
                    kwargs["function_call"] = genai_types.FunctionCall(
                        name=fc["name"],
                        args=fc["args"],
                    )
                elif "text" in p:
                    kwargs["text"] = p["text"]
                else:
                    continue
                if sig:
                    kwargs["thought_signature"] = sig
                parts.append(genai_types.Part(**kwargs))
            if parts:
                contents.append(genai_types.Content(role="model", parts=parts))
        elif role == "tool_result":
            contents.append(
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part(
                            function_response=genai_types.FunctionResponse(
                                name=m["tool_name"],
                                response={"result": m["content"]},
                            )
                        )
                    ],
                )
            )

    thinking_level = spec.thinking_config.get("thinking_level")
    config_kwargs = dict(
        system_instruction=system,
        max_output_tokens=8192,
        temperature=spec.temperature,
        tools=_gemini_tools(tools),
    )
    if thinking_level:
        config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
            thinking_level=thinking_level,
            include_thoughts=True,
        )
    config = genai_types.GenerateContentConfig(**config_kwargs)

    def _call():
        return client.models.generate_content(
            model=spec.model_id,
            contents=contents,
            config=config,
        )

    async with sem:
        resp = await asyncio.to_thread(_call)

    thinking = ""
    text = ""
    tool_calls = []
    raw_parts = []
    candidate = resp.candidates[0] if resp.candidates else None
    content = getattr(candidate, "content", None) if candidate else None
    parts = getattr(content, "parts", None) or []
    for part in parts:
        sig = getattr(part, "thought_signature", None)
        if getattr(part, "thought", False) and hasattr(part, "text"):
            thinking += part.text + "\n"
            # Preserve the thought part (with signature) so Gemini can validate next turn
            tp = {"thought": True, "text": part.text}
            if sig:
                tp["thought_signature"] = sig
            raw_parts.append(tp)
        elif getattr(part, "function_call", None):
            fc = part.function_call
            args = _deep_to_dict(fc.args)
            tool_calls.append({"name": fc.name, "args": args, "id": None})
            fcp = {"function_call": {"name": fc.name, "args": args}}
            if sig:
                fcp["thought_signature"] = sig
            raw_parts.append(fcp)
        elif getattr(part, "text", None):
            text += part.text
            tp = {"text": part.text}
            if sig:
                tp["thought_signature"] = sig
            raw_parts.append(tp)
    return ModelResponse(tool_calls, text.strip(), thinking.strip(), raw_parts)


def _deep_to_dict(obj):
    if isinstance(obj, dict):
        return {k: _deep_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_deep_to_dict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    try:
        return {k: _deep_to_dict(v) for k, v in dict(obj).items()}
    except (TypeError, ValueError):
        return str(obj)


async def call_openrouter(
    spec: ModelSpec,
    system: str,
    messages: list[dict],
    tools: list[GenericTool],
) -> ModelResponse:
    """OpenRouter via OpenAI-compatible Chat Completions API."""
    import hashlib

    client = _get_openrouter_client()
    sem = get_semaphore("openrouter")
    # OpenRouter caches common prefixes when a stable cache key is provided.
    # For models with native caching (Anthropic, Gemini via OR) this routes to
    # provider caching; for others it may be a no-op. Key on system prompt only
    # so that different scenarios within a condition share cache hits.
    cache_key = hashlib.sha256(system.encode()).hexdigest()[:32]

    # Chat Completions format: messages list with role strings, assistant
    # with optional tool_calls, tool results as role="tool".
    chat_messages = [{"role": "system", "content": system}]
    for m in messages:
        role = m.get("role")
        if role == "user":
            content = m["content"]
            # Anthropic-style tool_result blocks can leak through if an Anthropic
            # run somehow reused messages — flatten them.
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        chat_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": block["tool_use_id"],
                                "content": block["content"],
                            }
                        )
            else:
                chat_messages.append({"role": "user", "content": content})
        elif role == "assistant_raw":
            # From a previous openrouter turn — reconstruct assistant msg.
            # For reasoning models (e.g. Grok 4.x) we echo reasoning_details
            # back so the provider can round-trip its internal state between
            # turns; without this, Grok reasons from scratch each step.
            raw = m.get("raw") or {}
            msg = {"role": "assistant", "content": raw.get("content") or ""}
            if raw.get("tool_calls"):
                msg["tool_calls"] = raw["tool_calls"]
            if raw.get("reasoning_details"):
                msg["reasoning_details"] = raw["reasoning_details"]
            chat_messages.append(msg)
        elif role == "tool_result":
            chat_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": m["tool_call_id"],
                    "content": m["content"],
                }
            )

    tools_spec = [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]

    # Opt into provider-side reasoning when configured. The thinking_config
    # key `reasoning_effort` (e.g. "low" | "medium" | "high") maps to
    # OpenRouter's `extra_body.reasoning.effort`. This is what surfaces a
    # readable thinking trace for reasoning models served via OpenRouter —
    # most importantly the Grok 4.x line, where the default response omits
    # reasoning entirely.
    extra_body: dict = {"prompt_cache_key": cache_key}
    reasoning_cfg = spec.thinking_config.get("reasoning_effort")
    if reasoning_cfg:
        extra_body["reasoning"] = {"effort": reasoning_cfg}

    async with sem:
        resp = await client.chat.completions.create(
            model=spec.model_id,
            messages=chat_messages,
            tools=tools_spec,
            max_tokens=4096,
            temperature=spec.temperature,
            extra_body=extra_body,
        )

    msg = resp.choices[0].message
    text = msg.content or ""
    tool_calls = []
    raw_tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"name": tc.function.name, "args": args, "id": tc.id})
            raw_tool_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
            )

    # Extract any readable reasoning the provider returned. OpenRouter
    # normalizes reasoning into `msg.reasoning` (string) and
    # `msg.reasoning_details` (list of typed blocks). We concatenate
    # `reasoning.text` and `reasoning.summary` blocks — `reasoning.encrypted`
    # is opaque provider tokens, not text, so we skip it for `thinking`
    # (but we DO preserve it in raw_assistant for multi-turn echo-back).
    raw_msg = msg.model_dump() if hasattr(msg, "model_dump") else {}
    reasoning_parts: list[str] = []
    top_reasoning = raw_msg.get("reasoning")
    if isinstance(top_reasoning, str) and top_reasoning.strip():
        reasoning_parts.append(top_reasoning.strip())
    reasoning_details = raw_msg.get("reasoning_details") or []
    for block in reasoning_details:
        if not isinstance(block, dict):
            continue
        t = block.get("type")
        if t == "reasoning.text" and block.get("text"):
            reasoning_parts.append(block["text"].strip())
        elif t == "reasoning.summary" and block.get("summary"):
            # Skip if it's an exact dup of the top-level `reasoning` field
            # (OpenRouter often mirrors the first summary there).
            s = block["summary"].strip()
            if s and s not in reasoning_parts:
                reasoning_parts.append(s)
    thinking = "\n\n".join(reasoning_parts).strip()

    raw_assistant = {"content": msg.content, "tool_calls": raw_tool_calls}
    if reasoning_details:
        raw_assistant["reasoning_details"] = reasoning_details
    return ModelResponse(tool_calls, text.strip(), thinking, raw_assistant)


_PROVIDER_CALLERS = {
    "anthropic": call_anthropic,
    "openai": call_openai,
    "gemini": call_gemini,
    "openrouter": call_openrouter,
}


async def call_model(
    spec: ModelSpec,
    system: str,
    messages: list[dict],
    tools: list[GenericTool],
) -> ModelResponse:
    """Call a model with retry. messages accepts roles:
    user, assistant, assistant_raw, tool_result."""
    caller = _PROVIDER_CALLERS[spec.provider]
    # Long outer timeout so scenarios queued behind a tight provider semaphore
    # do not time out while waiting their turn. The real HTTP timeout is
    # enforced by the httpx client within each provider call.
    outer_timeout = 3600.0
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(
                caller(spec, system, messages, tools),
                timeout=outer_timeout,
            )
        except Exception as e:
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "%s attempt %d failed: %s (%r) — retry in %.1fs",
                    spec.name,
                    attempt + 1,
                    type(e).__name__,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("%s failed after %d attempts: %s", spec.name, MAX_RETRIES + 1, e)
                return ModelResponse([], f"(provider error: {e})", "", None)
