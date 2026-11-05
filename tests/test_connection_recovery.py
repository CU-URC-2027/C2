import asyncio
import json
import math
import pytest
from c2_web.runtime import Runtime
from c2_web.legacy import RoverLink


class Socket:
    def __init__(self): self.received=[]; self.sent=[]; self.closed=False
    def sendto(self,data,address): self.sent.append(data.decode().strip().split(',')); return len(data)
    def recvfrom(self,size):
        if not self.received: raise BlockingIOError
        return self.received.pop(0)
    def close(self): self.closed=True


def link_fixture():
    link=RoverLink();link.sock=Socket();link.target=('127.0.0.1',4210);link.session='a'*16
    link.started=100;link.send('HELLO',now=100)
    feedback(link,1,1,100.01)
    return link


def feedback(link,seq,state_id,now,enabled=False,stopped=False,epoch=3,**extra):
    row=dict(v=1,type='state',fw='c2-guard-v1',session=link.session,watchdog_ms=250,
             seq=seq,state_id=state_id,epoch=epoch,enabled=enabled,stopped=stopped,
             throttle=0,steering=0,reason='test',encoders=None,**extra)
    link.sock.received.append((json.dumps(row).encode(),link.target));link.receive(now)


def output(): return dict(enabled=False,stop_latched=False,legacy_drive_preview='0,0\n')


@pytest.mark.parametrize('old_ping_age',[.20,.25,.30])
def test_arm_uses_its_own_deadline_not_the_pre_arm_ping_age(old_ping_age):
    link=link_fixture()
    link.send('PING',now=100.02)
    feedback(link,link.seq,2,100.03)
    requested=100.02+old_ping_age
    link.request_enable(requested)
    arm=link.pending_arm[0]
    driving=output()|dict(enabled=True,legacy_drive_preview='64,0\n')
    link.tick(driving,requested+.156)
    assert not link.fault and link.phase(requested+.156)=='enabling'
    assert not any(p[4]=='DRIVE' for p in link.sock.sent)
    assert link.sent[2]==100.02  # Keep the real send timestamp.
    feedback(link,arm,3,requested+.21,enabled=True)
    link.tick(driving,requested+.21)
    assert link.pending_arm is None and not link.fault
    assert link.sock.sent[-1][4]=='DRIVE'


@pytest.mark.parametrize('late_ack',[False,True])
def test_arm_timeout_cannot_be_hidden_by_a_late_enabled_ack_or_recent_ping(late_ack):
    link=link_fixture();link.request_enable(100.02)
    arm=link.pending_arm[0]
    link.tick(output()|dict(enabled=True),100.15)
    if late_ack: feedback(link,arm,2,100.28,enabled=True)
    else: feedback(link,link.seq,2,100.27)  # Fresh PING, but never enabled.
    link.tick(output()|dict(enabled=True),100.28)
    assert 'enable within 250 ms' in link.fault
    assert link.sock.sent[-1][4]=='STOP'
    assert not any(p[4]=='DRIVE' for p in link.sock.sent)


def test_wrong_epoch_enabled_ack_cannot_confirm_arm():
    link=link_fixture();link.request_enable(100.02)
    feedback(link,link.seq,2,100.04,enabled=True,epoch=4)
    assert link.pending_arm
    link.tick(output()|dict(enabled=True),100.28)
    assert link.fault and not any(p[4]=='DRIVE' for p in link.sock.sent)


async def test_enable_display_log_and_model_wait_for_actual_rover_confirmation():
    now=[100.04]
    r=Runtime(clock=lambda:now[0]);r.register('a');r.link=link_fixture()
    r.link.send('PING',now=100.02);feedback(r.link,r.link.seq,2,100.03)
    await r.action('a','input',dict(seq=0))
    await r.action('a','enable',{})
    arm=r.link.pending_arm[0]
    await r.action('a','input',dict(seq=1,throttle=.8,deadman=True))
    r.tick()
    for out in (r.state()['control'],r.records[-1]['control'],r.log_context()['control']):
        assert not out['enabled'] and out['enable_requested']
        assert out['left']==out['right']==0
        assert out['reason']=='Enable requested; waiting for rover confirmation'
    assert not any('hold drive' in event['text'].lower() for event in r.events)
    row=dict(r.link.state,seq=arm,state_id=3,enabled=True)
    r.link.sock.received.append((json.dumps(row).encode(),r.link.target))
    now[0]=100.09;r.tick()
    assert r.state()['control']['enabled'] and r.records[-1]['control']['left']>0
    assert any('Rover confirmed enabled' in event['text'] for event in r.events)
    await r.close()


def test_fault_heartbeat_observes_confirmed_stop_without_clearing_fault_or_enabling():
    link=link_fixture();link.request_enable(100.02)
    link.fault='latched test fault';link.tick(output(),100.04)
    stop=link.pending_disarm['sequence']
    feedback(link,stop,2,100.10,stopped=True)
    assert link.idle_confirmed()
    for i in range(1,15):
        now=100.10+i*.05
        link.tick(output(),now)
        feedback(link,link.seq,i+2,now+.001,stopped=True)
    assert link.fault=='latched test fault'
    assert link.diagnostics(now)['stop_confirmed']
    assert link.diagnostics(now)['acknowledged_command_age_ms']<151
    assert all(p[4]=='PING' for p in link.sock.sent if int(p[2])>stop)


def test_compact_feedback_preserves_separately_dated_firmware_diagnostics():
    link=link_fixture()
    feedback(link,1,2,100.03,diagnostics={'udp_send_ms':80},build='test-v2')
    feedback(link,1,3,100.08)
    d=link.diagnostics(100.1)
    assert 'diagnostics' not in d['last_mcu_state']
    assert d['mcu_detail_state']['diagnostics']['udp_send_ms']==80
    assert d['mcu_detail_age_ms']==70


def test_old_disabled_feedback_cannot_confirm_a_later_disarm_or_cancel_its_barrier():
    link=link_fixture()
    link.request_enable(100.02)
    link.disable(now=100.03)
    barrier=link.pending_disarm['sequence']
    feedback(link,1,2,100.04)  # Disabled before ARM/DISARM: not shutdown evidence.
    assert link.disarm_pending and not link.idle_confirmed()
    with pytest.raises(ValueError,match='disabled'):
        link.request_enable(100.05)
    for i in range(5): link.disable(now=100.05+i*.02)
    assert link.pending_disarm['sequence']==barrier
    assert len([p for p in link.sock.sent if p[4]=='DISARM'])==1
    feedback(link,barrier,3,100.15)
    assert not link.disarm_pending and link.idle_confirmed()


def test_retries_are_bounded_keep_first_deadline_and_late_ack_cannot_clear_fault():
    link=link_fixture();link.request_enable(100.02);link.disable(now=100.03)
    barrier=link.pending_disarm['sequence']
    for i in range(1,7):link.tick(output(),100.03+i*.05)
    assert link.pending_disarm['started']==100.03
    assert link.pending_disarm['sequence']==barrier and link.pending_disarm['retries']<=2
    link.tick(output(),100.39)
    assert link.fault and '350 ms' in link.fault
    assert link.pending_disarm['started']==100.03
    feedback(link,link.seq,3,100.42,stopped=True)
    assert link.fault and link.disarm_pending


def test_stop_escalation_never_downgrades_to_disarm_or_accepts_unlatched_feedback():
    link=link_fixture();link.request_enable(100.02);link.disable(now=100.03)
    link.disable(latch=True,now=100.04)
    seq=link.pending_disarm['sequence'];link.disable(now=100.05)
    assert link.pending_disarm['latch'] and link.pending_disarm['started']==100.03
    feedback(link,seq,3,100.06)
    assert link.disarm_pending
    feedback(link,seq,4,100.07,stopped=True)
    assert not link.disarm_pending


def test_confirmed_idle_disarms_generate_no_transition_traffic_even_if_feedback_degrades():
    link=link_fixture()
    for i in range(40):
        link.disable(now=100.02+i*.02)
        link.tick(output(),100.02+i*.02)
    assert not any(p[4] in ('DISARM','STOP','ARM','DRIVE') for p in link.sock.sent)
    assert not link.fault and not link.ready(100.85)


def test_reset_readiness_tracks_remote_stop_and_rejects_pending_arm():
    from types import SimpleNamespace
    r=Runtime(clock=lambda:100.02);r.register('a');r.link=link_fixture()
    r.link.state['stopped']=True
    assert r.connection_status(100.02)['can_reset']
    r.link.pending_arm=(2,100.02)
    assert not r.connection_status(100.02)['can_reset']
    r.link.sock.close();r.link.sock=None
    r.onboard=SimpleNamespace(state=lambda:dict(fresh=True,owned=True,fault=None,
        state=dict(mcu_ready=True,mcu_enabled=False,supervisor_enabled=False,
                   mcu_stopped=False,stop_latched=True)))
    assert r.connection_status(100.02)['can_reset']


async def wait_for(predicate):
    async with asyncio.timeout(3):
        while not predicate():await asyncio.sleep(.02)


async def test_missing_gamepad_slow_transition_receiver_does_not_flood_or_reenable():
    r=Runtime();r.register('a');await r.start()
    try:
        await r.action('a','connect',{'mode':'mock'})
        await wait_for(r.direct_enable_ready)
        r.mock.transition_delay=.08
        await r.action('a','input_mode',{'mode':'gamepad'})
        for seq in range(40):
            await r.action('a','input',{'seq':seq,'gamepad_connected':False})
            await asyncio.sleep(.05)
        assert not r.link.fault and not r.control.armed and not r.mock.enabled
        assert r.input_seq==39 and r.last_input==-math.inf
        assert sum(op=='DISARM' for op,_,_ in r.mock.received)<=1
        await r.action('a','input',{'seq':40,'gamepad_connected':True})
        assert not r.control.armed
        await r.action('a','enable',{})
        for seq in range(41,49):
            await r.action('a','input',{'seq':seq,'gamepad_connected':True,'throttle':.5,'deadman':True})
            await asyncio.sleep(.05)
        assert r.mock.throttle>0
        for seq in range(49,65):
            await r.action('a','input',{'seq':seq,'gamepad_connected':False})
            await asyncio.sleep(.05)
        assert not r.mock.enabled and r.mock.throttle==0 and not r.link.fault
        assert sum(op=='DISARM' for op,_,_ in r.mock.received)<=2
    finally:await r.close()


async def test_repeated_page_disarms_with_delayed_feedback_preserve_link_and_no_auto_arm():
    r=Runtime();r.register('a');await r.start()
    try:
        await r.action('a','connect',{'mode':'mock'})
        await wait_for(r.direct_enable_ready)
        r.mock.reply_delay=.15
        for seq in range(35):
            await r.action('a','disarm',{'reason':'page_change'})
            await r.action('a','input',{'seq':seq})
            await asyncio.sleep(.05)
        assert not r.link.fault and not r.mock.enabled and not r.control.armed
        assert not any(op=='DISARM' for op,_,_ in r.mock.received)
    finally:await r.close()


async def test_fault_confirmed_stop_reconnect_reset_enable_needs_no_extra_stop_press():
    from c2_web.legacy import MockRover
    rover=MockRover();r=Runtime();r.register('a');await r.start()
    target=dict(mode='udp',host='127.0.0.1',port=rover.port)
    try:
        await r.action('a','connect',target)
        await wait_for(r.direct_enable_ready)
        await r.action('a','input',dict(seq=0))
        await r.action('a','enable',{})
        await wait_for(lambda:not r.link.pending_arm)
        r.link.fault='Injected transport fault'
        await wait_for(lambda:r.link.idle_confirmed() and r.link.state['stopped'])
        assert r.link.fault and not r.control.armed
        # Reconnect is deliberate; MCU STOP survives the new session/owner lease.
        await r.action('a','connect',target)
        await wait_for(lambda:r.connection_status(r.clock())['can_reset'])
        assert rover.stopped and not r.control.armed
        await r.action('a','reset_stop',{})
        await wait_for(r.direct_enable_ready)
        assert not rover.stopped and not rover.enabled and not r.control.armed
        await r.action('a','input',dict(seq=1))
        await r.action('a','enable',{})
        for seq in range(2,8):
            await r.action('a','input',dict(seq=seq,throttle=.5,deadman=True))
            await asyncio.sleep(.05)
        assert rover.enabled and rover.throttle>0 and not r.link.fault
        assert not any(e['text'].startswith('STOP latched.') for e in r.events)
    finally:
        await r.close();rover.close()
