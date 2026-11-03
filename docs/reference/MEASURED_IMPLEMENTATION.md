# Measured acquisition candidate .242: firmware, transport and Python

2026-11-02. **Implementation candidate flashed; checkpoint A passed, measured hardware acceptance pending.**
The validated eval baseline remains .241 and its protected4094-pair v1 recording.
The first checklist item is implemented for bench evaluation but stays unchecked
until the hardware sequence below passes. UTC/RTC and continuous acquisition during
flash are not implemented by this change. Alignment targets remain provisional.

## Implemented path

- Firmware build1010 -> CLI version0.0.3.242. New measured_capture.h and shared
  aligned16KiB arena support1024 measured pairs or4094 legacy raw pairs, never both.
- Actual coherent uint64 WTIMER0 ticks are read immediately before ADC trigger;
  attempt index/12-bit P1/P2 accompany valid pairs. This is a pre-trigger proxy,
  not a characterized aperture. Nominal20MHz tick frequency, UTC unavailable.
- Per-attempt interval early/late, estimated unserviced slots, ADC timeout/error
  and detected nonmonotonic clock faults produce frozen events/aggregate counters.
  Estimated counts stay estimated. Phase is explicitly unassessed, not passed.
-32 fixed event slots. A33rd required detail sets sticky loss/reason/counter and
  stops capture. ADC failure stops acquisition and latches restart rejection until
  MCU reset; no late ADC result is attributed to another attempt. A zero-valid-pair
  fault cannot become a normal committed recording: preserve console/timing_status
  diagnostics before reset; normal dump_measured/persist requires at least one pair.
- Stopped snapshots serialize complete v2 metadata/data/events/manifest from RAM;
  dump_measured downloads a verified reconstructed binary plus CSV/JSON. Snapshot
  does not persist RAM. Counter reset does not reset the timer/domain.
- Stopped flash persistence commits metadata, data and events, manifest last;
  MCU verification/recovery discriminates v1/v2. ACK/CLEAR journals retain exact
  version2 ownership bitmap and metadata. Unknown/ambiguous regions stay protected.
  Partial clear resumes only with an intact matching committed manifest proof;
  damaged-manifest ambiguity is not permission to erase a newer torn capture.
- V1 commands/format remain nominal-only. Old scratch fixtures reject a v2 record;
  dump_buffer rejects measured RAM rather than interpreting it as raw32-bit pairs.
- Host v2 download/validation uses flash_v2.py; measured_export.py writes raw ticks,
  attempt/domain/recording IDs, gap/quality flags, events.json and clock/summary JSON.
  verified_file covers v2 binary metadata/events before durable transfer ACK.
- Analysis uses (tick-first_tick)/hz, subtracting integers before float conversion.
  It never derives MCU time from host receipt. Plot lines break before detected
  discontinuities, with timing/event markers including terminal failed attempts.
  Filtering is disabled for irregular, gapped or quality-degraded captures; no
  implicit resampling or filtering across missing data. Uniform qualified samples
  may retain the existing filter. UTC and its error bound remain null.

New host commands:

| Command | Meaning |
|---|---|
| measured_init | Query existing domain or assign a fresh UUID after reset; no timer reset |
| measured_capture N (1..1024) | Bounded measured capture; explicit argument with space required |
| dump_measured LABEL | Verified frozen RAM export; source preserved |
| flash_stop | Stop active bounded capture; preserves RAM |
| persist_buffer / verify_flash / dump_flash LABEL | Format-discriminated persistence/verification/retrieval |
| ack_flash PATH / clear_flash PATH | Verify saved binary then ID/digest-bound lifecycle |

Syntax example: `measured_capture 58`. No new capture overwrites a valid flash
recording or frozen source. measured_init alone may assign RAM identity while a
recording is retained; it sends no flash writes. Host reconnect retains the domain.

## Capability and boot-domain wire contract

8-byte command/reply framing and CAN IDs stay unchanged. RPC arguments/reply u32
are big-endian; v2 blocks/fields are little-endian. UUIDs use RFC byte order.
Existing0x0F retains0x49500104 for legacy compatibility. New selector RPC0x30:

| Argument | Reply |
|---|---|
|0 |0x49500201: measured profile1 |
|1 /2 |1024 sample capacity /32 detailed events |
|3 |0 UNASSIGNED /1 ASSIGNED |
|4..7 | Four big-endian words of assigned domain UUID; rejected if unassigned |

Firmware boots with domain UNASSIGNED. Stage a nonzero UUID with ordered0x31..34;
word0 restarts staging, later words require the exact accumulated prefix mask.
Replies echo the word (a high bit in a UUID word is NOT an error bit). Commit0x35
with CRC32 of the16 UUID bytes; reply1 succeeds. Partial/out-of-order/CRC mismatch
never assigns identity. Re-staging an already assigned same ID is idempotent;
a different ID is rejected until MCU reset. Known retained v2 manifest/journal
IDs are rejected as fresh post-reset domains; global uniqueness still relies on
a conforming host UUID allocator, not a durable boot-counter implementation.
Host queries/readbacks assignment and never resets the timer on reconnect.

Recording UUID staging remains0x10..13. Arm0x38 with CRC32 of recording UUID bytes,
assigned domain UUID bytes, then limit as four big-endian bytes. Reply echoes that
token. Begin0x36 carries limit; firmware recomputes the token and consumes the arm
before acceptance. This binds limit/domain/ID and rejects stale or mixed staging.
CRC detects accidental transaction mixups; it is not authentication. A start retry
never resets a live/frozen recording. Single host owns the interface; multi-client
arbitration is not provided. Unknown response outcomes require query, not blind start.

0x37 reads a frozen RAM image page (relative index0..127, only owned pages valid).
ACK256 words then tag0x3B frames: ordinal BE16 in bytes1..2; four raw bytes in4..7.
Host requires order/count and validates CRC, manifest, identity/domain, counters
and all pages before exporting. Active capture reads are rejected. The frozen
recording cannot be silently replaced while downloading. Existing0x18/tag0x1A
reads actual flash; v2 host first validates manifest counts before requesting pages.
New errors11/12/13 mean ADC restart latched /unassigned domain /unsupported clock.
The old v1 decoder/commands are not silently upgraded to measured semantics.

## Build and offline evidence

Debug build/link and ELF reserved-partition/vector/stack checks passed. Stack
reservation4096 bytes. Linker occupied span25136 of32768 bytes ->7632 unallocated;
actual used symbols25128. Arena16384 and events2048 confirmed by map; linked
margin exceeds the4096-byte floor. Runtime stack high-water remains unmeasured.
Release configuration stack updated, but no generated Release directory was
available to build; only Debug is verified here. No claim of C execution on hardware
or cross-language MCU golden output is made by compilation alone.

76 host tests pass (40 existing,21 v2 codec and15 measured-pipeline groups);
firmware offline timer5 + format8 = **89 tests**. This includes existing v1 regression,
v2 corruption/recovery tests and15 measured-pipeline tests (export precision,
lookup/download, handshake rejection/reconnect/token binding, v2 ACK guard,
CSV validation and actual plot generation). An OFFLINE fixture gap plot was
rendered and visually checked. It is synthetic evidence, not a sensor measurement.

Reproduce in MasterPython:

```powershell
.\.venv\Scripts\python.exe -m unittest test_reentry test_flash_protocol test_flash_recovery test_flash_lifecycle test_timing_protocol test_flash_v2 test_measured_pipeline
```

From firmware root build Debug, run tools/verify_firmware_layout.py on its .out,
run tools/check_metadata_v2.py, tools/test_timer.py and tools/test_log_format.py.
The RAM checker now recognizes the new arena/event/stack layout without subtracting
an obsolete array twice. Canonical v2 JSON offsets are unchanged.

## Hardware checkpoint A: preserve current v1 recording

1. Exit CLI. In CCS build/load Debug/Inkley_PressureSensor.out using **Necessary
   Pages Only**, GH6PM target and16MHz crystal setting. Never mass erase. Resume.
2. Start updated CLI and run:

```text
version
flash_recovery
verify_flash
dump_flash v242_preserved_v1_01
measured_init
measured_init
```

Expect .242, COMMITTED4094, verified download matching the saved v1 binary, and
identical timer-domain IDs on the two init calls. None of these steps deletes
or replaces the current recording. Stop and review this output before reclamation.
The existing v1 recording remains NOMINAL_ONLY, never retroactively timestamped.

## Hardware checkpoint B: disposable measured capture

Only after A and verified host backup, explicitly ACK and clear that exact saved
v1 binary using the established runbook. Require CLEARED. Then:

```text
timing_reset
measured_capture 58
```

Wait two seconds without CCS halts; then:

```text
flash_status
buffer_status
dump_measured v242_ram_58
persist_buffer
verify_flash
dump_flash v242_flash_58
flash_recovery
```

Expect58 valid pairs, capacity1024, identical recording/domain/raw ticks/attempts/
P1/P2 in RAM and flash reconstructed binaries, coherent summary, no unexplained
errors and COMMITTED. Use full byte comparison (not only P1/P2), plus flash_v2
semantic validation. 58-pair clean persist expects2 data pages +metadata +manifest:
4 erase/8 program calls. A1024-pair clean capture uses18 data pages:20/40 calls
without event pages. Add at most3 event pages when populated. Durations need
fresh measurement; .241 timings are not .242 performance evidence.

Analyze the resulting samples.csv with analyze_pressure.py. Axis must say measured
trigger elapsed time; no UTC. Real tick jitter may automatically disable filtering.
Repeat sample boundaries1/57/58/1023/1024 as appropriate, reclaiming explicitly
between captures. A1-pair record needs --no-filter due filter length, as before.
No requirement to erase/reflash the whole MCU for repeated tests.

## Hardware checkpoint C: gaps, restart and retention

Arrange a controlled disposable delayed-service test and verify actual interval
and event markers/estimated counts; a deliberate debug halt is a negative gap
exercise and cannot pass normal cadence acceptance. Record the intervention;
unconfirmed debugger causes remain unexplained/late, not DEBUG_HALT_CONFIRMED.
ADC error/timeout, event overflow, runtime stack high-water and C/Python agreement
on failure records need controlled validation; synthetic host fixtures do not
establish those hardware paths. Zero-valid-pair failures retain diagnostics only.

Reboot a valid v2 recording without reflash; verify/download and compare exact
binary. Query/init assigns a NEW current domain while recovered recording retains
its OLD domain. ACK/reboot retention, explicit clear/new UUID, stale-clear rejection
and v1 capture regression must pass with mixed journal history. Keep the final
valid recording intact. Do not simulate physical interrupted flash by deleting
files or truncating images; actual busy-window tests remain a separate checklist item.

## Checklist disposition

Code implemented for bounded measured logging and Python decoding/plots. Leave
'Implement acquisition timing metadata and gap records, then update Python decoding
and plots together' open until A--C pass. UTC/RTC, drift/synchronization, IVER transport,
continuous storage, hardware power-cut recovery and custom PCB acceptance remain
open. No firmware has been flashed, committed or pushed by this implementation step.

## Hardware checkpoint A passed: 2026-11-02

User flashed .242 with retained v1 media. COMMITTED4094, MCU CRC/readback and
host download passed. Agent compared Data/v242_preserved_v1_01_20261102_164719_188167/
recording.bin against the pre-upgrade max4094_after_reboot_01 copy: byte-identical;
independent v1 validation confirmed4094 pairs and UUID64f906c8-461f-44a0-955c-17e21460d71d.
SHA2567c8387eb72a0e2a49be899b3922ab7eb722c841fbb54b3adea2b5ef11d63ad35.
Two measured_init calls returned the same current domain:
ea4c5622-8fee-4e34-a665-101f6e07f722. Domain query/assignment did not change the
stored v1 recording. The recording remains COMMITTED, no ACK/clear sent by this
verification. Measured capture/persistence/gap/plot/reboot hardware tests remain
pending; proceed to checkpoint B only with explicit reclaim of this verified copy.

## Measured58-pair RAM/persistence hardware checkpoint: passed 2026-11-02

Recording0863de00-be33-4f4c-826d-d88bbb5529b8, domain
ea4c5622-8fee-4e34-a665-101f6e07f722. RAM_READY58, capacity1024; host strict v2
validation passed58 attempts/valid pairs, zero ADC errors/timeouts/events/loss,
quality0, raw trigger intervals999.450--1007.050 us, rate999.881593 Hz over57
intervals (MCU-clock-relative). No phase or independent clock accuracy claim.

Persist committed/readback verified58; MCU verify and host download passed;
recovery COMMITTED58. Diagnostic reset preceded persist, so0 acquisition attempts
during storage is intentional.4 erase/8 program calls, whole command410.385850 ms;
max erase0.076650 ms, max program9.113800 ms; zero flash errors/unsafe writes.

RAM source Data/v242_ram_58_20261102_165517_483859/recording.bin and flash copy
Data/v242_flash_58_20261102_165614_306761/recording.bin are byte-identical;
full strict host decoding passes. Equality includes timestamps, attempt IDs,
P1/P2, metadata/domain identity, manifest and CRCs, not only pressure values.
Reconstructed binary SHA256: `97a61f2050560f84c3d0f9a81b55c7f1fc74aa4234df017ee0bd0b1dcd1252a5`.

Current MCU recording remains COMMITTED58, no ACK/deletion sent by comparison.
Next: measured plot review and clean-reboot v2 retention, then explicit v2
ACK/reclaim/restart into1024-pair maximum. Controlled gap/error/overflow tests,
runtime stack measurement and remaining acceptance gates stay open.

## V2 clean-reboot retention: passed 2026-11-02

After user-reported board restart without reflash, .242 recovered COMMITTED58;
MCU CRC verification and host download passed. Post-reboot file:
Data/v242_after_reboot_58_20261102_165948_641254/recording.bin.
Agent comparison against v242_flash_58 pre-reboot copy is byte-identical; strict
v2 decoding passes58 pairs, attempts/ticks/metadata/manifest intact. Original
recording0863de00-be33-4f4c-826d-d88bbb5529b8 retains original domain
ea4c5622-8fee-4e34-a665-101f6e07f722, not relabeled to a new boot. SHA256
`97a61f2050560f84c3d0f9a81b55c7f1fc74aa4234df017ee0bd0b1dcd1252a5`.

Current recording remains COMMITTED58; no ACK or deletion sent by this check.
New current-domain assignment after reset is still to be tested, followed by v2
ACK retention/reclaim and1024-pair capture. Controlled gap/ADC/error/overflow and
runtime stack high-water acceptance remain open; clean reboot is not a physical
interrupted-program/erase test.

## New boot domain, v2 lifecycle and maximum RAM capture: 2026-11-02

Repeated init after reboot returned8db7e7df-5224-4ec5-800b-f27498ca92e7,
different from prior ea4c5622-8fee-4e34-a665-101f6e07f722; stored58-pair record
still verified. Explicit v2 ACK retained58 verified pairs; clear using matching
saved binary succeeded, recovery CLEARED. New capture899dee62-92d9-48ea-94c5-fcf239668008
used the new domain, reached RAM_READY1024/capacity1024 and downloaded to
Data/v242_ram_1024_20261102_170258_638408. Full flag indicates bounded capacity,
not circular overwriting. Strict host v2 validation passes. Persistence of this
maximum capture is next; RAM remains volatile and must not be reset/replaced.

Maximum RAM counters: {'schema': 2, 'payload_bytes': 256, 'samples': 1024, 'attempts': 1024, 'adc_timeouts': 0, 'adc_errors': 0, 'events_retained': 0, 'events_total': 0, 'events_lost': 0, 'estimated_missing_slots': 0, 'first_valid_ticks': 3536982630, 'last_valid_ticks': 3557442764, 'capture_stop_ticks': 3557443524, 'first_attempt_ticks': 3536982630, 'last_attempt_ticks': 3557442764, 'capture_accepted_ticks': 3536971474, 'data_blocks': 18, 'event_blocks': 0, 'metadata_blocks': 1, 'stream_crc32': 1150546704, 'quality_bits': 0, 'stop_reason': 2, 'ram_rejected': 0, 'unpaired_tail': 0, 'tx_drops': 0, 'tx_failures': 0, 'event_reason_or': 0, 'counter_rule': 1, 'validity_bits': 7}

Trigger interval min/max 999.450000/1007.050000 us; rate 999.993450678 Hz (MCU-relative).

## Maximum measured persistence: passed 2026-11-02

Recording899dee62-92d9-48ea-94c5-fcf239668008, domain8db7e7df-5224-4ec5-800b-f27498ca92e7.
MCU committed/readback verified1024, verify_flash passed, host measured download
validated and recovery COMMITTED1024. RAM copy
Data/v242_ram_1024_20261102_170258_638408/recording.bin is byte-identical to
Data/v242_flash_1024_20261102_170506_380267/recording.bin, including ticks,
attempt indices, values, identity/domain/clock metadata, manifest and CRCs.
SHA256 `881ff56d986240b2d304137a044ead995a1b5b5c8c85b462b69c0239a6f482a0`.

Persist20 erase/40 program calls (60 total), whole command1643.946500 ms,
max erase0.076700 ms, max program9.115400 ms. No flash errors or unsafe writes;
zero ADC attempts during intentional stopped storage. Acquisition counters were
reset after capture, so this report does not measure capture cadence.
Current recording remains COMMITTED1024/unacknowledged. No MCU writes sent by
comparison. Maximum-record clean reboot, real gap/fault/overflow acceptance and
runtime stack high-water still require tests; continuous flash acquisition is
not established.

## Maximum v2 clean-reboot retention: passed 2026-11-02

After normal restart without reflash, .242 recovered COMMITTED1024; MCU verify
and measured host download passed. Post-reboot directory:
Data/v242_after_reboot_1024_20261102_170605_111615.
Agent compared recording.bin against v242_flash_1024 pre-reboot copy: byte-identical;
strict v2 validation confirms all1024 pairs, raw ticks, attempts, clock/event/
manifest metadata and original identities. Recording899dee62-92d9-48ea-94c5-fcf239668008,
domain8db7e7df-5224-4ec5-800b-f27498ca92e7; SHA256
`881ff56d986240b2d304137a044ead995a1b5b5c8c85b462b69c0239a6f482a0`.
Current recording remains COMMITTED1024/unacknowledged; no MCU command sent by
comparison. Nominal-path measured capture, exact RAM/flash comparison, v2 lifecycle,
reboot/domain separation and measured plot generation have passed tested cases.
Do not close the entire implementation item yet: on-device controlled gap/error/
overflow acceptance and runtime stack high-water remain open. Physical interrupted
flash, UTC/RTC/clock accuracy and continuous flash acquisition remain separate.
