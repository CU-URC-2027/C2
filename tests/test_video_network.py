import pytest
import time
from types import SimpleNamespace
from pathlib import Path
from c2_web.video_receiver import VideoReceiver
from c2_web.priorities import VideoPriorities
from c2_web.runtime import Runtime


def test_remote_media_bind_is_explicit_and_peer_filtered():
    with pytest.raises(ValueError):VideoReceiver(host='0.0.0.0')
    with pytest.raises(ValueError):VideoReceiver(host='10.211.55.6')
    r=VideoReceiver(host='10.211.55.6',allowed_peers=['10.211.55.7'])
    assert r.host=='10.211.55.6' and r.allowed_peers=={'10.211.55.7'}
    assert VideoReceiver().allowed_peers=={'127.0.0.1'}


async def test_video_ros_budget_action_never_renews_input_or_enables_chassis():
    class Video(VideoPriorities):
        def configure_budget(self,bps,share):self.budget=bps,share
    video=Video(enabled=False);r=Runtime(video_priorities=video);r.register('a')
    try:
        before=r.last_input
        await r.action('a','video_link_budget',{'available_bps':0,'video_share_percent':0})
        assert video.budget==(0,0) and r.last_input==before
        assert not r.control.armed and not r.link.connected
    finally:await r.close()


def test_retired_rover_health_cannot_replace_a_restarted_rover(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'prototypes/video_pipeline'))
    from c2_web.video_ros import ROSVideoPriorities
    r=ROSVideoPriorities();r.sequence=1;r.sent[1]=(time.monotonic(),1)
    def message(session,seq):
        values=dict(schema_version=1,source_session=session,sequence=seq,
            priority_source_session=r.session,priority_sequence=1,priority_revision=1)
        return SimpleNamespace(**values,get_fields_and_field_types=lambda:values)
    r.receive_health(message('old',1));r.receive_health(message('new',1))
    r.receive_health(message('old',2))
    assert r.rover_session=='new' and r.remote_health['source_session']=='new'
