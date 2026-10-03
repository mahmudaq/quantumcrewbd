"""Thread-safe event bridge between CrewAI and the UI (impl-doc risk #3).

Why this exists: CrewAI emits events from worker threads during a run, but
Streamlit re-renders on the main thread. Handing raw CrewAI callbacks straight
to Streamlit raises ``ScriptRunContext`` warnings and can corrupt widget state,
because two threads touch the same render context.

The bridge inverts that. CrewAI events are pushed onto a ``queue.Queue`` (safe
across threads) by a listener that touches nothing else. The UI drains the queue
from the main thread on its own schedule. Neither side holds a reference to the
other, so a slow or dead UI cannot stall a run, and a crashed run cannot wedge
the UI.

This module deliberately imports nothing from Streamlit. It is used headless by
Gate 4 and by the tests, and only the UI layer knows Streamlit exists.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Lane = Literal["A", "B", "1", "4", "5", ""]
Level = Literal["info", "tool", "success", "warning", "error"]

# Which lane an agent's activity belongs to, for the two-lane UI. Agents 2 and 3
# run concurrently after the checkpoint; 1 precedes it, 4 and 5 follow the merge.
AGENT_LANE: dict[str, Lane] = {
    "analyzer": "1",
    "market_intel": "B",
    "resource_planner": "A",
    "writer": "4",
    "reviewer": "5",
}

AGENT_LABEL: dict[str, str] = {
    "analyzer": "RFP Analysis",
    "market_intel": "Market Intelligence",
    "resource_planner": "Resource & Consortium",
    "writer": "Proposal Drafting",
    "reviewer": "QA Review",
}


@dataclass
class Event:
    """One thing that happened during a run. Plain data — JSON-serialisable.

    Keeping this a dataclass of primitives (not CrewAI objects) is what makes it
    safe to store in ``st.session_state``: runbook rule 3 says only
    JSON-serialisable data goes there, never CrewAI objects.
    """

    kind: str                      # agent_start | tool_start | tool_end | ...
    message: str
    agent: str = ""
    lane: Lane = ""
    level: Level = "info"
    tool: str = ""
    ts: float = field(default_factory=time.time)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventQueue:
    """A bounded-ish, thread-safe sink for run events.

    Bounded so a runaway loop cannot exhaust memory, but never blocks a producer
    — dropping the oldest event under pressure is the right failure mode, since
    the UI only ever renders a tail.
    """

    def __init__(self, maxlen: int = 2_000) -> None:
        self._q: queue.Queue[Event] = queue.Queue()
        self._lock = threading.Lock()
        self._all: list[Event] = []
        self._maxlen = maxlen
        self._dropped = 0

    def put(self, event: Event) -> None:
        with self._lock:
            self._all.append(event)
            if len(self._all) > self._maxlen:
                del self._all[: len(self._all) - self._maxlen]
                self._dropped += 1
        self._q.put_nowait(event)

    def drain(self) -> list[Event]:
        """Non-blocking: return everything queued since the last drain."""
        out: list[Event] = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out

    def history(self) -> list[Event]:
        """Everything seen so far, in order — for a post-run report."""
        with self._lock:
            return list(self._all)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped


class EventBridge:
    """Translates CrewAI events into :class:`Event` and pushes them to a queue.

    Registered against CrewAI's global event bus. Two details matter:

    * ``agent`` attribution is tracked here rather than read from the event,
      because tool events do not always carry the agent that triggered them.
      The current agent is set on ``AgentExecutionStartedEvent``.
    * the listener is a plain callable registry, not a CrewAI
      ``BaseEventListener`` subclass, so this module stays importable without
      CrewAI installed. ``attach()`` wires up the real bus.
    """

    def __init__(self, queue_: EventQueue | None = None) -> None:
        self.queue = queue_ or EventQueue()
        self._current_agent = ""
        self._handles: list[Any] = []

    # -- producer side (called from CrewAI's threads) ---------------------- #

    def _emit(self, kind: str, message: str, *, level: Level = "info",
              tool: str = "", agent: str = "", detail: str = "") -> None:
        who = agent or self._current_agent
        self.queue.put(Event(
            kind=kind, message=message, agent=who,
            lane=AGENT_LANE.get(who, ""), level=level, tool=tool, detail=detail,
        ))

    def on_agent_start(self, agent: str) -> None:
        self._current_agent = agent
        self._emit("agent_start",
                   f"▶ {AGENT_LABEL.get(agent, agent)} started")

    def on_agent_end(self, agent: str = "", ok: bool = True) -> None:
        who = agent or self._current_agent
        self._emit("agent_end",
                   f"{'✔' if ok else '✖'} {AGENT_LABEL.get(who, who)} "
                   f"{'finished' if ok else 'failed'}",
                   level="success" if ok else "error", agent=who)
        self._current_agent = ""

    def on_tool_start(self, tool: str, args: Any = None) -> None:
        self._emit("tool_start", f"🔧 {tool}", level="tool", tool=tool,
                   detail=_short(args))

    def on_tool_end(self, tool: str, ok: bool = True, detail: Any = None) -> None:
        self._emit("tool_end", f"{'✔' if ok else '✖'} {tool}",
                   level="success" if ok else "warning", tool=tool,
                   detail=_short(detail))

    def on_llm(self, message: str) -> None:
        self._emit("llm", message, level="info")

    def on_error(self, message: str) -> None:
        self._emit("error", message, level="error")

    def on_task_start(self, task: str) -> None:
        self._emit("task_start", f"• {task}")

    def on_task_end(self, task: str, ok: bool = True) -> None:
        self._emit("task_end", f"• {task} {'complete' if ok else 'failed'}",
                   level="success" if ok else "error")

    # -- consumer side (main thread / headless) ---------------------------- #

    def events(self) -> list[Event]:
        return self.queue.drain()

    def history(self) -> list[Event]:
        return self.queue.history()

    def summary(self) -> dict[str, Any]:
        """Counts for a post-run report."""
        hist = self.history()
        tools = [e for e in hist if e.kind == "tool_start"]
        return {
            "events": len(hist),
            "dropped": self.queue.dropped,
            "agents": sorted({e.agent for e in hist if e.agent}),
            "tool_calls": len(tools),
            "tools": sorted({e.tool for e in tools if e.tool}),
            "errors": [e.message for e in hist if e.level == "error"],
        }

    # -- CrewAI bus wiring ------------------------------------------------- #

    def attach(self) -> bool:
        """Subscribe to CrewAI's global event bus.

        Returns False (rather than raising) when CrewAI is not importable or the
        event API has moved, so the headless path degrades to a run with no
        live events instead of failing outright.
        """
        try:
            from crewai.events import crewai_event_bus
            from crewai.events.types.agent_events import (
                AgentExecutionCompletedEvent,
                AgentExecutionErrorEvent,
                AgentExecutionStartedEvent,
            )
            from crewai.events.types.task_events import (
                TaskCompletedEvent,
                TaskFailedEvent,
                TaskStartedEvent,
            )
            from crewai.events.types.tool_usage_events import (
                ToolUsageFinishedEvent,
                ToolUsageStartedEvent,
            )
        except Exception:                                       # noqa: BLE001
            return False

        def _hook(bus, fn, event_type):
            def handler(source, event):                          # noqa: ANN001
                try:
                    fn(event)
                except Exception:                                # noqa: BLE001
                    # A UI callback must never break a run.
                    pass
            bus.on(event_type)(handler)
            return handler

        def agent_of(event: Any) -> str:
            for attr in ("agent", "agent_role"):
                v = getattr(event, attr, None)
                if v is None:
                    continue
                for probe in ("role", "name"):
                    r = getattr(v, probe, None)
                    if isinstance(r, str) and r:
                        return _role_to_key(r)
                if isinstance(v, str):
                    return _role_to_key(v)
            return ""

        def on_agent_started(event: Any) -> None:
            self.on_agent_start(agent_of(event))

        def on_agent_done(event: Any) -> None:
            self.on_agent_end(agent_of(event) or self._current_agent, ok=True)

        def on_agent_err(event: Any) -> None:
            self.on_agent_end(agent_of(event) or self._current_agent, ok=False)
            self.on_error(str(getattr(event, "error", "agent error"))[:400])

        def on_tool_started(event: Any) -> None:
            name = str(getattr(event, "tool_name", "") or
                       getattr(getattr(event, "tool", None), "name", "") or "tool")
            self.on_tool_start(name, getattr(event, "tool_args", None))

        def on_tool_finished(event: Any) -> None:
            name = str(getattr(event, "tool_name", "") or
                       getattr(getattr(event, "tool", None), "name", "") or "tool")
            self.on_tool_end(name, ok=True, detail=getattr(event, "result", None))

        def on_task_started(event: Any) -> None:
            self.on_task_start(_short(getattr(event, "task", ""), 80))

        def on_task_done(event: Any) -> None:
            self.on_task_end(_short(getattr(event, "task", ""), 80), ok=True)

        def on_task_failed(event: Any) -> None:
            self.on_task_end(_short(getattr(event, "task", ""), 80), ok=False)
            self.on_error(str(getattr(event, "error", "task failed"))[:400])

        pairs = [
            (AgentExecutionStartedEvent, on_agent_started),
            (AgentExecutionCompletedEvent, on_agent_done),
            (AgentExecutionErrorEvent, on_agent_err),
            (ToolUsageStartedEvent, on_tool_started),
            (ToolUsageFinishedEvent, on_tool_finished),
            (TaskStartedEvent, on_task_started),
            (TaskCompletedEvent, on_task_done),
            (TaskFailedEvent, on_task_failed),
        ]
        try:
            for event_type, fn in pairs:
                self._handles.append(_hook(crewai_event_bus, fn, event_type))
        except Exception:                                        # noqa: BLE001
            return False
        return True

    def detach(self) -> None:
        """Unsubscribe. Call this when a run finishes.

        Without it, a second run would register a second set of handlers and
        every event would be counted twice — which looks like the agents doing
        double the tool calls.
        """
        try:
            from crewai.events import crewai_event_bus
        except Exception:                                        # noqa: BLE001
            self._handles.clear()
            return
        for handle in self._handles:
            for target in ("off", "remove_handler", "unregister_handler"):
                fn = getattr(crewai_event_bus, target, None)
                if callable(fn):
                    try:
                        fn(handle)
                    except Exception:                            # noqa: BLE001
                        pass
                    break
        self._handles.clear()


def _role_to_key(role: str) -> str:
    """Map a CrewAI agent role back to our short key.

    The bus reports the verbose role string ("Senior Procurement & Compliance
    Specialist"), but lanes are keyed by short name ("analyzer"). Matching on a
    distinctive substring of each ROLE constant keeps this working without a
    second registry to maintain.
    """
    low = role.lower()
    table = (
        ("procurement", "analyzer"),
        ("compliance specialist", "analyzer"),
        ("intelligence", "market_intel"),
        ("benchmarking", "market_intel"),
        ("resource allocator", "resource_planner"),
        ("teaming", "resource_planner"),
        ("bid writer", "writer"),
        ("proposal architect", "writer"),
        ("auditor", "reviewer"),
        ("quality controller", "reviewer"),
    )
    for needle, key in table:
        if needle in low:
            return key
    return ""


def _short(value: Any, limit: int = 120) -> str:
    """Render arbitrary event payloads as a short single-line string."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        try:
            import json
            value = json.dumps(value, default=str)
        except Exception:                                        # noqa: BLE001
            value = str(value)
    s = " ".join(str(value).split())
    return s[: limit - 1] + "…" if len(s) > limit else s
