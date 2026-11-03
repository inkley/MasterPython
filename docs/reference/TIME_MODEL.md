> Implementation update: [measured .242 candidate](MEASURED_IMPLEMENTATION.md), built but hardware acceptance pending.
> Historical design/offline-only status below describes its checkpoint; .241 bench results remain the validated baseline.

> Next measured encoding/budget: [METADATA_V2](METADATA_V2.md). It is a design, not enabled firmware.

# Time model: acquisition, reset domains and UTC

Definition dated 2026-11-02. This is the implementation contract for the next
milestone, not a claim that .241 recordings contain actual acquisition timestamps
or UTC. Accuracy goals below are provisional engineering targets, not mission
acceptance requirements. No MCU, record bytes or retained recording is changed.
This document supersedes conflicting time/identity proposals in older references;
existing v1 on-media semantics remain unchanged. See [current status](../CURRENT_STATUS.md).

## 1. Time domains must remain distinct

| Quantity | Meaning | Authoritative use |
|---|---|---|
| Raw MCU ticks | Free-running timer within an identified continuous clock domain | Sample order and elapsed acquisition intervals |
| Trigger proxy time | MCU timer read immediately before issuing the software ADC trigger | Measured pair timestamp, not ADC aperture or UTC |
| Nominal sample time | Index multiplied by nominal period | Legacy/v1 plot axis only, explicitly synthesized |
| Mapped UTC | Estimate from an identified clock mapping and uncertainty | Vehicle/other-module correlation, when qualified |
| Host receipt time | Host clock when data arrived, with host clock provenance | Transport diagnostics only |

Neither host receipt nor sample index replaces measured MCU acquisition time.
P1 and P2 each measure differential pressure independently; their ADC conversions
are sequential and share one pair identity, not an identical physical instant.

## 2. Acquisition clock and timestamp definition

Use the existing WTIMER0 64-bit free-running system-clock counter as the starting
implementation candidate. In .241 it runs at nominal 20 MHz (50 ns/tick), including
masked interrupts, flash CPU stalls and debugger halt, but is not persisted per
sample. Its frequency is derived from the MCU oscillator, not an independent
calibration. GlobalTimer counts serviced SysTicks and is never the elapsed-time
source. Do not substitute DWT/SysTick counts without revisiting their halt/wrap rules.

For the measured format, retain raw uint64 ticks as the authoritative timestamp,
with timer frequency/clock configuration metadata. Read coherently, using the
existing high/low/high hardware accessor. Read immediately before the ADC trigger
write; store `trigger_proxy_ticks` for EVERY attempted sequence, including failures.
If practical, also bracket the trigger write with a second read and characterize
the instrumentation latency. Do not disable interrupts for an entire conversion
just to simplify timestamps. Measure the added instrumentation overhead.

The proxy is earlier than the actual trigger write/aperture by an uncalibrated
latency. Label its reference point `PRE_SOFTWARE_TRIGGER`; do not silently call
it aperture time. A successful pair references that attempt's timestamp; an ADC
completion-read timestamp, if collected, is a separate field. Never timestamp
buffer insertion, CAN transmission, persistence or download as acquisition.

Monotonic presentation in microseconds may use integer floor(ticks*1000000/hz),
with overflow-safe quotient/remainder arithmetic. Raw ticks/frequency remain
available; conversion to integer microseconds introduces <1 us truncation error.
50 ns nominal resolution does not imply 50 ns accuracy. Use integer/rational
arithmetic for persisted mappings and host integer timestamps, not large float
Unix seconds. Check arithmetic and uint64 bounds; overflow ends a domain/capture
with an explicit fault, never wraps into a plausible earlier sample time.

P1 aperture is a positive offset after the proxy; P2 follows P1. Existing ADC
configuration supports an expected approximately 1 us interchannel separation,
but actual proxy-to-aperture and separation bounds are unmeasured. Export both
channel aperture times as unknown unless calibrated offset/bounds are available.
Pressure-to-electrical sensor latency is a separate uncharacterized transfer
property. A common pair UTC does not establish either channel's physical aperture.

## 3. Identity and lifecycle boundaries

| Identity | Contract |
|---|---|
| device_id | Provisioned stable module identity; UNKNOWN until provisioning is implemented. DID0/DID1 are part/revision information, not unique device IDs. |
| time_domain_id | Host-issued nonzero UUID for one uninterrupted timer epoch/configuration; include in all measured samples, events and mappings. |
| recording_id | Existing host-issued nonzero UUID, new for every accepted capture. Stop/persist/dump/ACK retain it. |
| attempt_index | uint64, zero-based per recording, increments once per actual software trigger, even if ADC fails. |
| sample_index | uint64 ordinal of valid pairs per recording; does not count failed attempts or prove gap-free acquisition. |
| mapping_id | Unique ID for an immutable UTC mapping version within one time domain. |

For host-controlled measured capture, firmware starts each boot UNASSIGNED. A
handshake assigns a fresh time_domain_id before measured capture is allowed;
accept assignment only while UNASSIGNED/stopped, not to rename a live domain.
Repeated host attachment queries the assigned ID without resetting it or the
timer. A reset clears assignment; a new handshake must use a new UUID. Do not
infer reset detection solely from host reconnect or a smaller timestamp.
This handshake is not implemented yet; it does not change current .241 commands.
Autonomous startup without a host needs a durable identity allocator reviewed
for interrupted allocation and wear; it is a separate deployment prerequisite.

Normal stop creates an immutable recording end; a restart uses a fresh recording
ID even in the same time domain. Store first attempt, first/last valid pair,
stop boundary and reason separately. No burst catch-up or previous-value fill.
Record the stop-to-next-start gap if both times share a valid domain; first-to-last
sample span is (N-1) periods, while N pairs represent N nominal sample slots.

Reset, brownout, timer reset, timer-source/frequency reconfiguration or loss of
known timer continuity ends the domain and active recording. Clock changes while
capturing are disallowed in the first implementation. After recovery, old data
retains its original recording/domain IDs and mappings; never attach the current
boot's time to old flash samples. Reboot does not retroactively supply an unknown
old boot ID. Ordinary timing_reset only resets diagnostics; it must not reset the
authoritative hardware timer or domain identity.

Host restart is not an MCU reboot. RTC battery survival is not continuity of the
MCU monotonic clock. Debug halt consumes timer time in .241: mark DEBUG_HALT only
when positively observed, otherwise unexplained discontinuity. Halt-contaminated
runs cannot pass uninterrupted-acquisition acceptance. A timer that stops in a
future low-power mode requires a new domain or independently validated continuity.
Unknown reset-to-restart duration stays unknown unless a qualified UTC source
bounds it. Never subtract boot-relative times from different domains.

## 4. Schedule, gaps and counters

Per recording, establish schedule origin at the first issued trigger proxy,
slot0, nominal period1000 us. Store actual attempt/sample identity and ticks;
nominal schedule positions are additional annotations. Interval target remains
990--1010 us, phase target +/-10 us relative to the schedule: provisional and
separate from oscillator frequency error and UTC accuracy. Phase compliance is
not established by the existing min/max interval diagnostics.

Use schedule-relative timing and known service history to identify skipped slots.
If jitter/latency makes slot assignment ambiguous, retain the actual timestamp,
report slot/missing count UNKNOWN or ESTIMATED and its basis. Do not adopt the
older floor-based estimator as an exact slot allocator. An out-of-tolerance
interval does not itself prove a lost pair; every ADC timeout/error is a known
failed attempt regardless of interval. Do not claim exact unserviced-trigger
counts from a software-trigger architecture with no hardware event counter.

Events retain reason, time/domain/recording identity, known/estimated/unknown
count classification and related attempts. Planned stop/persist pauses, acquisition
failures, timer discontinuity, RAM eviction, CAN publication loss and host transfer
loss are distinct. Detailed event overflow sets a durable sticky integrity flag
and count; missing event detail must not become a zero-loss claim. On ADC timeout,
quiesce before restarting; a late result cannot belong to a later attempt.

## 5. UTC mapping representation and semantics

Never set/step/slew the acquisition timer in response to UTC. Use an affine map
for one clock segment:

    utc_ns(c) = anchor_utc_ns + (c - anchor_ticks) * ns_per_tick

`ns_per_tick` is a rational slope near 1e9/nominal_hz, estimated/calibrated when
possible; it is not silently fixed to a measured-perfect oscillator. Mapping
record contract (binary encoding/version is deferred):

- mapping_id, time_domain_id, source identity/type and reference health.
- anchor_ticks, signed anchor_utc_ns, rational positive slope and unit/rounding rule.
- valid_from/to ticks, creation/publication order and causal vs offline-fit status.
- reference uncertainty, timestamp/transport/fit bounds, drift bound and bound
  provenance; unknown components remain unknown, not zero.
- source timescale/epoch, UTC conversion metadata, leap/smear policy, quality and
  reasons for invalidation. Store observations/residuals for audit/refitting.

Choose `UTC_POSIX_NS` for host interchange: signed integer nanoseconds since
1970-01-01T00:00:00Z under an explicitly tagged POSIX convention. This is not a
continuous SI-timescale guarantee across leap seconds. Also store UTC ISO8601 Z
when representable. GPS/TAI counts are not interchangeable with UTC; require
source-provided conversion metadata. Do not hard-code today's leap offset.
Reject/quarantine ambiguous leap-second intervals or start new mapping segments;
record smear provider/window if source uses smear. Unknown policy invalidates
fine cross-source alignment across the affected interval. Samples remain ordered
by monotonic time even if UTC repeats, jumps backwards or is adjusted.

References: [NIST time scales](https://www.nist.gov/pml/time-and-frequency-division/how-utcnist-related-coordinated-universal-time-utc-international)
and [NTPv4 timestamp/delay/dispersion model](https://www.rfc-editor.org/rfc/rfc5905.html).
These inform the design; implementing this contract does not imply NTP compliance.

## 6. Acquiring synchronization evidence

Prefer a qualified vehicle-clock reference when its accuracy/status are known.
Host datetime.now or an NTP-enabled OS alone is not a bounded UTC reference.
No IVER clock/transport precision is assumed. Characterize the complete path.

For command exchange, record host UTC and monotonic send h1, MCU receive c2,
MCU send c3, host UTC and monotonic receive h4, with endpoint definition and
clock-read uncertainty. Host monotonic time measures RTT despite wall-clock
steps. Reject exchanges spanning a host step, incompatible domain, negative
network remainder, invalid source or protocol/sequence ambiguity.

Convert MCU processing c3-c2 to reference units using the candidate slope.
Network remainder R = (h4-h1) - processing. A midpoint offset is an estimate
assuming symmetric path delay; CAN arbitration/USB queues can violate symmetry.
If all endpoint delays are covered and nonnegative, a conservative asymmetry
allowance is at least R/2, plus source/read/fit errors. Minimum-RTT filtering may
reduce queue effects but does not prove symmetry or remove fixed path asymmetry.
Without bounded endpoint/reference errors, report unknown bound and no accuracy
pass. Acquisition timestamping at firmware receipt is not hardware CAN timestamping.

PPS/shared trigger can improve relative alignment only if the edge is timestamped
with characterized latency; interrupt service time alone may be delayed by flash.
PPS also needs an identified UTC second; a pulse alone supplies no UTC epoch.
A shared trigger/PPS is future hardware evaluation, not a requirement to buy or
modify hardware now. RTC reads need oscillator-stop/backup validity, tick-edge
phase/read latency, resolution and drift bounds; an integer-second RTC value
without phase information cannot establish millisecond UTC accuracy.

## 7. Accuracy, holdover and quality

Keep requirements and measured quality separate:

| Quantity | Policy / provisional goal |
|---|---|
| Pair cadence and interval jitter | Nominal1kHz; +/-10 us interval and phase target already proposed; phase/aperture not yet verified |
| MCU-to-vehicle UTC correlation | Provisional <=1 ms absolute error bound at the trigger proxy, subject to mission confirmation and interface feasibility |
| Pairwise module alignment | Provisional <=1 ms combined bound; not guaranteed by each module merely meeting <=1 ms UTC |
| UTC when no qualified reference | UNKNOWN; acquisition and raw download still allowed |
| RTC-only startup | COARSE until reference/phase/drift evidence supports a tighter bound |

The 1 ms goals are planning criteria only. User/vehicle alignment tolerance is
unconfirmed, as are sensor latency and mission duration. No fixed resync period
is approved. Do not label a recording UTC-valid merely because it has a date.

Report conservative absolute error bounds in ns, not unexplained standard
deviations. Add worst-case component bounds unless a justified statistical model
and coverage level are documented. Suggested budget:

    B(c) = B_reference + B_capture + B_transport + B_fit
           + B_quantization + abs(delta_seconds) * drift_ppm * 1000 ns

Components must not be silently omitted or double-counted; define each budget's
reference point. Include aperture/sensor-latency terms separately if claiming
physical pressure-event time rather than trigger-proxy time. Unknown drift means
no bounded extrapolation away from characterized anchors. A confidence interval
from a short fit is not a guaranteed aging/temperature bound.

Example only: a 50 ppm bound contributes 50 us/s; 200 us initial error reaches
1 ms after16 s. 50 ppm is not a measured property of this board. Two independent
module errors combine conservatively as B1+B2, plus reference-distribution and
aperture uncertainties not already included. Shared-source errors may cancel
only with demonstrated correlation; do not subtract them by assumption.

States: UNSYNCHRONIZED (no map), COARSE (RTC/unqualified reference), SYNCHRONIZED
(accepted source and bounded current map), HOLDOVER (source lost; bound grows),
INVALID (discontinuity/source/policy fault). Separately export accuracy_met and
required_accuracy_ns; source health does not by itself mean target_met. If a
holdover bound exceeds target, accuracy_met=false; keep estimate with its bound
until mapping validity expires, then mark UTC unknown. No fabricated zero bound.

## 8. Resynchronization, storage and host exports

Accepted sync updates append immutable mappings; never rewrite committed sample
bytes or erase old provenance. New live mappings apply from a stated tick boundary.
UTC can step between mappings; record the correction/quality transition. Rejected
outliers leave prior qualified mapping unchanged and record rejection. A host
reconnect does not silently reset the sample domain or trust its current wall clock.

Later calibration can produce a separate OFFLINE_FIT mapping across stored samples
within its validity interval. Label it explicitly; never present retrospective
results as synchronization that existed during capture. Keep original observations
and prior mappings. Across reboot create a new map; correlate domains only when
each has qualified UTC evidence, including power-off uncertainty.

Persist domain/clock metadata, sync observations/mappings (or verified linked
sidecars), provenance and gap status sufficient to interpret samples after reboot.
If only host-side mappings exist, state that MCU-only recovery cannot reproduce
UTC; archival completeness requires the matching sidecar and its hash/identity.
ACK integrity verification must cover all required timing metadata in the future
schema; existing v1 ACK does not cover a future sidecar by implication.

Planned host fields: device_id status, time_domain_id, recording_id, sample_index,
attempt_index, trigger_ticks/frequency, time_basis, mapping_id, utc_posix_ns nullable,
utc_error_bound_ns nullable, sync_state, accuracy_met, host_received_utc and clock
provenance, gap/quality flags. Never serialize unknown as epoch0 or a zero error.
Plot acquisition elapsed time by default; UTC only with basis/uncertainty exposed.
Do not interpolate or filter silently across gaps, reset boundaries or incompatible
UTC maps. Preserve legacy nominal-time plotting with explicit labeling.

Existing v1 .241 recordings remain nominal-only/uncertain even when diagnostic
snapshots were taken nearby. They have no per-sample measured timestamps, boot
domain or qualified UTC map. Introduce capability/schema versions for the measured
contract; do not populate previously nominal fields with changed semantics or
reuse old reserved bytes without versioning. Recalculate RAM/flash capacity before
implementation; .241's 4094 raw pairs cannot be assumed to fit with added metadata.

## 9. Implementation gates and acceptance

Next work: capability-gated time-domain handshake, coherent per-attempt timer
capture and gap accounting, versioned persisted encoding/metadata, then host
decoder/exports. Define binary layout and memory budget before changing firmware.
RTC selection and vehicle-clock transport follow the accuracy/retention requirements.

Required tests before claiming implementation:

1. Increasing/coherent raw ticks, overflow arithmetic, diagnostic reset leaves
   timer/domain intact, planned pauses and service delays retain real elapsed time.
2. Fresh domain after reset/clock discontinuity, new recording after stop/restart,
   host reconnect retains domain, recovered recordings retain original identities.
3. Timeout/late result, ambiguous slots and event overflow report honest failures;
   attempt=valid+timeout+other_failure when quiescent. No synthetic catch-up samples.
4. Known injected offset/drift/reference noise/path asymmetry, UTC source step,
   leap/smear mismatch and source loss produce expected mapping/uncertainty states.
5. Bound growth, stale source, resync and retrospective refit never alter raw time;
   two-module alignment is assessed against combined bounds, not rate alone.
6. Reboot/power loss retains complete interpretation metadata or marks UTC unknown;
   RTC backup/invalid flag behavior is tested after hardware choice.
7. Host decoding preserves integer timestamps/unknown states and old nominal v1;
   gaps and uncertainty visible in analysis. Recalculate capacity and rerun the
   bounded acceptance suite after encoding/firmware changes.

This time-model definition is addressed for implementation planning. Measured
metadata, UTC synchronization, target validation, RTC hardware, drift characterization
and resynchronization tests remain unimplemented/unvalidated.
