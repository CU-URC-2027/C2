import asyncio
import json
import time
import pytest
from c2_web.runtime import Runtime
from c2_web.rover_discovery import RoverDiscovery,RoverProfiles
from c2_web.legacy import MockRover
from discovery_wire import query,parse_query,parse_reply


async def wait_for(predicate):
    async with asyncio.timeout(3):
        while not predicate():await asyncio.sleep(.02)


def test_discovery_protocol_rejects_wrong_nonce_oversize_and_invalid_identity():
    nonce='a'*16
    assert parse_query(query(nonce))==nonce
    assert parse_query(b'C2DISC1,aaaaaaaaaaaaaaaa,ARM') is None
    valid=dict(v=1,type='c2_discovery',nonce=nonce,device_id='rover-test-01',control_protocol='C2V1',
               control_port=4210,watchdog_ms=250,busy=False,enabled=False,stopped=False)
    assert parse_reply(json.dumps(valid).encode(),nonce)['device_id']=='rover-test-01'
    for change in ({'nonce':'b'*16},{'device_id':'<script>'},{'control_port':True},{'watchdog_ms':999},
                   {'busy':False,'enabled':True},{'busy':'no'}):
        with pytest.raises(ValueError):parse_reply(json.dumps(valid|change).encode(),nonce)
    with pytest.raises(ValueError):parse_reply(b'x'*2049,nonce)


async def test_read_only_discovery_finds_mock_without_claiming_session_or_watchdog():
    mock=MockRover();discovery=RoverDiscovery()
    try:
        discovery.start('127.0.0.1',mock.port)
        await discovery.task
        result=discovery.state()
        assert len(result['candidates'])==1 and not result['scanning']
        assert result['candidates'][0]['device_id']==mock.device_id
        assert not mock.session and mock.last_owner==0 and mock.last_drive==0 and mock.received==[]
        assert not mock.enabled and not mock.stopped
    finally:await discovery.close();mock.close()


async def test_busy_rover_cannot_be_selected_for_takeover():
    mock=MockRover();r=Runtime();r.register('a')
    try:
        mock.session='b'*16;mock.last_owner=time.monotonic()
        await r.action('a','find_rovers',{'host':'127.0.0.1','port':mock.port})
        await r.discovery.task
        row=r.discovery.candidates[0]
        assert row['busy']
        with pytest.raises(ValueError,match='active owner'):
            await r.action('a','connect_discovered',{'id':f"{row['device_id']}@{row['host']}:{row['control_port']}"})
        assert not r.link.connected and mock.received==[]
    finally:await r.close();mock.close()


async def test_saved_identity_connects_disarmed_and_profiles_persist_without_autoconnect():
    mock=MockRover();r=Runtime();r.register('a');await r.start()
    try:
        await r.action('a','connect',{'mode':'udp','host':'127.0.0.1','port':mock.port})
        await wait_for(r.direct_enable_ready)
        await r.action('a','save_rover',{'name':'My test rover'})
        await r.profile_task
        profiles=RoverProfiles()
        assert len(profiles.profiles)==1 and profiles.profiles[0]['device_id']==mock.device_id
        r.disconnect()
        restored=Runtime()
        assert restored.profiles.profiles==profiles.profiles and not restored.link.connected
        await restored.close()
        await r.action('a','connect_saved',{'id':mock.device_id})
        await wait_for(lambda:r.link.ready(r.clock()))
        assert r.link.expected_device_id==mock.device_id and not r.control.armed and not mock.enabled
        assert mock.stopped  # Closing the old session STOPs; saved reconnect never resets it.
        assert r.state()['connection_status']['can_reset']
    finally:await r.close();mock.close()


async def test_wrong_saved_identity_never_sends_arm_or_stop_to_unverified_endpoint():
    mock=MockRover();r=Runtime();r.register('a');await r.start()
    try:
        r.profiles.save({'name':'Wrong saved identity','host':'127.0.0.1','port':mock.port,'device_id':'rover-other-01'})
        await r.action('a','connect_saved',{'id':'rover-other-01'})
        await wait_for(lambda:r.link.fault)
        assert 'identity' in r.link.fault and not r.link.connected
        await r.action('a','input',{'seq':0})
        with pytest.raises(ValueError,match='identity'):
            await r.action('a','enable',{})
        assert not any(op in ('ARM','DRIVE','STOP') for op,_,_ in mock.received)
    finally:await r.close();mock.close()


async def test_discovery_is_explicit_owner_only_and_blocked_while_enabled():
    r=Runtime();r.register('a');r.register('viewer')
    try:
        assert r.discovery.task is None
        with pytest.raises(ValueError,match='view-only'):
            await r.action('viewer','find_rovers',{})
        await r.action('a','input',{'seq':0});await r.action('a','enable',{})
        with pytest.raises(ValueError,match='Disarm'):
            await r.action('a','find_rovers',{})
        assert r.discovery.task is None
        await r.action('a','disarm',{})
        with pytest.raises(ValueError):await r.action('a','find_rovers',{'host':'8.8.8.8'})
        with pytest.raises(ValueError):await r.action('a','find_rovers',{'host':'224.0.0.1'})
    finally:await r.close()


def test_corrupt_profile_settings_are_visible_and_never_start_networking(monkeypatch,tmp_path):
    p=tmp_path/'corrupt.json';p.write_text('{invalid')
    monkeypatch.setenv('C2_PROFILE_PATH',str(p))
    r=Runtime()
    assert r.profiles.error and r.profiles.profiles==[] and not r.link.connected
    assert p.read_text()=='{invalid'


def test_discovery_runs_with_the_production_uvicorn_event_loop():
    uvloop=pytest.importorskip('uvloop')
    async def scenario():
        mock=MockRover();discovery=RoverDiscovery()
        try:
            discovery.start('127.0.0.1',mock.port)
            await discovery.task
            assert len(discovery.candidates)==1 and not discovery.error
        finally:await discovery.close();mock.close()
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        runner.run(scenario())
