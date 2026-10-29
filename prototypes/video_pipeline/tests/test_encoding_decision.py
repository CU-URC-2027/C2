from dataclasses import replace
import random

import pytest

from encoding_decision import DecisionConfig, DecisionInputs, EncodingDecision, SigmaLimits, StreamCapability

STREAMS = tuple(StreamCapability(f'cam-{i:02}',f'Camera {i:02}',3840 if i==1 else 1920,
                                2160 if i==1 else 1080) for i in range(1,6))
IDS = tuple(s.id for s in STREAMS)


class Clock:
    now = 0.0
    def __call__(self):return self.now


def inputs(bps=10_000_000, **changes):
    return replace(DecisionInputs(IDS,5,bps,True,True,False,False,'session',1,1,1),**changes)


def core(clock=None):
    # Direct budget for threshold tests. Production defaults remain 70% × 80%.
    return EncodingDecision(STREAMS,DecisionConfig(100,0),clock=clock or Clock())


def selected(plan):return [r for r in plan['cameras'] if r['selected']]


def test_video_share_headroom_and_contract_are_decisions_only():
    planner=EncodingDecision(STREAMS)
    plan=planner.evaluate(inputs(), IDS)
    assert plan['budget']['video_allowance_bps']==7_000_000
    assert plan['budget']['encoder_budget_bps']==5_600_000
    assert plan['budget']['headroom_bps']==1_400_000
    assert not plan['encoder_connected'] and not plan['encoding_policy']['applied']
    assert plan['mode']=='decision_only' and plan['hardware']['measured_on_sigma'] is False
    assert len(plan['cameras'])==5


def test_low_bandwidth_protects_only_actual_highest_priority():
    planner=core()
    plan=planner.evaluate(inputs(280_000,ordered_stream_ids=IDS[::-1]),IDS)
    assert [(r['id'],r['profile_id'],r['target_bitrate_bps']) for r in selected(plan)]==[('cam-05','360p15',280_000)]
    assert all(r['reason_code']=='primary_protected' for r in plan['cameras'][1:])


def test_below_minimum_produces_no_feasible_video():
    plan=core().evaluate(inputs(149_999),IDS)
    assert selected(plan)==[] and plan['state']=='no_video'
    assert plan['budget']['planned_bitrate_bps']==0


def test_primary_working_floor_precedes_overviews():
    plan=core().evaluate(inputs(1_600_000),IDS)
    assert len(selected(plan))==1 and selected(plan)[0]['profile_id']=='720p30'
    plan=core().evaluate(inputs(3_000_000),IDS)
    assert [r['target_bitrate_bps'] for r in selected(plan)]==[1_800_000,300_000,300_000,300_000,300_000]


def test_omitted_cameras_never_reenabled_even_with_surplus():
    plan=core().evaluate(inputs(100_000_000,enabled_count=1),IDS)
    assert len(selected(plan))==1
    assert all(r['reason_code']=='operator_omitted' for r in plan['cameras'][1:])
    plan=core().evaluate(inputs(100_000_000,enabled_count=0),IDS)
    assert not selected(plan) and all(r['reason_code']=='operator_omitted' for r in plan['cameras'])


def test_zero_bandwidth_and_zero_video_share_remove_plan_immediately():
    planner=core()
    planner.evaluate(inputs(),IDS)
    assert not selected(planner.evaluate(inputs(0),IDS))
    planner.configure(0)
    assert not selected(planner.evaluate(inputs(),IDS))


def test_sigma_pixel_cap_allows_4k_only_when_other_views_leave_room():
    planner=core()
    only=planner.evaluate(inputs(30_000_000,enabled_count=1),IDS)
    assert selected(only)[0]['profile_id']=='2160p30'
    assert only['hardware']['planned_pixels_per_second']==248_832_000
    all_views=core().evaluate(inputs(100_000_000),IDS)
    assert len(selected(all_views))==5
    assert all_views['hardware']['planned_pixels_per_second']<=248_832_000
    assert selected(all_views)[0]['width']<3840
    assert 'Sigma workload cap' in selected(all_views)[0]['reason']


def test_never_upscale_and_explain_native_limit():
    plan=core().evaluate(inputs(50_000_000,ordered_stream_ids=IDS[1:]+IDS[:1],enabled_count=1),IDS)
    camera=selected(plan)[0]
    assert camera['id']=='cam-02' and camera['profile_id']=='1080p30'
    assert 'source resolution/fps ceiling' in camera['reason']


def test_paused_or_missing_sources_are_not_selected_and_primary_fails_over():
    planner=core()
    plan=planner.evaluate(inputs(3_000_000),{'cam-03'})
    assert selected(plan)[0]['id']=='cam-03'
    assert plan['cameras'][0]['reason_code']=='source_unavailable'
    assert not selected(planner.evaluate(inputs(),set()))


def test_bandwidth_stale_or_missing_cannot_create_a_budget():
    planner=core()
    planner.evaluate(inputs(),IDS)
    plan=planner.evaluate(inputs(bandwidth_stale=True),IDS)
    assert not selected(plan) and plan['budget']['encoder_budget_bps']==0
    plan=planner.evaluate(inputs(available_bandwidth_bps=None,bandwidth_received=False),IDS)
    assert plan['state']=='waiting_inputs' and not selected(plan)


def test_no_invented_priority_list_before_c2_receives_input():
    plan=core().evaluate(inputs(ordered_stream_ids=(),enabled_count=0,priorities_received=False),IDS)
    assert plan['state']=='waiting_inputs' and not selected(plan)
    assert all(r['reason_code']=='waiting_inputs' for r in plan['cameras'])


def test_upgrade_needs_four_seconds_with_spare_capacity_and_decrease_is_immediate():
    clock=Clock();planner=core(clock)
    first=planner.evaluate(inputs(600_000),IDS)
    assert selected(first)[0]['profile_id']=='360p30'
    pending=planner.evaluate(inputs(5_000_000),IDS)
    assert pending['state']=='holding_upgrade'
    assert selected(pending)[0]['profile_id']=='360p30'
    clock.now=3.99
    assert selected(planner.evaluate(inputs(5_000_000),IDS))[0]['profile_id']=='360p30'
    clock.now=4
    assert selected(planner.evaluate(inputs(5_000_000),IDS))[0]['profile_id']=='720p30'
    down=planner.evaluate(inputs(200_000),IDS)
    assert len(selected(down))==1 and selected(down)[0]['profile_id']=='180p15'
    assert down['budget']['planned_bitrate_bps']==200_000


def test_upgrade_headroom_and_unstable_budget_restart_the_hold():
    clock=Clock();planner=core(clock)
    planner.evaluate(inputs(200_000),IDS)
    assert not planner.evaluate(inputs(260_000),IDS)['stability']['upgrade_pending']
    assert planner.evaluate(inputs(320_000),IDS)['stability']['upgrade_pending']
    clock.now=3
    planner.evaluate(inputs(200_000),IDS)
    clock.now=5
    assert planner.evaluate(inputs(320_000),IDS)['stability']['upgrade_remaining_s']==4
    clock.now=9
    assert selected(planner.evaluate(inputs(320_000),IDS))[0]['profile_id']=='360p15'


def test_outage_recovery_resumes_emergency_then_waits_for_upgrades():
    clock=Clock();planner=core(clock)
    planner.evaluate(inputs(),IDS)
    planner.evaluate(inputs(0),IDS)
    recovered=planner.evaluate(inputs(),IDS)
    assert len(selected(recovered))==1 and selected(recovered)[0]['profile_id']=='180p15'
    assert recovered['stability']['upgrade_pending']
    clock.now=4
    assert len(selected(planner.evaluate(inputs(),IDS)))>1


def test_stale_priorities_retain_order_without_automatic_profile_or_source_additions():
    clock=Clock();planner=core(clock)
    first=planner.evaluate(inputs(600_000),{'cam-01'})
    stale=planner.evaluate(inputs(50_000_000,priorities_stale=True),IDS)
    clock.now=100
    stale=planner.evaluate(inputs(50_000_000,priorities_stale=True),IDS)
    assert [(r['id'],r['profile_id']) for r in selected(stale)]==[(r['id'],r['profile_id']) for r in selected(first)]
    assert stale['state']=='degraded'


def test_explicit_priority_change_takes_effect_without_upgrade_wait():
    planner=core()
    planner.evaluate(inputs(200_000),IDS)
    plan=planner.evaluate(inputs(200_000,ordered_stream_ids=IDS[::-1],priority_revision=2),IDS)
    assert selected(plan)[0]['id']=='cam-05'


def test_heartbeats_do_not_change_plan_revision():
    planner=core()
    first=planner.evaluate(inputs(),IDS)
    second=planner.evaluate(inputs(priority_sequence=2,bandwidth_sequence=9),IDS)
    assert first['plan_revision']==second['plan_revision']
    assert second['evaluation_sequence']==first['evaluation_sequence']+1


@pytest.mark.parametrize('value',[True,-1,101,float('nan'),float('inf'),'70',None])
def test_invalid_video_share_does_not_replace_configuration(value):
    planner=core()
    with pytest.raises(ValueError):planner.configure(value)
    assert planner.config.video_share_percent==100


def test_invalid_received_snapshot_is_rejected():
    with pytest.raises(ValueError):core().evaluate(inputs(ordered_stream_ids=(IDS[0],)*5),IDS)
    with pytest.raises(ValueError):core().evaluate(inputs(True),IDS)


def test_budget_source_omission_and_hardware_invariants_across_combinations():
    rng=random.Random(20261028)
    for _ in range(500):
        order=tuple(rng.sample(IDS,5));count=rng.randrange(6);budget=rng.randrange(100_000_001)
        available=set(rng.sample(IDS,rng.randrange(6)))
        plan=EncodingDecision(STREAMS).evaluate(inputs(budget,ordered_stream_ids=order,enabled_count=count),available)
        picked=selected(plan)
        assert sum(r['target_bitrate_bps'] for r in plan['cameras'])==plan['budget']['planned_bitrate_bps']<=plan['budget']['encoder_budget_bps']
        assert sum(r['pixels_per_second'] for r in picked)<=SigmaLimits().max_pixels_per_second
        assert len(picked)<=5
        for r in picked:
            assert r['id'] in order[:count] and r['id'] in available
            assert r['width']<=r['source_width'] and r['height']<=r['source_height'] and r['fps']<=r['source_fps']
            assert r['profile_minimum_bps']<=r['target_bitrate_bps']<=r['profile_maximum_bps']
