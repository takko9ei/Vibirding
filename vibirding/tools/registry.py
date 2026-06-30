"""ToolManager — the single, uniform tool contract.

Every tool, regardless of what it does, is registered here and goes through one
pipeline on execution:

    find(name) -> schema-validate input -> if write: permission gate -> run()
                                                                      -> normalize to ToolResult

This module also defines the shape a tool must have (the `Tool` protocol) and the
`ToolContext` handed to each run(), keeping the contract in one place
(architecture section 5: "tools/registry.py 统一工具契约").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from ..harness.permissions import Permissions
from ..schemas import ToolResult


@dataclass
class ToolContext:
    """Execution context passed to a tool's run() and used by the write gate.

    Holds only what S1 needs (permissions for the gate). Later slices grow it
    (e.g. the append-only log handle in S4) without changing the registry API.
    """

    permissions: Permissions | None = None


@runtime_checkable
class Tool(Protocol):
    """The shape every tool must satisfy (structural typing — no inheritance)."""

    name: str
    description: str  # menu description shown to the model
    input_schema: dict  # JSON Schema; becomes the function-declaration parameters
    schema: type[BaseModel]  # pydantic model for our-side input validation
    risk: str  # "read" | "write"

    def run(self, input: dict, ctx: ToolContext) -> ToolResult: ...


class ToolManager:
    """Holds tools by name; produces the model-facing menu; executes them."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def find(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict]:
        """The menu handed to the model: name / description / input_schema only."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, input: dict, ctx: ToolContext) -> ToolResult:
        """Run one tool, normalizing every outcome into a ToolResult.

        Order is fixed by the contract: find -> validate -> (write?) gate -> run.
        Any failure becomes ok=False so the loop can feed it back to the model.
        """
        # 1. find
        tool = self.find(name)
        if tool is None:
            return ToolResult(ok=False, output=f"unknown tool: {name}")

        # 2. validate the model-supplied input against the tool's pydantic schema
        try:
            tool.schema.model_validate(input)
        except ValidationError as e:
            return ToolResult(ok=False, output=f"invalid input for {name}: {e}")

        # 3. write gate — read tools skip this entirely
        if tool.risk == "write":
            decision = (
                ctx.permissions.check(name, tool.risk, input)
                if ctx.permissions is not None
                else "deny"  # fail closed if no permissions wired in
            )
            if decision != "allow":
                return ToolResult(ok=False, output=f"permission denied: {name}")

        # 4. run, normalizing any exception into a ToolResult
        try:
            return tool.run(input, ctx)
        except Exception as e:  # normalize ALL tool errors so the loop stays alive
            return ToolResult(ok=False, output=f"tool error in {name}: {e}")
