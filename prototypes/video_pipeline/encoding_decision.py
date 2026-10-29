"""Decision-only video planner; standard library, no pixels/encoder/transport.

Sigma throughput and H.264 quality floors are provisional engineering limits.
The core consumes a StatusManager snapshot; a ROS adapter can supply the same
immutable DecisionInputs. A plan is a request, never evidence of encoding.
"""
from dataclasses import asdict, dataclass
import math
import time


@dataclass(frozen=True)
class Profile:
    id: str
    width: int
    height: int
    fps: int
    minimum_bps: int
    target_bps: int
    maximum_bps: int

    @property
    def pixels_per_second(self):
        return self.width*self.height*self.fps


PROFILES = (
    Profile('180p15', 320, 180, 15, 150_000, 200_000, 300_000),
    Profile('360p15', 640, 360, 15, 250_000, 300_000, 500_000),
    Profile('360p30', 640, 360, 30, 400_000, 600_000, 900_000),
    Profile('540p30', 960, 540, 30, 800_000, 1_100_000, 1_500_000),
    Profile('720p30', 1280, 720, 30, 1_500_000, 1_800_000, 3_000_000),
    Profile('1080p30', 1920, 1080, 30, 3_000_000, 4_000_000, 6_000_000),
    Profile('2160p30', 3840, 2160, 30, 10_000_000, 15_000_000, 20_000_000),
)


@dataclass(frozen=True)
class StreamCapability:
    id: str
    name: str
    width: int
    height: int
    fps: int = 30


@dataclass(frozen=True)
class SigmaLimits:
    name: str = 'LattePanda Sigma · provisional'
    codec: str = 'h264'
    pixel_format: str = 'nv12'
    max_streams: int = 5
    max_width: int = 3840
    max_height: int = 2160
    max_fps: int = 30
    max_pixels_per_second: int = 248_832_000
    measured_on_sigma: bool = False


@dataclass(frozen=True)
class DecisionConfig:
    video_share_percent: float = 70.0
    headroom_percent: int = 20
    upgrade_delay_s: float = 4.0
    upgrade_margin_percent: int = 25

    def validate(self):
        if (type(self.video_share_percent) not in (int, float)
            or not math.isfinite(self.video_share_percent) or not 0 <= self.video_share_percent <= 100):
            raise ValueError('Video share must be a finite percentage from 0 to 100')
        if not 0 <= self.headroom_percent < 100 or self.upgrade_delay_s < 0 or self.upgrade_margin_percent < 0:
            raise ValueError('Invalid decision policy')


@dataclass(frozen=True)
class DecisionInputs:
    ordered_stream_ids: tuple[str, ...]
    enabled_count: int
    available_bandwidth_bps: int | None
    priorities_received: bool
    bandwidth_received: bool
    priorities_stale: bool
    bandwidth_stale: bool
    priority_session: str | None = None
    priority_revision: int | None = None
    priority_sequence: int | None = None
    bandwidth_sequence: int | None = None

    @classmethod
    def from_snapshot(cls, s):
        return cls(tuple(s['ordered_stream_ids']), s['enabled_count'], s['available_bandwidth_bps'],
                   s['priorities_received'], s['bandwidth_received'], s['priorities_stale'], s['bandwidth_stale'],
                   s['priority_session'], s['priority_revision'], s['priority_sequence'], s['bandwidth_sequence'])


class EncodingDecision:
    def __init__(self, streams, config=DecisionConfig(), limits=SigmaLimits(), clock=time.monotonic):
        self.streams = {s.id: s for s in streams}
        if not self.streams:
            raise ValueError('At least one source capability is required')
        config.validate()
        self.config, self.limits, self.clock = config, limits, clock
        self.selection = {}
        self.context = self.pending = self.pending_since = None
        self.plan_revision = self.evaluation_sequence = 0
        self.fingerprint = None
        self.last = None

    def configure(self, video_share_percent):
        config = DecisionConfig(video_share_percent, self.config.headroom_percent,
                                self.config.upgrade_delay_s, self.config.upgrade_margin_percent)
        config.validate()
        self.config = config
        self.pending = self.pending_since = None

    def supported(self, id, profile):
        s, h = self.streams[id], self.limits
        return (profile.width <= min(s.width, h.max_width) and profile.height <= min(s.height, h.max_height)
                and profile.fps <= min(s.fps, h.max_fps))

    def workload(self, selection):
        return sum(PROFILES[i].pixels_per_second for i in selection.values())

    def floor(self, selection):
        return sum(PROFILES[i].minimum_bps for i in selection.values())

    def fits(self, selection, budget):
        return (self.floor(selection) <= budget and len(selection) <= self.limits.max_streams
                and self.workload(selection) <= self.limits.max_pixels_per_second)

    def fill(self, selection, budget):
        rates = {id: PROFILES[i].minimum_bps for id, i in selection.items()}
        remaining = budget-sum(rates.values())
        for attribute in ('target_bps', 'maximum_bps'):
            for id, index in selection.items():
                added = min(max(0, remaining), max(0, getattr(PROFILES[index], attribute)-rates[id]))
                rates[id] += added
                remaining -= added
        return rates

    def allocate(self, eligible, budget):
        """Protect primary to <=720p30, add overview views, then upgrade by rank."""
        if not eligible:
            return {}
        primary = eligible[0]
        baseline = [i for i, p in enumerate(PROFILES[:5]) if self.supported(primary, p)]
        affordable = [i for i in baseline if self.fits({primary: i}, budget)]
        if not affordable:
            return {}
        selection = {primary: affordable[-1]}
        if affordable[-1] == baseline[-1]:
            for id in eligible[1:]:
                overview = next((i for i in (1, 0) if self.supported(id, PROFILES[i])), None)
                if overview is not None and self.fits(dict(selection, **{id: overview}), budget):
                    selection[id] = overview
        rates = {id: PROFILES[i].minimum_bps for id, i in selection.items()}
        # Spend toward nominal targets before adding resolution/fps.
        for id, index in selection.items():
            rates[id] += min(budget-sum(rates.values()), PROFILES[index].target_bps-rates[id])
        for id in tuple(selection):
            for index in range(selection[id]+1, len(PROFILES)):
                p = PROFILES[index]
                if not self.supported(id, p):
                    continue
                proposed = dict(selection, **{id: index})
                cost = max(0, p.minimum_bps-rates[id])
                if self.fits(proposed, budget) and cost <= budget-sum(rates.values()):
                    selection[id] = index
                    rates[id] = max(rates[id], p.minimum_bps)
                    rates[id] += min(budget-sum(rates.values()), max(0, p.target_bps-rates[id]))
        return selection

    def evaluate(self, inputs, available_stream_ids):
        now = self.clock()
        self.evaluation_sequence += 1
        order = inputs.ordered_stream_ids
        if inputs.priorities_received and (len(order) != len(self.streams) or set(order) != set(self.streams)
            or type(inputs.enabled_count) is not int or not 0 <= inputs.enabled_count <= len(order)):
            raise ValueError('Invalid received camera priorities')
        bandwidth = inputs.available_bandwidth_bps
        if bandwidth is not None and (type(bandwidth) is not int or not 0 <= bandwidth <= 10_000_000_000):
            raise ValueError('Invalid bandwidth input')
        received = inputs.priorities_received and inputs.bandwidth_received
        valid_bandwidth = inputs.bandwidth_received and not inputs.bandwidth_stale and bandwidth is not None
        video_allowance = math.floor((bandwidth or 0)*self.config.video_share_percent/100) if valid_bandwidth else 0
        budget = video_allowance*(100-self.config.headroom_percent)//100
        enabled = order[:inputs.enabled_count] if inputs.priorities_received else ()
        available = set(available_stream_ids)
        eligible = [id for id in enabled if id in available]
        context = (order, inputs.enabled_count, inputs.priority_session, tuple(eligible))
        input_blocked = not received or not valid_bandwidth
        changed_context = context != self.context
        waiting = False
        remaining_s = 0.0
        if input_blocked or not budget or not eligible:
            self.selection = {}
            self.pending = self.pending_since = None
        elif self.context is None or changed_context:
            if inputs.priorities_stale:
                self.selection = {id:i for id,i in self.selection.items() if id in eligible}
                if not self.fits(self.selection, budget):
                    self.selection = {}
            else:
                self.selection = self.allocate(eligible, budget)
            self.pending = self.pending_since = None
        elif not self.fits(self.selection, budget):
            self.selection = self.allocate(eligible, budget)
            self.pending = self.pending_since = None
        else:
            candidate = self.allocate(eligible, budget*100//(100+self.config.upgrade_margin_percent))
            improved = (candidate != self.selection and candidate
                and all(id in candidate and candidate[id] >= i for id, i in self.selection.items()))
            # A usable emergency primary may resume immediately after a zero-budget outage.
            if not self.selection:
                emergency = {eligible[0]: 0}
                if self.supported(eligible[0], PROFILES[0]) and self.fits(emergency, budget):
                    self.selection = emergency
            if improved and not inputs.priorities_stale:
                key = tuple(candidate.items())
                if key != self.pending:
                    self.pending, self.pending_since = key, now
                remaining_s = max(0.0, self.config.upgrade_delay_s-(now-self.pending_since))
                if remaining_s == 0:
                    self.selection = candidate
                    self.pending = self.pending_since = None
                else:
                    waiting = True
            else:
                self.pending = self.pending_since = None
        self.context = context
        rates = self.fill(self.selection, budget)
        workload = self.workload(self.selection)
        rows = []
        for id in order or tuple(self.streams):
            s = self.streams[id]
            enabled_by_c2 = id in enabled
            index = self.selection.get(id)
            p = PROFILES[index] if index is not None else None
            code, reason = 'planned', 'Secondary view within the available budget'
            if not inputs.priorities_received:
                code, reason = 'waiting_inputs', 'Waiting for actual C2 priorities'
            elif not enabled_by_c2:
                code, reason = 'operator_omitted', 'Omitted by the C2 operator'
            elif id not in available:
                code, reason = 'source_unavailable', 'Source is paused, starting or has no fresh frames'
            elif input_blocked:
                code, reason = 'bandwidth_unavailable', 'Bandwidth input is missing or stale; no usable budget'
            elif not budget:
                code, reason = 'zero_budget', 'No video budget: link outage or zero video share'
            elif p:
                if id == eligible[0]:
                    reason = 'Primary view protected' if index >= 4 else 'Primary only / reduced quality to fit bandwidth'
                if waiting:
                    reason += '; holding profile while upgrade capacity stabilizes'
                elif inputs.priorities_stale:
                    reason += '; last C2 order retained, automatic upgrades blocked'
                else:
                    next_profile = next((q for q in PROFILES[index+1:] if self.supported(id, q)), None)
                    if next_profile is None:
                        reason += '; source resolution/fps ceiling reached'
                    elif workload-p.pixels_per_second+next_profile.pixels_per_second > self.limits.max_pixels_per_second:
                        reason += '; next profile exceeds Sigma workload cap'
                    else:
                        reason += '; higher profile requires more allocation / stable spare capacity'
            elif waiting:
                code, reason = 'upgrade_hold', 'Waiting for stable spare capacity before adding this stream'
            elif not self.fits(dict(self.selection, **{id: 1}), 10**15):
                code, reason = 'hardware_limit', 'Withheld by the provisional Sigma workload/session limit'
            elif self.selection and next(iter(self.selection.values())) < 4:
                code, reason = 'primary_protected', 'Bandwidth reserved for the primary view before adding overviews'
            else:
                code, reason = 'bandwidth_limit', 'Budget cannot fit another useful overview profile'
            rows.append({'id':id, 'name':s.name, 'priority':order.index(id)+1 if enabled_by_c2 else None,
                'operator_enabled':enabled_by_c2, 'selected':p is not None,
                'reason_code':code, 'reason':reason, 'profile_id':p.id if p else None,
                'width':p.width if p else None, 'height':p.height if p else None, 'fps':p.fps if p else None,
                'target_bitrate_bps':rates.get(id, 0), 'profile_minimum_bps':p.minimum_bps if p else None,
                'profile_maximum_bps':p.maximum_bps if p else None,
                'pixels_per_second':p.pixels_per_second if p else 0,
                'source_width':s.width, 'source_height':s.height, 'source_fps':s.fps})
        fingerprint = (tuple(self.selection.items()), tuple(rates.items()), tuple((r['id'],r['reason_code']) for r in rows),
                       budget, self.config.video_share_percent, inputs.priorities_stale)
        if fingerprint != self.fingerprint:
            self.plan_revision += 1
            self.fingerprint = fingerprint
        state = 'waiting_inputs' if input_blocked else 'no_video' if not self.selection else 'holding_upgrade' if waiting else 'degraded' if inputs.priorities_stale else 'plan_ready'
        self.last = {'schema_version':1, 'mode':'decision_only', 'encoder_connected':False,
            'plan_revision':self.plan_revision, 'evaluation_sequence':self.evaluation_sequence,
            'state':state, 'inputs':asdict(inputs), 'configuration':asdict(self.config),
            'budget':{'available_bandwidth_bps':bandwidth, 'video_allowance_bps':video_allowance,
                'encoder_budget_bps':budget, 'headroom_bps':video_allowance-budget,
                'planned_bitrate_bps':sum(rates.values()), 'unallocated_bps':budget-sum(rates.values())},
            'hardware':dict(asdict(self.limits), planned_pixels_per_second=workload,
                remaining_pixels_per_second=self.limits.max_pixels_per_second-workload,
                planned_streams=len(self.selection)),
            'stability':{'upgrade_pending':waiting, 'upgrade_remaining_s':round(remaining_s, 2)},
            'encoding_policy':{'codec':'h264','pixel_format':'nv12','rate_control':'CBR',
                'b_frames':0,'lookahead':False,'applied':False},
            'cameras':rows}
        return self.last
