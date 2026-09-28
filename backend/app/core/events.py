"""Event bus of a run: what the WebSocket streams and what a reconnect gets as `snapshot`.

Every message has `type`, `seq` and `ts`. The bus keeps the last log lines, the whole progress
and resources series and the warnings, so a reload of the page loses nothing.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.storage.models import utcnow

SNAPSHOT_LOG_LINES = 2000
SUBSCRIBER_QUEUE = 2000
# Finished runs whose buses stay in memory, so their screen still shows the charts.
KEEP_FINISHED = 5

Message = dict[str, Any]


def _drain(queue: asyncio.Queue[Message | None]) -> None:
    while not queue.empty():
        queue.get_nowait()


def _ts(now: datetime | None = None) -> str:
    return (now or utcnow()).isoformat()


@dataclass
class RunEvents:
    run_id: int
    config: dict[str, Any]
    status: Message = field(default_factory=dict)
    seq: int = 0
    log: deque[Message] = field(default_factory=lambda: deque(maxlen=SNAPSHOT_LOG_LINES))
    progress: list[Message] = field(default_factory=list)
    resources: list[Message] = field(default_factory=list)
    warnings: list[Message] = field(default_factory=list)
    finished: bool = False
    _subscribers: set[asyncio.Queue[Message | None]] = field(default_factory=set)

    def publish(self, type_: str, **payload: Any) -> Message:
        self.seq += 1
        message: Message = {"type": type_, "seq": self.seq, "ts": _ts(), **payload}
        if type_ == "log":
            self.log.append(message)
        elif type_ == "progress":
            self.progress.append(message)
        elif type_ == "resources":
            self.resources.append(message)
        elif type_ == "warning":
            self.warnings.append(message)
        elif type_ == "status":
            self.status = message
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A slow client: end its stream; on reconnect it gets a fresh snapshot.
                self._subscribers.discard(queue)
                _drain(queue)
                queue.put_nowait(None)
        return message

    def snapshot(self) -> Message:
        return {
            "type": "snapshot",
            "seq": self.seq,
            "ts": _ts(),
            "run_id": self.run_id,
            "status": self.status,
            "config": self.config,
            "log": list(self.log),
            "progress": self.progress,
            "resources": self.resources,
            "warnings": self.warnings,
        }

    def subscribe(self) -> tuple[Message, asyncio.Queue[Message | None]]:
        """Snapshot and a queue of later messages, taken atomically (no gap, no duplicate)."""
        queue: asyncio.Queue[Message | None] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE)
        self._subscribers.add(queue)
        return self.snapshot(), queue

    def unsubscribe(self, queue: asyncio.Queue[Message | None]) -> None:
        self._subscribers.discard(queue)

    def close(self) -> None:
        """No more messages: subscribers get None and end their stream."""
        self.finished = True
        for queue in list(self._subscribers):
            if queue.full():
                _drain(queue)
            queue.put_nowait(None)
        self._subscribers.clear()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class EventHub:
    def __init__(self, keep_finished: int = KEEP_FINISHED) -> None:
        self._runs: OrderedDict[int, RunEvents] = OrderedDict()
        self._keep_finished = keep_finished

    def open(self, run_id: int, config: dict[str, Any]) -> RunEvents:
        events = RunEvents(run_id=run_id, config=config)
        self._runs[run_id] = events
        return events

    def get(self, run_id: int) -> RunEvents | None:
        return self._runs.get(run_id)

    def finish(self, run_id: int) -> None:
        events = self._runs.get(run_id)
        if events is None:
            return
        events.close()
        self._runs.move_to_end(run_id)
        finished = [rid for rid, ev in self._runs.items() if ev.finished]
        for rid in finished[: max(len(finished) - self._keep_finished, 0)]:
            del self._runs[rid]
