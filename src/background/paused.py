"""A background run waiting on the user, kept in Redis until they answer.

When a worker reaches a call that must always ask (an image, which spends the user's
money), it cannot wait in memory for days: a restart or deploy would lose it. So it saves
the whole run -- every message, the calls it stopped on and what they ask -- here, and
stops. The user's answer is added to it, and the next run of the task carries on from
exactly that point. Unanswered for EXPIRE_SECONDS, it expires and the task fails as such.
"""

from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from src.core.agents.domain import LoopState
from src.core.cache.ports import CacheStore
from src.core.llm.domain import TokenUsage, ToolCall
from src.core.tools.domain import ClientRequest, Decision, ToolLocation, ToolResult

EXPIRE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class PausedRun:
    state: LoopState
    # the user's answers, once given; empty while the task waits
    decisions: dict[str, Decision] = field(default_factory=dict)

    @property
    def asking(self) -> tuple[ClientRequest, ...]:
        return self.state.pending_requests


def _key(task_id: UUID) -> str:
    return f"background:paused:{task_id}"


async def save(cache: CacheStore, task_id: UUID, paused: PausedRun) -> None:
    await cache.store_json(_key(task_id), _dump(paused), EXPIRE_SECONDS)


async def load(cache: CacheStore, task_id: UUID) -> PausedRun | None:
    data = await cache.get_json(_key(task_id))
    return _load(data) if data else None


async def remove(cache: CacheStore, task_id: UUID) -> None:
    await cache.remove(_key(task_id))


def answered(paused: PausedRun, decisions: dict[str, Decision]) -> PausedRun:
    return replace(paused, decisions={**paused.decisions, **decisions})


def _dump(paused: PausedRun) -> dict[str, Any]:
    state = paused.state
    return {
        "messages": state.messages,
        "pending_tool_calls": [_call(call) for call in state.pending_tool_calls],
        "completed_tool_results": [
            {"tool_call_id": r.tool_call_id, "content": r.content, "failed": r.failed}
            for r in state.completed_tool_results
        ],
        "iterations_used": state.iterations_used,
        "usage": {
            "input_tokens": state.usage.input_tokens,
            "output_tokens": state.usage.output_tokens,
            "total_tokens": state.usage.total_tokens,
            "cache_read_tokens": state.usage.cache_read_tokens,
            "cache_write_tokens": state.usage.cache_write_tokens,
        },
        "pending_requests": [
            {
                "call": _call(request.call),
                "location": str(request.location),
                "requires_approval": request.requires_approval,
                "detail": request.detail,
                "preview": request.preview if isinstance(request.preview, str) else None,
                "choices": {name: list(values) for name, values in request.choices.items()},
                "always_ask": request.always_ask,
            }
            for request in state.pending_requests
        ],
        "decisions": {
            call_id: {
                "approved": d.approved, "feedback": d.feedback, "output": d.output,
                "failed": d.failed, "args": dict(d.args),
            }
            for call_id, d in paused.decisions.items()
        },
    }


def _load(data: dict[str, Any]) -> PausedRun:
    state = LoopState(
        messages=list(data["messages"]),
        pending_tool_calls=tuple(_to_call(call) for call in data["pending_tool_calls"]),
        completed_tool_results=tuple(
            ToolResult(r["tool_call_id"], r["content"], r.get("failed", False))
            for r in data["completed_tool_results"]
        ),
        iterations_used=data["iterations_used"],
        usage=TokenUsage(**data["usage"]),
        pending_requests=tuple(
            ClientRequest(
                call=_to_call(r["call"]),
                location=ToolLocation(r["location"]),
                requires_approval=r["requires_approval"],
                detail=r.get("detail"),
                preview=r.get("preview"),
                choices={name: tuple(values) for name, values in (r.get("choices") or {}).items()},
                always_ask=r.get("always_ask", False),
            )
            for r in data["pending_requests"]
        ),
    )
    decisions = {
        call_id: Decision(
            approved=d["approved"], feedback=d.get("feedback", ""), output=d.get("output"),
            failed=d.get("failed", False), args=d.get("args") or {},
        )
        for call_id, d in (data.get("decisions") or {}).items()
    }
    return PausedRun(state=state, decisions=decisions)


def _call(call: ToolCall) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "args": call.args}


def _to_call(data: dict[str, Any]) -> ToolCall:
    return ToolCall(id=data["id"], name=data["name"], args=data["args"])
