# Current project status

Updated 2026-11-02. This is the authoritative status snapshot; archived notes
retain the evidence and decisions of earlier checkpoints. Update both repositories'
copy together. Firmware baseline: build 1009, CLI version **0.0.3.241**.
Candidate implementation: **.242/build1010** now includes measured1024-pair v2
capture, gap events, stopped persistence/recovery/lifecycle and Python measured
exports/plots. Debug build/layout checks and89 offline tests pass. Flashed on eval; checkpoint A (v1 retention/domain initialization) passed;
measured acquisition/storage hardware acceptance remains pending. [Read-only upgrade checkpoint](reference/MEASURED_IMPLEMENTATION.md)
comes before any reclamation. The validated scope below still describes .241.

Validated implementation commits: firmware `8c2fb0c`, host `e88b44b`.
This documentation reorganization does not change firmware or its image.

## Validated scope

- Eval target TM4C123GH6PM silicon revision 7; deployment GH6PM variant confirmed,
  deployment silicon revision pending DID0 readout when debug access is available.
- Verified 20 MHz configuration and nominal 1 kHz software-trigger pair cadence.
  P1/AIN0 then P2/AIN1 are sequential; physical aperture offset is unmeasured.
- GlobalTimer increments on serviced SysTicks, including early-return paths;
  modular heartbeat comparison passed the rollover checkpoint. GlobalTimer does
  not count unserviced hardware ticks and is not continuous wall time through stalls.
- Bounded RAM captures through 4094 pairs, stopped-acquisition flash persistence,
  CRC/count/identity-checked CAN retrieval and exact RAM/flash sample comparison.
- Clean-reboot retention, durable ACK retaining data, explicit ID-bound clear,
  capture restart with a new UUID, stale clear rejection.
- Synthetic torn-marker/corrupt-CRC fixtures, quarantine and normal scratch erase
  preserved the protected recording. Physical interrupted program/erase is untested.

## Measured timing (.241, eval board)

| Run | Completed pairs | Rate (Hz) | Trigger interval min/max (us) |
|---|---:|---:|---:|
| Acquisition only | 13551 | 1000.000000 | 1000.000 / 1000.000 |
| Normal packed CAN | 10539 | 1000.000052 | 999.450 / 1000.050 |
| Bounded maximum capture | 4094 | 1000.000000 | 999.950 / 1000.050 |

No observed ADC errors/timeouts, +/-10 us interval violations, estimated missing
slots or reported CAN overruns in these runs. CAN host CSV had 10538 pairs versus
10539 acquisitions, consistent with one terminal unpaired sample; end-to-end
losslessness is not certified. Timing is MCU-clock-relative, not independently
calibrated, UTC, or a measurement of the ADC aperture. Instrumentation adds work.

| Stopped storage operation | Erase/program calls | Whole operation |
|---|---:|---:|
| ACK, 1000-pair recording | 1 / 2 | 411.985950 ms |
| Clear, 1000-pair recording | 11 / 2 | 738.352500 ms |
| Persist 1000 pairs | 10 / 20 | 749.765250 ms |
| Persist 4094 pairs | 36 / 72 | 2402.929200 ms |

ADC attempts during each storage operation were zero by design; flash errors
were zero. Whole durations include scans/verification/processing, not just flash
calls. Maximum-size persist's longest program call was 9.145200 ms, longest erase
0.076750 ms (freshly cleared pages), maximum serviced SysTick spacing 1506.318900
ms. These are observed values, not aged-flash or worst-case guarantees.

## Retained recording and evidence

MCU recording at this checkpoint: **COMMITTED, unacknowledged, 4094 pairs**, UUID
`64f906c8-461f-44a0-955c-17e21460d71d`. Documentation work sends no MCU commands.
All local paths below are relative to the MasterPython repository:

- RAM source: `Data/max4094_ram_before_01.csv`.
- Before reboot: `Data/max4094_flash_01_20261102_150925_176265/`.
- After reboot: `Data/max4094_after_reboot_01_20261102_151106_784281/`.
- Timing: `Data/max4094_capture_01_20261102_150808_303400.json` and
  `Data/max4094_persist_01_20261102_150921_704375.json`.

All 4094 ordered (index,P1,P2) triples matched RAM/flash. Reconstructed binary
before/after reboot was byte-identical; SHA256
`7c8387eb72a0e2a49be899b3922ab7eb722c841fbb54b3adea2b5ef11d63ad35`.
Untransferred physical journal/scratch areas are FF placeholders, not read bytes.
Data is Git-ignored; commits do not back up these recordings. Keep verified host
copies before any explicit reclaim. Evidence detail is indexed in docs/README.md.

## Storage and deployment boundaries

256 KiB flash / 32 KiB SRAM. Application [0x00000,0x20000); logging
[0x20000,0x40000), 1 KiB erase pages. No separate bootloader reservation is currently
implemented; introducing one requires a new layout review. Compact format capacity
estimates are not achieved capture duration: current capture ceiling is 4094 pairs,
about 4.094 s nominal, and only one retained recording. 10--30 s captures and
continuous logging are goals, not implemented capabilities. RAM stages acquisition.

Policy definitions cover retention, full storage, overwrite and wear budgets;
automatic wear enforcement/leveling is not implemented. IVER backseat CPU is the
intended external sink; transport/throughput/outage requirements remain unknown.

## Open work, in recommended order

1. Time-model definition is documented in [TIME_MODEL](reference/TIME_MODEL.md):
   raw trigger-proxy ticks, explicit timer domains/recording IDs, immutable UTC
   mappings and conservative uncertainty. Accuracy goals remain provisional.
   Review mission tolerance; settle versioned encoding and RAM budget next.
2. Measured timestamps/gaps and Python decoding/plots are implemented in .242
   candidate; run hardware acceptance before checking this item complete.
3. Evaluate RTC/battery/PCB requirements against UTC-retention requirements.
4. Test drift, reboot/power loss and resynchronization of that implementation.
5. Obtain IVER transport, sustainable throughput and expected outage requirements;
   choose/implement continuous storage architecture only after this evaluation.
6. Validate controlled physical interrupted programming/erase and lifecycle journal
   interruption with disposable data; plan this separately from routine acceptance.

The bounded .241 checkpoint passed. The broad timing/overrun item is addressed
only for normal CAN traffic and deliberately stopped flash operations. Continuous
acquisition through flash, saturated CAN, physical power cuts, clock accuracy,
UTC retention and deployment-board acceptance remain open.

Time model is defined for planning, not implemented in .241 recordings. UTC,
per-sample measured timing and resynchronization acceptance remain open.

Measured metadata/RAM design: [METADATA_V2](reference/METADATA_V2.md) selects16-byte
raw-tick/attempt/P1/P2 records,1024 measured pairs,32 event details and a shared
legacy4094-pair arena. Planned SRAM26536/32768,6232-byte margin; not an actual v2
link or runtime stack result. .241 and retained v1 data are unchanged. Offline v2 codec/fault checks now pass; capability/domain-handshake design is
next before firmware. Accuracy goals remain provisional per user confirmation.

Offline v2 checkpoint: host reference encoder/decoder and read-only recovery
classifier implemented separately from the v1 CLI.21 new test groups pass;
61 host +13 firmware offline tests pass. See [offline v2 evidence](reference/OFFLINE_V2_CODEC.md).
Ambiguous interrupted reclaim remains protected without an erase executor.
That offline checkpoint did not establish MCU support. The newer .242 candidate
implements capture/protocol/storage and host integration; hardware acceptance
remains pending (see MEASURED_IMPLEMENTATION). Physical fault acceptance is open.

Measured implementation candidate:76 host +13 firmware offline checks pass (89).
Linked Debug occupied span25136, remaining7632 bytes, stack4096; runtime high-water
and hardware timing unmeasured. Current MCU recording has not been touched.

.242 checkpoint A: retained4094-pair v1 download is byte-identical to .241 backup;
repeated domain initialization stable. Checkpoint B measured capture is next.

.242 measured58-pair capture/persist/download passed strict v2 validation and
byte-identical RAM/flash comparison. Current recording is COMMITTED58, UUID
0863de00-be33-4f4c-826d-d88bbb5529b8; earlier4094 v1 recording was explicitly
ACKed/cleared with host backup retained. V2 clean-reboot retention of58 pairs passed byte-identical comparison;
new boot-domain assignment, v2 ACK/reclaim, maximum and gap acceptance remain pending.

.242 maximum measured1024-pair capture/persist/download passed full byte-identical
RAM/flash comparison. Persist1.6439465s,20/40 calls, no flash errors. Current MCU
recording is COMMITTED1024 (899dee62-92d9-48ea-94c5-fcf239668008), unacknowledged;
keep it intact. Maximum reboot and gap/fault/stack acceptance remain pending.

.242 maximum1024-pair clean-reboot retention passed byte-identical comparison,
including original time-domain identity. Current COMMITTED recording remains
899dee62-92d9-48ea-94c5-fcf239668008. Controlled on-device gap/error/overflow
and runtime stack high-water checks remain pending before full item acceptance.

Unflashed .243/build1011 bench candidate: a protected-record-bound RAM-only64-pair
capture introduces one nominal5ms service delay. Metadata schema2 marks bench
data; persistence/flash ACK/CLEAR of that bench are blocked. Observed MSP watermark
reporting added. Normal .242 recording remains intact; no MCU commands sent by
preparation. See [short bench runbook](reference/BENCH_GAP_STACK.md). ADC/error/
overflow and worst-case stack acceptance remain open.99 offline checks pass.

### .243 observed bench result — 2026-11-02

RAM-only gap capture 808f6dc2-15a8-48ed-b8d6-d992e5208c07 completed64/64 pairs.
Two events retained, none lost: late/estimated-gap at attempt16 (4 estimated
missing slots), then early interval at attempt17. Diagnostic trigger range
927.500–5073.100us; zero ADC failures, CAN drops/overruns, or flash calls.
Event ticks describe pre-trigger timestamps; diagnostic intervals are a separate
instrumentation point. Stack watermark after a physical startup and bench export:
3600/4096 bytes pattern-unused (496 touched/unknown), not worst-case acceptance.
CCS post-load startup initially bypassed stack painting; power cycling enabled it.
Protected1024-pair flash copy after bench is byte-identical to .242 reboot backup:
SHA256 881ff56d986240b2d304137a044ead995a1b5b5c8c85b462b69c0239a6f482a0.
Bench export: Data/bench_gap_01_20261102_173144_511710; protected export:
Data/v243_protected_after_gap_20261102_173148_436910. Bench RAM discard pending.
Controlled gap reporting passed this fixture; ADC-error/event-overflow hardware
checks, worst-case stack and physical interrupted-flash tests remain OPEN.

Final bench cleanup confirmed by operator: matching disposable bench RAM discarded;
recovery COMMITTED1024 and flash CRC verification passed. Protected recording
899dee62-92d9-48ea-94c5-fcf239668008 remains intact. Resume with ADC-error,
event-overflow and broader stack checks; do not clear the protected recording.
