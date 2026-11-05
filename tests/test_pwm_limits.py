import asyncio
import random
import pytest
from c2_web.runtime import Runtime
from c2_web.legacy import Control
from rover_link import packet


async def wait_for(predicate):
    async with asyncio.timeout(3):
        while not predicate():await asyncio.sleep(.02)


def test_zero_full_and_mixed_quantization_stay_inside_selected_wheel_pwm():
    rng=random.Random(7)
    for cap in (0,.05,.25,.5,1):
        c=Control();c.speed_limit=cap;c.receive('Xbox',0,0,False,0);assert c.enable(0)[0]
        for i in range(150):
            t,s=(1,1) if i==0 else (rng.uniform(-1,1),rng.uniform(-1,1))
            c.receive('Xbox',t,s,True,.01)
            out=c.output(.01);qt,qs=map(int,out['legacy_drive_preview'].strip().split(','))
            assert max(abs(qt+qs),abs(qt-qs))<=round(cap*255)
            packet('a'*16,i+1,1,'DRIVE',qt,qs)
        c.receive('Xbox',1,0,True,.02)
        assert c.output(.02)['legacy_drive_preview']==f'{round(cap*255)},0\n'


async def test_browser_cap_defaults_to_25_and_raising_it_disarms():
    r=Runtime();r.register('a')
    try:
        assert r.control.speed_limit==.25 and r.state()['speed_limit_max']==1
        await r.action('a','input',{'seq':0});await r.action('a','enable',{})
        await r.action('a','speed_limit',{'value':1})
        assert not r.control.armed and r.control.speed_limit==1
        assert r.control.output(r.clock())['left']==0
        await r.action('a','speed_limit',{'value':0})
        assert r.control.output(r.clock())['left']==0
        with pytest.raises(ValueError):await r.action('a','speed_limit',{'value':1.01})
    finally:await r.close()


@pytest.mark.parametrize('legacy',[False,True])
async def test_firmware_capability_controls_sender_and_legacy_fallback(legacy):
    r=Runtime();r.register('a');await r.start()
    try:
        await r.action('a','connect',{'mode':'mock'})
        r.mock.advertise_pwm=not legacy
        r.mock.max_pwm=64 if legacy else 255
        await wait_for(r.direct_enable_ready)
        if legacy:
            assert r.pwm_limit_max()<.26
            with pytest.raises(ValueError):await r.action('a','speed_limit',{'value':.5})
            r.control.speed_limit=.5  # Even a bad caller cannot bypass send-side validation.
            with pytest.raises(ValueError,match='PWM'):
                r.link.send('DRIVE',128,0)
        else:
            await r.action('a','speed_limit',{'value':1})
            await r.action('a','input',{'seq':0});await r.action('a','enable',{})
            for seq in range(1,11):
                await r.action('a','input',{'seq':seq,'throttle':1,'deadman':True});await asyncio.sleep(.04)
            assert r.mock.throttle==255 and not r.link.fault
    finally:await r.close()


async def test_ros_loopback_keeps_pinned_quarter_power_ceiling():
    r=Runtime();r.register('a')
    try:
        await r.action('a','connect',{'mode':'oc-mock'})
        assert r.pwm_limit_max()==.25
        with pytest.raises(ValueError):await r.action('a','speed_limit',{'value':.5})
    finally:await r.close()
