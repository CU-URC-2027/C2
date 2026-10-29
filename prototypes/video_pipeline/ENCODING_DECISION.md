# Encoding Decision — local decision-only module

October 28, 2026. User-authorized prototype in the original local lab, now curated here. The decision core itself does no media processing, transmission or motor policy. The separately authorized actual Encoder now consumes its requests; see `ENCODER.md`. Source generators remain raw NV12. Values in the Decision node remain **requested plan values**; measured output is shown separately in the Encoder node.

## Input and output boundary

`encoding_decision.py` uses only the Python standard library. Immutable `DecisionInputs` map the received `StatusManager.snapshot()` fields, and immutable source capabilities describe native dimensions/rate. `decision_runtime.py` owns one instance in the lab asyncio loop, evaluates at 5 Hz independently of browser polling, and reads source metadata only. A paused source or one with no frame received in the past second is unavailable. No raw frame crosses this decision path.

The percentage is the share **available to video**, as confirmed by the user. Its current supplier is an explicitly labeled manual bench setting, default 70%; it is not a second C2 simulator or a claimed implemented comms allocator. Priorities still come only from the actual external C2 backend over the shaped link. The fixed preliminary headroom is 20%:

`video allowance = floor(available bandwidth bps × video share / 100)`

`encoder target budget = floor(video allowance × 0.80)`

Example: 10,000,000 bps × 70% × 80% = 5,600,000 bps. Overhead/headroom must later be reconciled with what the real bandwidth estimator measures so it is counted once. CBR targets do not constitute instantaneous traffic ceilings; keyframe bursts, pacing and congestion control remain encoder/transport work.

| API | Behavior |
| --- | --- |
| GET `/api/encoding-decision` | Observed current plan from the autonomous runtime |
| POST `/api/encoding-decision/config` | Set only `video_share_percent` (finite 0–100; Boolean/string/extra fields rejected) |
| GET `/api/state` | Includes the same plan under `architecture.encoding_decision` |

The plan contains its schema/revision/evaluation sequence, input session/revision/sequences and stale flags, budget arithmetic, hardware workload/margin, stability timer, encoding-policy request and all five per-camera rows. Each row carries source identity/native capability, operator eligibility/rank, selected profile, target bitrate bps, output width/height/fps and reason code/text. Missing output dimensions/rate are null, with zero target bitrate. `mode=decision_only`, `encoder_connected` (reported by the app from actual encoder enablement), and `encoding_policy.applied=false` are explicit.

## Provisional Sigma profile

These user-approved development constraints are engineering estimates, not manufacturer performance guarantees:

- H.264 / NV12 (8-bit 4:2:0); requested CBR, no B frames or lookahead.
- Five logical streams maximum; maximum individual output 3840×2160 at 30 fps, limited further by each source's native dimensions/rate.
- Aggregate output pixels: **248,832,000 pixels/s**, equivalent to one 4K30 or four 1080p30 outputs. Pixel count is a proxy; actual decoding/scaling, memory traffic, codec settings, thermals and other workloads are not measured by it.
- Source capabilities are separate: Camera 01 is 4K30; Camera 02–05 are 1080p30. Upscaling is prohibited.
- A 4K30 output consumes the complete provisional pixel allowance; it cannot coexist with secondary outputs under this cap. With multiple eligible views, the policy adds useful overviews before attempting 4K, so all five can be planned at lower resolutions.

Initial H.264 quality thresholds (not measured on real rover footage):

| Profile | Minimum / nominal / maximum target, bps |
| --- | --- |
| 320×180 @15 | 150,000 / 200,000 / 300,000 |
| 640×360 @15 | 250,000 / 300,000 / 500,000 |
| 640×360 @30 | 400,000 / 600,000 / 900,000 |
| 960×540 @30 | 800,000 / 1,100,000 / 1,500,000 |
| 1280×720 @30 | 1,500,000 / 1,800,000 / 3,000,000 |
| 1920×1080 @30 | 3,000,000 / 4,000,000 / 6,000,000 |
| 3840×2160 @30 | 10,000,000 / 15,000,000 / 20,000,000 |

## Allocation and stability

1. Use only received enabled IDs, preserving rank. Operator omissions are never overridden. Sources without fresh frames are excluded; the next available enabled source becomes primary.
2. Select the highest affordable primary baseline up to 720p30 (or its supported lower ceiling). Below 150 kb/s no profile is feasible. Lower baseline profiles provide emergency single-view operation.
3. Once the primary reaches its baseline, admit secondary overview profiles in rank order when both bitrate floors and hardware limits fit. A normal overview is 360p15; smaller-source fallback is 180p15.
4. Fill selected profiles toward nominal target bitrate in rank order. Attempt resolution/fps upgrades in rank order using remaining allocation; check minimum rate, native capabilities, pixel cap and session count each time. Fill residual bitrate up to the selected profiles' maximum rates in rank order. Unusable surplus remains unallocated.
5. During steady operation retain feasible existing profiles and adapt rates within their ranges. If their combined minimum no longer fits, recompute immediately. Zero budget removes every selection immediately.
6. Automatic structural upgrades (resolution/fps/additional streams) are candidates computed using `budget / 1.25`. They must improve the existing selection without degrading other selected profiles and remain feasible with the same candidate configuration for 4 seconds. A capacity fall/candidate change resets the hold. Rates within a profile can adapt without waiting.
7. On recovery from zero, a supported emergency primary can resume immediately while larger profiles wait. Initial valid input, explicit source activation and changed C2 order/eligibility recompute promptly; these explicit context changes bypass the automatic upgrade hold. When C2 priorities are stale, retain the last order and block automatic profile additions/upgrades. Source loss removes unavailable selections; source recovery while the order is stale does not add a stream. Missing/stale bandwidth yields no usable budget.

Revisions change for plan/budget/configuration changes; repeating C2/estimator heartbeat sequences do not churn plan revisions. Evaluation sequence continues at 5 Hz. Reason codes distinguish `operator_omitted`, `source_unavailable`, `waiting_inputs`, `bandwidth_unavailable`, `zero_budget`, `primary_protected`, `bandwidth_limit`, `hardware_limit`, `upgrade_hold`, and `planned`.

## Resource controls

Camera generation starts **off on every server start**, with Enable video streams / Disable video streams on the virtual camera bank. Disable stops all five FFmpeg processes and clears their buffers. Source controls are independent of the decision output: withholding an encoding plan does not change generators. Showing previews never starts generation. Hide previews only removes monitor fetching/conversion; use Disable video streams to stop the raw-source workload. The user explicitly authorized toggling sources for testing; leave them disabled after QA.

## Verification and remaining evidence

The decision-stage suite passed 56 tests before adding the actual Encoder, including budget/profile/hardware/native-capability invariants across 500 seeded input combinations, low-bandwidth primary protection, all/none omitted, source availability/failover, 4K cap behavior, immediate reductions, four-second/margin upgrade holds and reset, stale inputs, heartbeat revision stability, API boundaries, independent worker updates/health and default-off generation. Browser/API integration checks use actual external C2 priorities, test allocation edits, low bandwidth, outage/recovery, and actual generator enable/disable. Evidence is saved locally under `artifacts/encoding-decision-*`.

The color patterns check algorithm and plumbing behavior, not useful compression quality. Representative terrain/manipulation clips, actual encoder bitrate/latency/queue feedback, receiver frame age, and sustained Sigma workload tests are needed to calibrate these thresholds. ROS 2 should wrap the same core with typed metadata subscriptions/publications and a single owner/callback group; no DDS or ROS adapter for this new plan was implemented here. The existing StatusManager ROS scaffold is unchanged.

Public primary references researched October 28, 2026: [Sigma specifications](https://docs.lattepanda.com/content/sigma_edition/Specification/), [i5-1340P specifications](https://www.intel.com/content/www/us/en/products/sku/232126/intel-core-i51340p-processor-12m-cache-up-to-4-60-ghz/specifications.html), [Intel codec capabilities](https://www.intel.com/content/www/us/en/docs/onevpl/developer-reference-media-intel-hardware/1-1/overview.html), [dynamic encoder reconfiguration](https://intel.github.io/libvpl/latest/appendix/VPL_apnds_c.html), [interactive media congestion requirements](https://www.rfc-editor.org/rfc/rfc8836.html), and [content-dependent bitrate considerations](https://www.rfc-editor.org/rfc/rfc9317.html#section-3.1.1). No measured Intel throughput or approved operational quality threshold is inferred from those documents. This is an AI-assisted teaching prototype requiring substantive human engineering validation, not an approved competition architecture or submission-ready deliverable.
