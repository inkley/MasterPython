> Explicit RAM-only bench metadata schema2/feature1 is described in [BENCH_GAP_STACK](BENCH_GAP_STACK.md). Normal metadata schema1/feature0 is unchanged.

> Implementation update: [measured .242 candidate](MEASURED_IMPLEMENTATION.md), built but hardware acceptance pending.
> Historical design/offline-only status below describes its checkpoint; .241 bench results remain the validated baseline.

> Offline implementation checkpoint: [codec and recovery tests](OFFLINE_V2_CODEC.md).
> MCU v2 capture/storage and wire negotiation remain unimplemented.

# Measured recording metadata v2 and bounded RAM budget

Design settled for the next implementation milestone, 2026-11-02. **Not implemented
or flashed.** Existing .241 v1 recordings, the retained 4094-pair recording and
legacy capacity are unchanged. This specifies stopped-acquisition persistence,
not a continuous logger. Alignment goals remain provisional, as confirmed by the
user. [TIME_MODEL](TIME_MODEL.md) defines time semantics.

## Decision and scope

Use fixed 16-byte measured-pair records: raw uint64 timer ticks, uint32 attempt
index, uint16 P1 and uint16 P2. Preserve every valid pair's actual trigger proxy,
including irregular spacing. Do not infer acquisition time from nominal deltas.
Per-sample attempt indices distinguish failed triggers from successful pairs;
unserviced intended slots remain an estimate/unknown, not fabricated attempts.

Measured mode has **1024 valid pairs maximum (1.024 s nominal)** and **32 detailed
64-byte events**. Legacy raw mode remains4094 pairs. The modes share one 16KiB
staging allocation and cannot acquire simultaneously. No second full raw/timed
array, dynamic allocation or per-sample UTC array is permitted in this budget.
This deliberately reduces measured capture duration to leave safe design margin.
The 10--30 s goal needs later buffering/transport architecture, not a larger array
silently squeezed into32KiB. A 4094-pair measured capture would require65504 bytes
for samples alone and is impossible on this MCU.

UTC is **unavailable in the first v2 profile**: raw measured time, IDs, gap events,
clock metadata and capture summaries are persisted. Mapping count/schema are zero;
no epoch/uncertainty is invented. UTC mapping transport/persistence comes later
under an explicit capability/schema extension, not by reinterpreting reserved bytes.

## Versioning, ownership and physical pages

- Keep magic IPLG, 1KiB page, CRC32/ISO-HDLC and final CMIT marker, but envelope
  version=2. Every block of one recording uses the same version and UUID/domain.
- Version1 remains readable/nominal-only. No in-place migration, metadata retrofit
  or relabeling existing recordings as measured. Unknown versions remain protected.
- New firmware must expose explicit v1/v2 read/write and measured-capture capacities
  before accepting measured capture. Old CLI must reject unsupported capability;
  legacy commands cannot silently switch format. New host decodes v1/v2 explicitly.
- CRC32 is accidental-corruption checking, not authentication. CRC covers0..1015;
  marker at1020 is written separately last. Padding isFF; reserved fields are zero.
  Readback/semantic checks and stopped capture precede manifest commit.
- Partition remains [0x20000,0x40000),128 pages. Pages0/1 journals,2 manifest,
  **3 metadata**,4..6 events,7..8 protected spares,9..127 data. V1's event-region
  proposal is not reused without version discrimination. Scratch block7 remains
  excluded; no permission to run old scratch commands against a v2 footprint.
- Sequence: metadata seq0; data seq1..D; events seqD+1..D+E; manifest seq1+D+E.
  Journals use their independent generation rule. Stream CRC covers complete
  committed metadata/data/event blocks in this order, excluding manifest/journals.
  Require exact kinds/page addresses, contiguous sequences and matching IDs.
- DATA pages are contiguous from9, event pages from4. Counts must equal ceilings
  for densely packed records. No timestamp-based block splitting is needed with
  full ticks/attempt indices. Manifest commits last; no valid manifest means
  incomplete/quarantined, never complete capture. Reboot scans are read-only.

## Byte layout

Canonical machine-readable offsets: firmware `tools/metadata_v2_schema.json`.
All numeric fields unsigned little-endian; UUID bytes use RFC order, all-zero
recording/time-domain IDs invalid. Explicit serialization is required; do not
write native C structs or assume packed/unaligned uint64 accesses are safe.
Record sizes/offsets below have no implicit alignment padding. Signed UTC is not
part of this profile. All arithmetic/counts/regions must be range-checked.

Kinds: DATA1, EVENTS2, MANIFEST3, JOURNAL4, METADATA5.
Envelope payload_schema: DATA1, EVENTS1, METADATA1, MANIFEST2, JOURNAL2.
Header record_bytes is16,64,256,256,96 respectively. Non-DATA headers use zero
first_sample_index/first_trigger_ticks; DATA points to the first pair in its block.
Header nominal_tick_hz=20000000, nominal_period_us=1000 for this profile.
Header bytes field=96, version2; reject unknown kind/schema/bits/reserved bytes.

### Common envelope header: 96 bytes

| Offset | Bytes | Field |
|---|---:|---|
| 0 | 4 | magic |
| 4 | 2 | version |
| 6 | 2 | kind |
| 8 | 16 | recording_id |
| 24 | 16 | time_domain_id |
| 40 | 4 | sequence |
| 44 | 2 | record_count |
| 46 | 2 | record_bytes |
| 48 | 8 | first_sample_index |
| 56 | 8 | first_trigger_ticks |
| 64 | 4 | nominal_tick_hz |
| 68 | 4 | nominal_period_us |
| 72 | 4 | flags |
| 76 | 2 | header_bytes |
| 78 | 2 | reserved_zero_0 |
| 80 | 4 | payload_schema |
| 84 | 12 | reserved_zero_1 |

### Measured pair: 16 bytes

| Offset | Bytes | Field |
|---|---:|---|
| 0 | 8 | trigger_ticks |
| 8 | 4 | attempt_index |
| 12 | 2 | p1 |
| 14 | 2 | p2 |

### Gap/event detail: 64 bytes

| Offset | Bytes | Field |
|---|---:|---|
| 0 | 8 | event_sequence |
| 8 | 8 | attempt_index |
| 16 | 8 | previous_ticks |
| 24 | 8 | current_ticks |
| 32 | 8 | missing_pair_count |
| 40 | 8 | related_sample_index |
| 48 | 4 | reason_bits |
| 52 | 4 | validity_bits |
| 56 | 4 | detail_code |
| 60 | 4 | reserved_zero |

### Clock/domain metadata payload: 256 bytes

| Offset | Bytes | Field |
|---|---:|---|
| 0 | 4 | schema |
| 4 | 4 | payload_bytes |
| 8 | 16 | device_id |
| 24 | 4 | device_id_known |
| 28 | 4 | timestamp_reference |
| 32 | 8 | tick_hz_numerator |
| 40 | 8 | tick_hz_denominator |
| 48 | 8 | nominal_period_ns |
| 56 | 4 | timer_width |
| 60 | 4 | timer_behavior_bits |
| 64 | 8 | schedule_origin_ticks |
| 72 | 8 | first_attempt_ticks |
| 80 | 8 | capture_accepted_ticks |
| 88 | 8 | reserved_zero_0 |
| 96 | 8 | proxy_latency_bound_ns |
| 104 | 8 | drift_bound_ppb |
| 112 | 4 | nominal_tick_resolution_ns |
| 116 | 4 | validity_bits |
| 120 | 4 | sample_limit |
| 124 | 4 | event_limit |
| 128 | 4 | utc_schema |
| 132 | 4 | mapping_count |
| 136 | 4 | rcc |
| 140 | 4 | rcc2 |
| 144 | 4 | pllstat |
| 148 | 4 | nominal_pair_hz |
| 152 | 4 | feature_bits |
| 156 | 100 | reserved_zero_1 |

### Final manifest payload: 256 bytes

| Offset | Bytes | Field |
|---|---:|---|
| 0 | 4 | schema |
| 4 | 4 | payload_bytes |
| 8 | 8 | samples |
| 16 | 8 | attempts |
| 24 | 8 | adc_timeouts |
| 32 | 8 | adc_errors |
| 40 | 8 | events_retained |
| 48 | 8 | events_total |
| 56 | 8 | events_lost |
| 64 | 8 | estimated_missing_slots |
| 72 | 8 | first_valid_ticks |
| 80 | 8 | last_valid_ticks |
| 88 | 8 | capture_stop_ticks |
| 96 | 8 | first_attempt_ticks |
| 104 | 8 | last_attempt_ticks |
| 112 | 8 | capture_accepted_ticks |
| 120 | 4 | data_blocks |
| 124 | 4 | event_blocks |
| 128 | 4 | metadata_blocks |
| 132 | 4 | stream_crc32 |
| 136 | 4 | quality_bits |
| 140 | 4 | stop_reason |
| 144 | 8 | ram_rejected |
| 152 | 8 | unpaired_tail |
| 160 | 8 | tx_drops |
| 168 | 8 | tx_failures |
| 176 | 4 | event_reason_or |
| 180 | 4 | counter_rule |
| 184 | 8 | validity_bits |
| 192 | 64 | reserved_zero |

### Lifecycle journal payload: 96 bytes

| Offset | Bytes | Field |
|---|---:|---|
| 0 | 16 | recording_id |
| 16 | 4 | manifest_crc32 |
| 20 | 2 | operation |
| 22 | 2 | flags_zero |
| 24 | 8 | generation |
| 32 | 16 | request_id |
| 48 | 4 | data_blocks |
| 52 | 4 | samples |
| 56 | 4 | metadata_blocks |
| 60 | 4 | event_blocks |
| 64 | 16 | owned_page_bitmap |
| 80 | 4 | schema |
| 84 | 12 | reserved_zero |


## Field validation and nullability

DATA pairs require P1/P2<=4095, strict increasing trigger_ticks and attempt_index
within/across blocks. Sample index is header first_sample_index + record ordinal,
contiguous0..N-1 for retained valid pairs; attempt index starts at0 for the first
issued trigger and may skip failed attempts. It is stored uint32 as a bounded
encoding of the model's logical uint64 counter: end capture before overflow,
never wrap/truncate. Session summary counters remain uint64. Successful data
attempts must be less than total attempts. If an ADC result is invalid, it is not
stored as a valid sample. No duplicated prior pair or zero-valued placeholder.

Header flags bits:0 RAW_TRIGGER_TICKS,1 EVENTS_PRESENT,2 DEGRADED,
3 EVENT_DETAIL_LOST,4 UTC_UNAVAILABLE,5 MISSING_COUNT_ESTIMATED. Bits0/4 required;
others reflect frozen final capture quality and are identical on all non-journal
blocks. Journal flags use this target recording's frozen values. No aperture/UTC
claim is implied by RAW_TRIGGER_TICKS. Other bits rejected.

Event reason bits0..11: ADC_TIMEOUT, ADC_ERROR, TIMING_EARLY, TIMING_LATE,
UNSERVICED_SLOTS_ESTIMATE, CLOCK_DISCONTINUITY, DEBUG_HALT_CONFIRMED,
RAM_REJECTED, TX_QUEUE_DROP, TX_FAILURE, EVENT_DETAIL_LOST, PLANNED_PAUSE.
Combine reasons about the same detected discontinuity in one event. Do not label
an unexplained delay DEBUG_HALT or estimate an exact loss from interval alone.

Event validity bits0..5: attempt_index known, previous_ticks known, current_ticks
known, related_sample_index known, missing count exact, missing count estimated.
Exact/estimated are mutually exclusive; neither means UNKNOWN. Unknown fields
serialize zero with validity bit clear, not known zero. Nonzero known times use
the same domain. Event sequences start0; retained events form a prefix. detail_code
is zero in this profile (new detail enumerations require versioning). related sample
index refers to a valid sample if known; failed attempts may reference no sample.
PLANNED_PAUSE is emitted only when the relationship is known, never to assert
continuity across two domains. Recording stop/start fields already bound captures.

Metadata schema1, payload_bytes256. device_id_known0 means all16 ID bytes zero;
1 means a provisioned nonzero ID. timestamp_reference1=PRE_SOFTWARE_TRIGGER.
Timer width64; timer_behavior bits0..3 indicate runs during IRQ mask, flash stalls,
debug halt, and nominal-system-clock-derived; first profile requires all4.
Frequency numerator20000000/denominator1 is nominal, not calibrated. Resolution50ns
is nominal quantization, not total accuracy. rcc/rcc2/pllstat record configuration,
not unique device identity. feature_bits0 for this profile. sample_limit1..1024,
event_limit32, nominal_pair_hz1000. utc_schema=mapping_count=0.

Metadata validity bits0..5: provisioned device known, first-attempt known,
schedule-origin known, proxy-latency bound known, drift bound known, independently
calibrated frequency. First measured profile requires first-attempt/schedule bits;
latency/drift/calibration remain unset until characterized. Unknown optional bounds
are zero with validity clear. device-known bit agrees with device_id_known.
capture_accepted_ticks<=first_attempt_ticks=schedule_origin_ticks; accepted ticks
are admission time, never an acquisition timestamp.

Manifest schema2, payload_bytes256;1<=samples<=1024. At quiescence:

    attempts = samples + adc_timeouts + adc_errors
    events_total = events_retained + events_lost
    data_blocks = ceil(samples/57)
    event_blocks = ceil(events_retained/14)
    metadata_blocks = 1

No unaccounted RAM rejection is permitted for a passing bounded capture. If FIFO
error/timeout occurs, stop/quiesce acquisition, freeze explicit failure reason and
retain prior valid pairs/events. With zero valid pairs, preserve/export diagnostics
but reject normal persist; do not claim an empty valid recording. Recovering the
ADC or discarding faulted RAM needs explicit later policy, not automatic restart.

First/last valid ticks and first/last attempt ticks must agree with retained data,
known failed attempts and metadata. capture_stop_ticks is the continuous hardware
time when acquisition was disabled, not persist/download completion. It must not
precede last attempt/valid tick while clock-valid. Counter_rule1 means the equality
above. Stop reasons:1 requested,2 sample limit,3 ADC fault,4 event detail overflow,
5 clock/identity fault,6 backpressure/RAM failure. event_reason_or preserves OR of
all observed reason flags including lost detail. Reserved bytes stay zero.

Manifest quality_bits0..7: ADC_FAILURE, INTERVAL_VIOLATION, PHASE_VIOLATION,
MISSING_ESTIMATE_PRESENT, EVENT_DETAIL_LOST, CLOCK_INVALID, RAM_LOSS, TX_LOSS.
Validity bits0..4: monotonic domain valid, stop time valid, estimated-missing total
available, phase assessed, physical aperture calibrated. No bit means UTC valid.
Unknown/unassessed phase or missing totals must not become a zero-error claim.
Unused bits rejected. Flag and count consistency is mandatory. Phase calculation
uses first-attempt schedule, not a reset origin per block; calibrated absolute
clock/UTC accuracy remains separate.

## Event capacity and atomic publication

The ISR owns a fixed sample/event producer index. Capture writes a full16-byte
entry before publishing count; stopped snapshot uses a short critical section
and resolves any in-flight attempt. Volatile alone does not make64-bit data atomic.
Use naturally aligned RAM structs whose sizeof/offsets are checked at build time;
wire serialization is separate. No flash, CRC scan or full transfer in the ISR.

Keep32 detailed events; on the next required detail, increment events_lost and
events_total, set sticky EVENT_DETAIL_LOST and stop capture immediately. Preserve
aggregate attempt/failure/timing counters even when the detail cannot fit. Thus
ordinary recording stops with at most32 retained details and one lost detail;
post-stop diagnostics are not appended to capture totals. This is best-effort
fault evidence, not silent overflow. A data entry and its related event/counters
must become coherent before stop/finalization. ADC/timer faults are not ignored
just because detail capacity is exhausted.

## Recovery, ACK and clear

New v2 lifecycle journals are96 bytes, schema2. Operations1 ACK,2 DELETE;
flags_zero=0, generation>0, request ID nonzero. owned_page_bitmap is128 bits,
least-significant bit0 of byte0 represents relative page0. It includes manifest,
metadata, all used event/data pages and excludes journals0/1, spares7/8 and all
unused pages. Count fields and bitmap must exactly match a verified recording.
Persist that footprint in ACK/DELETE intent so interrupted reclaim need not infer
ownership from an already-erased manifest. Validate version, target UUID/domain,
manifest CRC, generation and footprint before any erase. Unknown/conflicting
ownership stays protected; unrelated valid/partial captures must not be reclaimed.

Journal stream is independent of recording block sequence; header sequence is
generation low32 bits, header target IDs retained. Clear commits DELETE first,
erases only owned pages with manifest last; do not erase journals implicitly.
ACK never deletes. New capture UUID cannot reuse old clear authority. Implement
v1/v2 journal recognition explicitly; old v1 deletion intent cannot authorize v2
metadata/event erasure or migration. Mixed-version capture footprints are invalid.
Test all boundaries offline before hardware. No power-failure guarantee follows
from this design alone. Existing retained v1 recording is protected during upgrade.

## RAM budget from the .241 linker map

SRAM total32768. Map used20888; occupied span20896 including8 alignment bytes.
Existing raw array16376; log_image1024 and stack2048 are already included.
Budget uses occupied span rather than only allocated symbols:

| Allocation | Bytes |
|---|---:|
| Existing span excluding raw array (retains log_image, stack, timing diagnostics) | 4520 |
| Shared legacy/raw or1024*16 measured staging | 16384 |
|32*64 event array | 2048 |
| Metadata/manifest/domain workspace allowance | 1024 |
| New counters/descriptors/control allowance | 512 |
| Additional stack allowance (4096 total stack reservation) | 2048 |
| Planned occupied total | **26536** |
| Remaining unallocated design margin | **6232** |

No double-counted second serialization image or copied SRAM flash code is included.
Metadata uses the retained1KiB log_image for page formatting; workspace allowances
cover small live state, not more page arrays. New fields must fit these explicit
allowances. Modes use one union/aligned byte arena and cannot preserve two different
RAM captures simultaneously. Switching cannot discard frozen source silently.
Existing legacy/v1 paths require accessors before changing allocation layout.

4094 legacy pairs remain possible in the shared arena; measured mode's cap is
1024. This is a PLANNING budget, not a linked v2 image or stack high-water result.
Require >=4096 bytes unallocated after the real link, enforce allocated sizes,
increase stack reservation to4096, measure stack under worst nested interrupt/
formatting paths, and reject the implementation if margins fail. No optional DMA,
SRAM-executed flash routine or continuous queue is approved by this budget.

Reproduce from firmware root: `python tools/check_metadata_v2.py`. The checker
validates every field offset/size, derives capacities and guards the existing
16376-byte raw-array symbol before subtracting it. Rebaseline deliberately when
the actual firmware layout changes; do not subtract the old array twice.

## Flash capacity and changed acceptance limits

96-byte header leaves920 payload bytes:57 pairs/page (8FF bytes left),14 events/page
(24FF bytes left). Data region119 pages holds at most6783 pairs (6.783s nominal),
but current chosen measured RAM cap permits only1024 pairs,18 data pages.
Metadata1 page + manifest1 + up to3 event pages gives20--23 owned pages total.
Fresh persist therefore expects20--23 erase and40--46 program API calls under the
existing full-body-plus-marker programming pattern. These are counts, not timing
or wear measurements. v1 remains10/20 for1000 and36/72 for4094. More metadata and
new CRC/recovery scans require new measured storage timing after implementation.

Use measured1024-pair boundary tests (also1,57,58,1023) and event boundaries0,14,15,28,
29,32/overflow; retain v1 4094 regression separately. Cannot claim measured4.094s
just because legacy capture supports that length. Test ADC failures/gap ambiguity,
unknown UTC/drift, raw timer rollover arithmetic, coherent freeze, missing/duplicate/
foreign blocks, CRC/commit faults, ACK footprint and interrupted clear. A decoder
must reject wrong record_bytes, duplicate event sequences, illegal flags/bitmaps,
nonzero reserved fields and incompatible domain IDs before reporting completeness.

## Implementation sequence

1. Add offline v2 codec/semantic validator and adversarial recovery tests against
   this frozen schema; current checker is a layout/budget validator, not that codec.
2. Review capability/command negotiation and domain-assignment handshake with host;
   settle CAN fragmentation before modifying on-device command handlers.
3. Introduce shared RAM accessors and measured capture with coherent timestamps,
   counters/events. Link/check sizes and stack; keep legacy behavior/capacity.
4. Implement stopped v2 metadata/data/event persistence, recovery and ownership-aware
   ACK/clear; extend host decoder, exports and exact comparison tests together.
5. Flash only after offline/build/layout checks; preserve current v1 recording and
   run updated bounded acceptance, explicitly separating v1 and measured v2 modes.

The format/RAM decision is addressed for planning. Offline Python codec/fault validation is now available (see linked checkpoint);
wire negotiation, firmware/C codec, final linked footprint, runtime stack and
hardware timing acceptance remain pending. No format-version2 writes have been enabled.
