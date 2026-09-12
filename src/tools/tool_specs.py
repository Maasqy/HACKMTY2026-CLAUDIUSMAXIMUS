"""
src/tools/tool_specs.py

Turns EstateDB's typed public methods into tool-calling descriptors (JSON
Schema-shaped, the format Ollama/OpenAI-style function calling expects) by
introspection — never by hand-maintaining a second copy of the tool list.

Why this matters for "constraints live in code, not in prompts": the set of
things the LLM is *allowed to call* is exactly, mechanically, the public
method list of EstateDB. Add a method here and the model gains a tool by
writing one typed function; there is no separate prompt-side tool menu that
can drift out of sync with what the code actually executes.

Usage:
    from src.tools import EstateDB
    from src.tools.tool_specs import build_tool_specs, dispatch

    specs = build_tool_specs(EstateDB)             # hand to the LLM client
    with EstateDB(estate_path) as estate:
        result = dispatch(estate, "obtener_facturas", {"rfc_emisor": "..."})
"""

from __future__ import annotations

import inspect
import typing
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, get_args, get_origin

_PRIVATE_PREFIXES = ("_",)
_EXCLUDED = {"close"}  # lifecycle methods, not investigation tools

_PY_TO_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _json_type_for(annotation: Any) -> tuple[str, bool]:
    """Returns (json_type, is_optional) for a parameter annotation."""
    origin = get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            t, _ = _json_type_for(args[0])
            return t, True
        return "string", True  # unions of concrete types: fall back safely
    return _PY_TO_JSON_TYPE.get(annotation, "string"), False


def build_tool_specs(cls: type) -> list[dict]:
    """Introspects every public method on `cls` (skipping dunder/private
    methods and lifecycle methods) and returns one tool descriptor per
    method: name, description (from the docstring), and a JSON-Schema
    `parameters` object built from the method's type hints and defaults."""
    specs = []
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith(_PRIVATE_PREFIXES) or name in _EXCLUDED:
            continue
        sig = inspect.signature(member)
        doc = inspect.getdoc(member) or ""
        properties: dict[str, dict] = {}
        required: list[str] = []
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            json_type, optional = _json_type_for(param.annotation)
            properties[pname] = {"type": json_type}
            has_default = param.default is not inspect.Parameter.empty
            if not has_default and not optional:
                required.append(pname)
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": doc,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return sorted(specs, key=lambda s: s["function"]["name"])


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def dispatch(estate, tool_name: str, arguments: dict) -> Any:
    """Calls `tool_name` on `estate` with `arguments` (as decoded from an
    LLM tool call) and returns a JSON-serializable result. Raises
    AttributeError for an unknown tool name and TypeError for a bad
    argument — both are meant to be caught by the investigator's tool loop
    and fed back to the model as an error message, not to crash the run."""
    if tool_name.startswith(_PRIVATE_PREFIXES) or tool_name in _EXCLUDED:
        raise AttributeError(f"'{tool_name}' is not a callable tool")
    method: Callable = getattr(estate, tool_name)
    result = method(**arguments)
    return _to_jsonable(result)
