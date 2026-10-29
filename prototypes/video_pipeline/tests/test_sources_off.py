import asyncio
from sources import Bank


def test_bank_start_does_not_launch_generators_or_preview_visibility_enable_them():
    async def run():
        bank=Bank()
        try:
            await bank.start()
            assert not any(s.running for s in bank.sources.values())
            bank.leases['visible-test']=10**20
            await asyncio.sleep(.2)
            assert bank.previews_enabled
            assert not any(s.process for s in bank.sources.values())
        finally:
            await bank.close()
    asyncio.run(run())
