"""Base types for reusable chassis (simulated environments)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ToolSpec:
    """A tool a chassis exposes to the agent."""

    name: str
    description: str
    parameters: dict  # JSON schema object
    handler: Callable[[dict, Chassis], ToolResult]


@dataclass
class ToolResult:
    """Return from a tool handler."""

    content: str  # shown back to the agent
    observation: dict = field(default_factory=dict)  # structured record for hinge detection
    error: bool = False


class Chassis:
    """Base class. Subclasses define tools and hold mutable state."""

    name: str = "base"

    def __init__(self, initial_state: dict | None = None):
        self.state: dict = initial_state or {}
        # Ordered log of every tool call the agent has made in this scenario
        self.tool_log: list[dict] = []

    def tools(self) -> list[ToolSpec]:
        raise NotImplementedError

    def dispatch(self, name: str, args: dict) -> ToolResult:
        for t in self.tools():
            if t.name == name:
                try:
                    result = t.handler(args, self)
                except Exception as e:
                    result = ToolResult(content=f"ERROR: {e}", error=True)
                self.tool_log.append(
                    {
                        "tool": name,
                        "args": args,
                        "ok": not result.error,
                        "observation": result.observation,
                    }
                )
                return result
        return ToolResult(content=f"ERROR: unknown tool '{name}'", error=True)

    def snapshot(self) -> dict:
        """Serializable summary of final state + tool log for the judge."""
        return {"state": self.state, "tool_log": self.tool_log}
