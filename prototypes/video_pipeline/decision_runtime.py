"""One asyncio owner for the decision core. Reads metadata only; no frame access."""
import asyncio
import copy
import os
import time

from encoding_decision import DecisionInputs, EncodingDecision, StreamCapability
from sources import SPECS


class DecisionRuntime:
    def __init__(self, bank, status):
        self.bank, self.status = bank, status
        self.core = EncodingDecision([StreamCapability(s.id,s.name,s.width,s.height,s.fps) for s in SPECS])
        self.task = None
        self.evaluated_at = None

    def evaluate(self):
        sources = self.bank.state()['sources']
        available = {s['id'] for s in sources if s['running'] and s.get('age_ms') is not None
                     and s['age_ms'] < 1000 and not s.get('error')}
        self.core.evaluate(DecisionInputs.from_snapshot(self.status.manager.snapshot()), available)
        self.evaluated_at = time.monotonic()

    async def start(self):
        self.evaluate()
        self.task = asyncio.create_task(self.run())

    async def run(self):
        while True:
            await asyncio.sleep(.2)
            self.evaluate()

    def configure(self, share):
        self.core.configure(share)
        self.evaluate()

    def state(self):
        age = time.monotonic()-self.evaluated_at if self.evaluated_at is not None else None
        alive = self.task is not None and not self.task.done()
        error = None
        if self.task and self.task.done() and not self.task.cancelled():
            exception = self.task.exception()
            error = str(exception) if exception else None
        return dict(copy.deepcopy(self.core.last), process_pid=os.getpid(),
                    runtime_healthy=alive and age is not None and age < 1,
                    evaluation_age_s=age, runtime_error=error,
                    allocation_source='Manual bench input standing in for future comms allocation')

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
