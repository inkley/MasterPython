> For the unflashed .242 measured candidate, follow [A--C checkpoints](reference/MEASURED_IMPLEMENTATION.md)
> as well. This runbook retains the validated .241 bounded workflow as its baseline.

# Repeatable bounded-logging acceptance procedure

Scope: .241-compatible eval-board capture, stopped persistence, verified transfer,
ACK, explicit clear, restart and clean-reboot retention. This does not certify
UTC, continuous flash acquisition, physical power cuts or the custom PCB.
Read [current status](CURRENT_STATUS.md) first.

## 1. Identify the test and run offline checks

Record date/operator, board/revision, firmware and host Git commits, dirty working
tree state, build configuration, CLI version, adapter/port, bitrate and clock.
Use unique labels per run: replace RUN below, e.g. 20261102_01. Fixed RAM/live CSV
names overwrite. A source commit alone does not identify locally modified firmware.

From MasterPython in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest test_reentry test_flash_protocol test_flash_recovery test_flash_lifecycle test_timing_protocol test_flash_v2 test_measured_pipeline test_bench_gap
```

Current: 61 host tests (40 validated-runtime regressions plus21 offline-only v2 groups). From the firmware repository:

```powershell
python tools/test_timer.py
python tools/test_log_format.py
& C:\ti\ccs1281\ccs\utils\bin\gmake.exe -s -C Debug all
python tools/verify_firmware_layout.py Debug/Inkley_PressureSensor.out
```

Baseline: 5 timer and 8 format tests, successful build/layout verification. Stop on
failure. Tool paths describe the validated lab setup, not a portable installer.

## 2. Preserve existing data; flash only if needed

Only one process owns COM5; CAN 1 Mbps. Before loading changed firmware, retain a
verified download of existing valid data. CCS: Necessary Pages Only, 16 MHz crystal,
correct GH6PM target, matching built Debug/Inkley_PressureSensor.out. Never mass
erase a retained recording. Resume target. Skip flashing if already on intended image.

```powershell
.\.venv\Scripts\python.exe InkleySensor.py
```

```text
version
flash_recovery
verify_flash
dump_flash RUN_existing_backup
```

EMPTY/CLEARED has no valid recording to verify/download; classify it before capture.
Unknown, quarantined, FAULT or CLEAR_PENDING requires investigation, not an improvised
erase. COMMITTED/ACKNOWLEDGED must verify and download successfully. Download does
not ACK or delete. Retain the unique saved directory and its recording.bin.

## 3. Acquisition-only and normal CAN timing

Stop legacy streaming. These diagnostic modes preserve retained RAM/flash. Do not
halt/step CCS or enable breakpoints during measurement.

```text
timing_stop
timing_reset
timing_start idle
```

Wait about 10 seconds:

```text
timing_stop
timing_status RUN_idle
timing_reset
timing_start can
```

Wait about 10 seconds:

```text
timing_stop
timing_status RUN_can
```

Require attempts=completed, no ADC errors/timeouts, reported CAN loss or estimated
missing slots. Review every interval outside provisional 1000 +/-10 us. Save JSON
even on failure. Expect ~1000 Hz relative to system clock; this does not calibrate
the clock or measure ADC aperture. Normal output is not CAN-saturation coverage.
An odd final acquisition may remain unpaired; host row count is not proof of
end-to-end losslessness. Retrieve diagnostics only after stopping the run.

## 4. Explicitly reclaim the single slot when ready

This deletes the matching MCU recording while retaining host files. Skip this
section if already EMPTY/CLEARED. Replace SAVED_BIN with the exact verified
download's recording.bin; quote paths containing spaces.

```text
timing_reset
ack_flash SAVED_BIN
timing_status RUN_ack
flash_recovery
verify_flash
```

Require ACKNOWLEDGED and matching verified count. ACK retains the recording.

```text
timing_reset
clear_flash SAVED_BIN
timing_status RUN_clear
flash_recovery
```

Require CLEARED. Stop after any error, timeout or unexpected state; inspect recovery
read-only. Retries can be idempotent and make no writes: inspect call counts before
claiming measured flash performance. Never clear using an unrelated recording.

## 5. Bounded capture and saved RAM source

For changed persistence code, test 1000 pairs first, then repeat the complete cycle
with 4094. Below is the maximum-size run; substitute 1000 for the smaller capture.

```text
set_buffer_size 4094
buffer_status
timing_reset
flash_capture 4094
```

Require capacity 4094. Wait at least six seconds (two for 1000 pairs), then:

```text
flash_status
timing_status RUN_capture
set_filename RUN_ram.csv
dump_buffer
```

Require RAM_READY with requested count N, N attempts/completed, no ADC errors,
reviewed timing and a complete ordered RAM dump with sequence check passed.
Do not restart capture, stream, reset or reboot before persisting this volatile RAM.
Save capture diagnostics before resetting counters for the storage measurement.

## 6. Persist and download

```text
timing_reset
persist_buffer
timing_status RUN_persist
verify_flash
dump_flash RUN_flash
flash_recovery
```

Require N committed/readback verified pairs, CRC/order/identity-valid download,
COMMITTED, zero flash errors/unsafe writes and zero ADC attempts during storage.
Expected real fresh persist calls: 1000 pairs -> 10 erase/20 program; 4094 -> 36/72.
Retry on COMMITTED only verifies; it is not a write timing test. Whole-command time
includes scans/verification. Long SysTick spacing is expected with interrupts
masked. Record this deliberate pause; do not claim uninterrupted 1 kHz. Saved sample
times remain nominal-only. Retain the new recording unacknowledged.

## 7. Verify exact RAM/flash equality

From PowerShell in MasterPython (exit CLI or use a second terminal without opening
CAN), replace paths with this run's files and execute:

```powershell
@'
import csv
from pathlib import Path
from flash_lifecycle import verified_file
ram = Path('Data/RUN_ram.csv')
flash = Path('Data/RUN_flash_TIMESTAMP')
def rows(p):
    with p.open(newline='') as f:
        return [(int(r['SampleIndex']), int(r['Pressure1']), int(r['Pressure2']))
                for r in csv.DictReader(f)]
a, b = rows(ram), rows(flash/'samples.csv')
e = verified_file(flash/'recording.bin')
assert len(a) == len(b) == e['count']
assert [r[0] for r in a] == list(range(e['count']))
assert a == b, 'RAM/flash mismatch'
print('PASS', e)
'@ | .\.venv\Scripts\python.exe -
```

Also require count equals requested N and UUID matches capture. Compare index/P1/P2,
not host-receipt versus nominal timestamp columns. Reconstructed binary equality
does not establish contents of untransferred physical pages.

## 8. Clean reboot and retention

Restart normally without reflash/erase; reconnect CLI if needed:

```text
version
flash_recovery
verify_flash
dump_flash RUN_reboot
```

Require COMMITTED, same UUID and N verified pairs. Compare downloads:

```powershell
@'
from pathlib import Path
from flash_lifecycle import verified_file
before = Path('Data/RUN_flash_TIMESTAMP/recording.bin')
after = Path('Data/RUN_reboot_TIMESTAMP/recording.bin')
assert before.read_bytes() == after.read_bytes(), 'Reboot content changed'
assert verified_file(before) == verified_file(after)
print('PASS: identical verified reconstructed binaries')
'@ | .\.venv\Scripts\python.exe -
```

For lifecycle code changes, additionally ACK/reboot/verify ACKNOWLEDGED, clear and
capture a new UUID; confirm stale prior-identity clear is rejected and new data
still verifies. Leave the final valid recording intact. No busy-window physical
interruption is tested by these steps.

## 9. Record acceptance and checkpoint

Record build/source identity, JSON reports, comparisons, UUID/count, hashes, state
transitions, failures/deviations and scope. Update both CURRENT_STATUS copies and
a dated evidence entry. Keep historical results. Raw Data is ignored by Git;
preserve verified host copies separately. A source commit does not back up them.
Commit validated changes when requested; push only when requested.

Pass scope: bounded capture with stopped storage. Separate open gates remain for
physical power cuts, continuous flash acquisition, saturated CAN, mission transport,
UTC/RTC, clock drift/synchronization and custom PCB deployment. A failed test is
not permission to discard evidence or mass erase.
