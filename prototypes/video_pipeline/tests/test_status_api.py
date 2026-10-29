from fastapi.testclient import TestClient
from app import create_app
from sources import SPECS
from status_runtime import StatusRuntime


class EmptyBank:
    def __init__(self):
        self.sources = {s.id: type('Source', (), {'running': False})() for s in SPECS}
    async def start(self):pass
    async def close(self):pass
    def state(self):return {'sources': []}


def test_lab_observes_external_c2_and_cannot_edit_priorities():
    bank=EmptyBank()
    app=create_app(bank=bank, status_runtime=StatusRuntime(bank.sources.keys(), ingress_port=0))
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/state').json()['architecture']['c2']['external']
        assert not client.get('/api/status-manager').json()['priorities_received']
        assert client.post('/api/c2/priorities',json={'ordered_stream_ids':list(bank.sources),'enabled_count':1}).status_code == 404
        assert client.post('/api/link',json={'bandwidth_bps':0,'latency_ms':40}).status_code == 200
        assert client.get('/api/status-manager').json()['available_bandwidth_bps'] == 0
        assert client.post('/api/link',json={'bandwidth_bps':True}).status_code == 400
        assert client.post('/api/link',json={'bandwidth_bps':1000},headers={'Origin':'https://elsewhere.example'}).status_code == 403


def test_encoding_decision_api_is_plan_only_and_validates_allocation():
    bank=EmptyBank()
    app=create_app(bank=bank,status_runtime=StatusRuntime(bank.sources.keys(),ingress_port=0))
    with TestClient(app) as client:
        initial=client.get('/api/encoding-decision').json()
        assert initial['mode']=='decision_only' and not initial['encoder_connected']
        assert initial['hardware']['max_pixels_per_second']==248_832_000
        assert initial['configuration']['video_share_percent']==70
        for invalid in (True,-1,101,'50',None):
            assert client.post('/api/encoding-decision/config',json={'video_share_percent':invalid}).status_code==400
        assert client.post('/api/encoding-decision/config',json={'video_share_percent':50,'max_streams':99}).status_code==400
        assert client.post('/api/encoding-decision/config',json={'video_share_percent':50},headers={'Origin':'https://elsewhere.example'}).status_code==403
        changed=client.post('/api/encoding-decision/config',json={'video_share_percent':50}).json()
        assert changed['configuration']['video_share_percent']==50
        assert client.get('/api/state').json()['architecture']['encoding_decision']['configuration']['video_share_percent']==50
        assert not any(r['selected'] for r in changed['cameras'])


def test_encoder_api_defaults_off_and_does_not_probe_hardware_for_observation():
    bank=EmptyBank();app=create_app(bank=bank,status_runtime=StatusRuntime(bank.sources.keys(),ingress_port=0))
    def unexpected():raise AssertionError('Observation must not probe or start hardware')
    app.state.encoder_runtime.native_prepare=unexpected
    with TestClient(app) as client:
        state=client.get('/api/encoder').json()
        assert not state['enabled'] and state['active_sessions']==0 and state['backend']=='not probed'
        assert not state['transmission_connected']
        assert client.post('/api/encoder/previews/test',json={'visible':True}).json()=={'enabled':False}
        for bad in (True,{}, {'enabled':1},{'enabled':False,'extra':0}):
            assert client.post('/api/encoder/enabled',json=bad).status_code==400
        assert client.post('/api/encoder/enabled',json={'enabled':False},headers={'Origin':'https://elsewhere.example'}).status_code==403
        assert client.post('/api/encoder/previews/test',json={'visible':1}).status_code==400
        assert client.get('/api/encoder/preview/cam-01.jpg').status_code==404
        assert client.get('/api/encoder/capture/unknown').status_code==404
        assert client.get('/api/encoder/capture/cam-01').status_code==409
