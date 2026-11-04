# Controlled ADC fault and event-detail overflow bench (.244)

Validated 2026-11-03: build1012 / version0.0.3.244. Debug build, ELF layout,
92 host tests and13 firmware-tool offline tests pass. Controlled ADC-error,
ADC-timeout and event-detail overflow board fixtures, matching RAM cleanup and
ADC restart-latch rejection passed. This checklist item is COMPLETE.
Normal protected recording899dee62-92d9-48ea-94c5-fcf239668008 must remain intact.

## What the injections exercise

All tests use the existing protected-flash UUID/CRC/full-verification guards,
boot-assigned timer domain and >=512 painted stack bytes. They refuse retained
RAM or active acquisition. Fixed requested limit64, real ADC triggers and raw
hardware timer ticks; no pressure values or event records are fabricated.

- adc_error: after15 valid pairs, read the next real conversion but deliberately
  reject its result through the normal ADC-error branch. Expect15 valid pairs,
  16 attempts,1 ADC error,0 timeouts, stop_reason3, ADC_FAILURE quality bit1 and
  terminal event reason bit2 at zero-based attempt15 without a related valid sample.
- adc_timeout: at attempt15 ignore ADC completion until the existing bounded
  polling timeout fires. Expect15 valid pairs,16 attempts,1 timeout,0 ADC errors,
  stop_reason3, ADC_FAILURE and terminal event reason bit1. A late/pending FIFO
  result must never become another pair; acquisition stays latched until reset.
- event_overflow: wait >=100000 timer ticks (5ms nominal) after every valid pair.
  Real subsequent trigger intervals produce timing/gap events until detail33
  cannot fit. Expect32 retained,33 total,1 lost, stop_reason4, EVENT_DETAIL_LOSS
  quality bit16, sticky overflow reason1024, zero ADC faults. Require acquisition
  stopped below64 pairs and stable counters on a second status/download.
  Exact sample count and missing-slot estimate depend on observed intervals.

Timing events may accompany ADC faults; do not require an exact total for them.
These controlled tests exercise software fault handling, not analog/electrical
ADC malfunction or independent-supply behavior. Worst-case stack remains open.

Metadata schema2 feature_bits values:1 gap,2 adc_error,3 adc_timeout,4 event_overflow.
Exports identify MCU_BENCH_RAM and bench_profile. Persist is blocked on the MCU;
normal flash export, ACK and CLEAR using a bench file are rejected by the host.
New capability0x30 selector9=0x424E4302; start opcodes0x3A/3B/3C respectively take
the protected manifest CRC and use existing request/target identity staging.
0x39 gap and0x3D matching verified RAM discard remain compatible with .243.

## Board sequence (one profile per run)

Exit the CLI. Load Debug/Inkley_PressureSensor.out with Necessary Pages Only,
GH6PM target and16MHz crystal. Run from physical startup so ResetISR paints the
stack; yesterday CCS post-load startup bypassed painting. Restart updated CLI.
Do not mass erase or clear the protected recording.

```text
version
flash_recovery
verify_flash
stack_status
timing_reset
measured_bench_fault event_overflow Data/v242_after_reboot_1024_20261102_170605_111615/recording.bin
```

Require .244, protected COMMITTED1024, successful verify, usable stack report and
successful bench start64. Stop on a failed guard. Wait1 second, then:

```text
flash_status
dump_measured bench_event_overflow
timing_status bench_event_overflow
stack_status
verify_flash
dump_flash v244_protected_after_event_overflow
flash_status
```

Review recording_metadata.json summary and events.json against expectations above.
Require RAM_READY, no later acquisition progress, and zero flash erase/program
calls in timing diagnostics. Compare the normal flash recording.bin byte-for-byte
(or SHA256) to the protected backup:
881ff56d986240b2d304137a044ead995a1b5b5c8c85b462b69c0239a6f482a0.
Save CLI output including stack and restart-rejection responses.

After reviewing and retaining the export, use its actual saved directory:

```text
measured_bench_discard Data/ACTUAL_BENCH_DIRECTORY/recording.bin
flash_recovery
verify_flash
```

Require protected COMMITTED1024 unchanged. Repeat with adc_error and adc_timeout
in place of event_overflow, using distinct export/timing labels. After each ADC
fault, discard matching saved bench RAM, then retry measured_bench_fault with the
same protected normal backup: require error11 (ADC fault latched), no capture.
Reset/power-cycle before the next profile, re-query version/recovery/verify/stack
and timing_reset. Never reset before saving disposable RAM evidence. After final
reset verify protected flash again. No ACK, CLEAR or persist command is required.

Actual board evidence and cleanup confirmations are recorded below. Earlier
pending statements describe intermediate checkpoints; the final acceptance
entry records completion.


## Observed event-overflow result - 2026-11-03

.244 board export59d2223e-80bc-4971-80dd-7b78cddc3101 decoded successfully:
34 attempts/valid pairs,32 retained events,33 total,1 lost; stop_reason4,
quality_bits26 (timing/estimated-gap/detail-loss), event_reason_or1048 including
sticky overflow1024. Zero ADC errors/timeouts. Diagnostic intervals5065.300 to
5099.250us,132 estimated missing slots, zero CAN drops/errors/overruns and zero
flash erase/program calls. RAM_READY34 remained stable on the later status query.
Observed painted stack unused3600/4096 bytes, not worst-case acceptance.
Bench: Data/bench_event_overflow_20261103_142057_019859; timing:
Data/bench_event_overflow_20261103_142057_053087.json. Protected export:
Data/v244_protected_after_event_overflow_20261103_142058_989796. Its binary was
compared directly to the .242 reboot backup: byte-identical, SHA256
881ff56d986240b2d304137a044ead995a1b5b5c8c85b462b69c0239a6f482a0.
Controlled event-detail overflow acceptance passed this fixture. Cleanup is still
PENDING: operator entered the literal ACTUAL_BENCH_DIRECTORY placeholder, so no
discard was sent. Use Data/bench_event_overflow_20261103_142057_019859/recording.bin
for matching RAM discard, then query flash_recovery and verify_flash.
ADC-error/timeout hardware acceptance remains OPEN; keep the combined checklist
item open until those tests and cleanup are reviewed.


2026-11-03 overflow cleanup confirmed by operator: matching saved bench RAM
was discarded successfully; protected flash reverified and retained. Subsequent
flash_recovery returned COMMITTED1024 and verify_flash passed1024 pairs.
Overflow fixture including cleanup is complete. ADC-error/timeout tests remain OPEN.


2026-11-03 ADC-error capture verified from saved binary:
4510175b-00bc-4252-8e05-8f293b00b8d2, profile2;15 valid pairs/16 attempts,
1 ADC error/0 timeouts, stop_reason3, quality_bits1. One terminal ADC_ERROR
 event at attempt15, reason2, validity7 (no related valid sample); no lost
 events or estimated missing slots. Diagnostics:999.450-1000.000us, zero CAN
 losses/errors/overruns and zero flash calls. Observed stack unused3552/4096
 bytes (544 touched/unknown), not worst-case acceptance. Protected flash CRC
 verification passed1024 pairs. Export:
Data/bench_adc_error_20261103_142401_651539; timing:
Data/bench_adc_error_20261103_142401_686604.json.
Capture/error reporting passed this fixture. Matching RAM cleanup and error11
restart-latch check remain PENDING; timeout hardware test remains OPEN.


2026-11-03 ADC-error cleanup/latch confirmed by operator: matching bench RAM
discarded, recovery COMMITTED1024, flash verification passed1024 pairs. Retry
without reset rejected with ADC fault latched; subsequent status COMMITTED,
RAM pairs0. Controlled ADC-error fixture including restart latch is complete.
ADC-timeout hardware validation remains OPEN.


2026-11-03 ADC-timeout capture verified from saved binary:
8380fd18-80d1-4a23-b906-b7ffaf4cb6df, profile3; fresh timer domain
7fe94c9e-eb48-42cf-9d31-3e68b20ddf77.15 valid pairs/16 attempts,
1 timeout/0 ADC errors, stop_reason3, quality_bits1. One terminal ADC_TIMEOUT
 event at attempt15, reason1, validity7 (no related valid sample); no lost events
 or estimated missing slots. Diagnostics999.450-1000.000us, zero CAN losses/
 errors/overruns and zero flash calls. Stack unused3600/4096 bytes; protected
 flash verification passed1024 pairs. Export:
Data/bench_adc_timeout_20261103_142552_686154; timing:
Data/bench_adc_timeout_20261103_142552_719487.json.
Timeout capture/reporting passed this fixture. Matching RAM cleanup, timeout
restart-latch rejection and final post-reset flash verification remain PENDING.


## Final acceptance - 2026-11-03

Operator confirmed timeout bench RAM discard, protected flash re-verification,
COMMITTED1024 recovery, and restart rejection with ADC fault latched. Following
status was COMMITTED with RAM pairs0. After the requested power-cycle/CLI restart
sequence, version reported0.0.3.244, recovery COMMITTED1024 and flash CRC/readback
verification passed1024 pairs. Physical cycling is operator-run; the terminal
transcript itself shows CLI restart and the subsequent verification responses.

Controlled ADC-error handling and event-detail overflow checklist item COMPLETE:
overflow stopped with32 retained/33 total/1 lost plus sticky flags; ADC-error and
timeout stopped at15 valid/16 attempts, preserved terminal fault detail and
rejected restart without reset. Matching disposable RAM was discarded after each
saved export. Normal flash remains protected; overflow post-test download was
byte-identical to the .242 backup. Final post-reset check was MCU CRC/readback,
not a new host byte-for-byte download. No independent power-supply, physical
interrupted-flash or worst-case storage/lifecycle stack acceptance is claimed.
