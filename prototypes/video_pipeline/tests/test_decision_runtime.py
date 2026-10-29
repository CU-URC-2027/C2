import asyncio

from decision_runtime import DecisionRuntime
from status_manager import StatusManager


def test_decision_worker_runs_without_browser_and_reports_when_stopped():
    class Bank:
        def state(self):return {'sources':[]}
    class Status:
        manager=StatusManager([f'cam-{i:02}' for i in range(1,6)])
    async def run():
        runtime=DecisionRuntime(Bank(),Status())
        await runtime.start()
        try:
            first=runtime.state()
            assert first['runtime_healthy']
            await asyncio.sleep(.25)
            second=runtime.state()
            assert second['evaluation_sequence']>first['evaluation_sequence']
            assert second['mode']=='decision_only' and not second['encoder_connected']
        finally:
            await runtime.close()
        assert not runtime.state()['runtime_healthy']
    asyncio.run(run())
