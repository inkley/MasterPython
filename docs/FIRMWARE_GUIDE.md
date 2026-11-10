# Firmware operator and development guide

This guide is the day-to-day reference for operating and developing the Inkley
two-channel pressure-sensor firmware. It covers the validated eval-board workflow,
command intent, recording protection, recovery, and current operating limits.

Use these documents with it:

- [Current status](CURRENT_STATUS.md): authoritative hardware checkpoint, retained
  recording, evidence, and open work.
- [Acceptance procedure](ACCEPTANCE_PROCEDURE.md): formal bounded-logging test
  sequence and pass criteria.
- [Documentation index](README.md): design references and historical evidence.

Update this guide when commands, required setup, state transitions, capacities, or
operating limits change. Do not use historical notes as the current procedure.

## 1. Current validated configuration

As of 2026-11-10:

- Eval board: TI EK-TM4C123GXL Rev B.
- Target MCU: TM4C123GH6PM; eval silicon revision 7.
- Firmware: 0.0.3.244.
- System clock: 20 MHz.
- Acquisition: nominal 1,000 P1/P2 pairs/s.
- Host transport: SLCAN/CANable at 1 Mbps; COM5 was last validated.
- Command CAN ID: 0x107; response ID: 0x108; broadcast ID: 0x7DF.
- Measured v2 capacity: 1,024 pairs.
- Legacy bounded capacity: 4,094 pairs.
- Storage: one retained recording; acquisition stops during persistence.

The current retained MCU recording is a normal, unacknowledged COMMITTED v2
recording:

- Recording UUID: `dda07164-f941-4814-b418-f732c120bf43`
- Timer domain: `111d503b-0946-4e56-beb1-870cefaa3d24`
- Count: 1,024 pairs
- Verified host SHA-256:
  `e3920109235c1f8c977f3f82e7196d7e37cc48e6af4b8121615f1abe302b8d77`

Preserve it unless a later test explicitly requires ACK and reclamation.

## 2. Host setup and launch

From the MasterPython repository in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe InkleySensor.py
```

Only one process may own the CAN serial port. Close other CLI instances before
starting. Use these commands if the adapter is not on COM5:

```text
scan_ports
set_channel COMx
system_info
```

Use `help COMMAND` for command-specific syntax. Set an evidence directory before
a run:

```text
set_outdir Data/RUN_LABEL
```

Use a unique, date-based label such as `stack_readback_20261110_01`. Raw Data is
ignored by Git; a source commit does not back up recordings.

## 3. CCS, reset, and normal operation

CCS does not need to be open or active when the intended firmware is already
flashed. The Python CLI communicates with the MCU over CAN.

For ordinary CLI work:

- Leave CCS alone.
- Do not select Build, Debug, Load, Run, halt, step, or set breakpoints.
- Leave SW3 on the power source actually in use.
- Use the physical RESET button when a fresh firmware startup is required.
- Treat a power cycle as actual removal and restoration of all possible board power
  paths. Moving SW3 alone is not proof of a full power cycle.

VS Code may launch the Python CLI through `debugpy`; that does not mean CCS is
debugging the MCU.

CCS is required when building, flashing, attaching a hardware debugger, or reading
target registers that are not exposed through the CLI. Avoid debugger halts during
timing measurements.

## 4. Safe read-only startup

Start every hardware session by identifying the firmware and storage state:

```text
version
flash_recovery
flash_status
```

If recovery reports COMMITTED or ACKNOWLEDGED, verify the recording:

```text
verify_flash
```

Interpret the result before sending any write command:

| State | Meaning and action |
|---|---|
| EMPTY or CLEARED | No valid retained recording; a new capture may be started. |
| RAM_READY | Volatile capture exists. Export it before reset; persist it if required. |
| COMMITTED | Valid retained recording. Verify and download it; do not clear merely to resume work. |
| ACKNOWLEDGED | Transfer was durably acknowledged; recording is still retained and verifiable. |
| CLEAR_PENDING | A clear was interrupted or is uncertain. Stop and investigate recovery. |
| COMMITTED_WITH_QUARANTINE | Valid recording plus unknown media. Preserve it and investigate. |
| FAULT, JOURNAL_UNCERTAIN, unknown, or damaged | Stop. Use read-only recovery and inspect evidence. |

A timeout or missing command response makes the outcome unknown. Query
`flash_status` and `flash_recovery` before considering any retry.

## 5. Protecting an existing recording

For COMMITTED or ACKNOWLEDGED media:

```text
verify_flash
dump_flash RUN_existing_backup
flash_recovery
```

`dump_flash` verifies and reconstructs a host `recording.bin`; it does not ACK,
erase, or change the MCU recording. Retain the timestamped output directory.

Before clearing a recording:

1. Verify the saved `recording.bin` with the host tools.
2. Record its UUID, count, and SHA-256.
3. Confirm it matches the MCU recording.
4. Keep at least one additional verified copy outside the MCU.
5. Use that exact saved binary for both ACK and clear.

Never use a file from another recording, a bench-injection export, or a literal
placeholder path.

## 6. Measured v2 capture and persistence

A normal measured capture requires flash state EMPTY or CLEARED. It will not
overwrite COMMITTED or ACKNOWLEDGED media.

Start and save a maximum measured capture:

```text
timing_reset
measured_capture 1024
```

Wait at least two seconds for auto-stop, then:

```text
flash_status
timing_status RUN_capture
dump_measured RUN_ram
stack_status
```

Require RAM_READY with 1,024 pairs, attempts equal to completed pairs, and no
unexplained ADC faults, timing gaps, or reported CAN losses. `dump_measured`
exports the volatile RAM source without deleting it.

Do not reset, start another capture, or discard RAM before a successful export and
the intended persistence decision.

Persist stopped RAM:

```text
timing_reset
persist_buffer
timing_status RUN_persist
verify_flash
dump_flash RUN_flash
flash_recovery
flash_status
```

Require COMMITTED with the requested count, zero ADC attempts during persistence,
no flash errors, and verified RAM/flash identity and content. For a fresh measured
1,024-pair persistence, the observed .244 path used 20 erase and 40 program calls
and paused acquisition for about 1.644 seconds.

Compare the RAM and flash `recording.bin` files byte-for-byte. The acceptance
procedure contains a reusable comparison script.

## 7. ACK and identity-bound reclamation

ACK records that a matching, verified host transfer exists. It retains the MCU
recording:

```text
timing_reset
ack_flash Data/ACTUAL_DIRECTORY/recording.bin
timing_status RUN_ack
flash_recovery
verify_flash
```

Require ACKNOWLEDGED, the expected pair count, and successful verification.

Clear is a separate, destructive MCU operation. It requires a durable ACK and the
same verified identity:

```text
timing_reset
clear_flash Data/ACTUAL_DIRECTORY/recording.bin
timing_status RUN_clear
flash_recovery
flash_status
```

Require CLEARED with zero pairs. Do not run `verify_flash` after a successful
clear because no committed recording remains. Host evidence is retained.

Never ACK or clear as a routine startup step.

## 8. Recovery workflow

`flash_recovery` is read-only. It scans and classifies the storage partition but
does not erase or repair it.

Use this sequence after an unexpected reset, timeout, or uncertain lifecycle
operation:

```text
flash_recovery
flash_status
```

For COMMITTED or ACKNOWLEDGED:

```text
verify_flash
dump_flash RUN_recovery_backup
```

Stop after an unexpected classification. Preserve terminal output and saved files.
Do not improvise an erase, mass erase the MCU, or reflash over retained evidence.

Physical interruption during active program/erase remains an open acceptance item.
The synthetic scratch fixtures do not certify real power-loss recovery.

## 9. Timing diagnostics

Diagnostic acquisition leaves retained RAM and flash unchanged.

Acquisition-only timing:

```text
timing_stop
timing_reset
timing_start idle
```

Run for about ten seconds, then:

```text
timing_stop
timing_status RUN_idle
```

Normal packed-CAN timing:

```text
timing_reset
timing_start can
```

Run for about ten seconds, then:

```text
timing_stop
timing_status RUN_can
```

Review attempts/completed pairs, ADC errors/timeouts, interval excursions,
estimated missing slots, CAN queue drops, transmit failures, and receive overruns.
The provisional interval screen is 1,000 +/- 10 us. Save and explain every
exception rather than reporting an unconditional pass.

MCU trigger ticks are CPU-clock-relative. They are not independently calibrated
time, UTC, ADC aperture time, or proof of host delivery. Host CSV timestamps are
receipt-based estimates. One terminal unpaired host sample may occur.

## 10. Observed stack watermark

`stack_status` reports the remaining boot-painted portion of the 4,096-byte MSP
stack reservation:

```text
stack_status
```

The 2026-11-10 storage/lifecycle run stayed at 3,600 bytes pattern-unused
(496 touched/unknown) across recovery, verification, download, ACK, clear, capture,
RAM export, persistence, and committed download.

This is useful observed-path evidence, not exact peak-stack measurement or absolute
worst-case proof. Conservative unpainted/reserved frames, lazy FPU stacking, and
pattern collisions limit the method. A fresh RESET-button startup is required to
start a new watermark session. Stop stress testing if the report is unavailable or
below the firmware's 512-byte bench threshold.

## 11. Command quick reference

| Command group | Purpose |
|---|---|
| `version`, `system_info` | Identify firmware and host interface. |
| `scan_ports`, `set_channel` | Locate and select the CAN adapter. |
| `set_outdir`, `set_filename` | Select host evidence destinations. |
| `start`, `stop`, `readings` | Legacy realtime CAN logging and latest host-observed values. |
| `buffer_status`, `dump_buffer` | Inspect/export legacy RAM buffering. |
| `measured_init` | Assign or query the boot timer-domain UUID. |
| `measured_capture N` | Start a bounded timestamped v2 RAM capture, maximum 1,024 pairs. |
| `dump_measured LABEL` | Verify/export frozen measured RAM without deleting it. |
| `flash_status` | Read current RAM/flash lifecycle state. |
| `persist_buffer` | Persist stopped RAM to blank/cleared reserved flash. |
| `verify_flash` | Verify committed flash CRC, structure, and readback. |
| `dump_flash LABEL` | Verify/download committed flash without ACK or deletion. |
| `ack_flash PATH` | Durably acknowledge the matching verified transfer; retain flash. |
| `clear_flash PATH` | Delete only the matching ACKNOWLEDGED recording. |
| `flash_recovery` | Read-only partition classification. |
| `timing_*` | Reset, run, stop, and export volatile diagnostics. |
| `stack_status` | Read the observed boot-painted MSP watermark. |

`read_flash` is a historical alias for `dump_buffer`; it does not download the
persistent flash recording.

The `measured_bench_gap`, `measured_bench_fault`,
`measured_bench_discard`, and `flash_scratch` commands are controlled test
fixtures. Use them only with their reference runbooks and matching protected
evidence.

## 12. Power and electrical limits

Eval-board documented input is 4.75-5.25 V through Debug USB or Device USB. SW3
selects the source. The VDD jumper remains installed for normal operation so the
onboard regulator supplies the MCU at 3.3 V.

For the planned independent-power test:

- Feed regulated 5 V and common ground through a verified USB power adapter/cable
  into Device USB.
- Set SW3 to Device with power off.
- Disconnect PC Debug USB.
- Keep the CAN-to-USB adapter connected to the PC for data.
- Verify adapter/cable continuity, polarity, board 5 V, and regulated 3.3 V before
  functional testing.

The prior 10 mA bench limit powered only the two pressure sensors; it is not an
approved limit for the sensors, eval board, and CAN transceiver together. Establish
and record an appropriate combined current limit during the separate power test.
Do not apply 5 V to MCU_PWR or the 3.3 V rail.

Pressure values are raw 12-bit ADC counts unless calibrated. The RC input filter
does not reduce steady-state sensor voltage. Sensor output must remain within the
MCU ADC input range.

## 13. Current firmware limits

- Only one retained recording is supported.
- Measured capture is limited to 1,024 pairs, about 1.024 seconds nominal.
- Legacy capture is limited to 4,094 pairs, about 4.094 seconds nominal.
- Acquisition stops during persistence and lifecycle flash operations.
- Continuous flash logging is not implemented or validated.
- UTC is unavailable; timer domains distinguish boot-relative clocks.
- Independent oscillator accuracy and drift are unvalidated.
- End-to-end host losslessness is not certified.
- Physical interruption during flash program/erase is unvalidated.
- Independent-supply and custom-PCB operation remain unvalidated.
- Custom-PCB silicon revision/DID0 remains to be confirmed.
- Capacity and wear policy are documented, but automatic wear leveling/enforcement
  is not implemented.

Do not infer continuous operation, UTC accuracy, physical power-loss tolerance, or
custom-board acceptance from a bounded eval-board pass.

## 14. Build and flash only when required

The currently validated `.244` image uses the CCS `Debug` configuration and TI
Arm Compiler 20.2.7.LTS. Its generated compiler command includes debug symbols
(`-g`) and does not include an optimization-level option, so the validated
application build is unoptimized. The separate library-project defaults are not
evidence of the options used to compile this application; use the generated
`Debug/subdir_rules.mk` command line as the authoritative record.

Treat any change to compiler version, build configuration, optimization level,
link-time optimization, floating-point mode, or ABI as a new firmware build. After
such a change, clean-rebuild, rerun the offline checks, reflash, and repeat the
relevant timing, stack, flash-lifecycle, and power-cycle acceptance tests before
claiming equivalence to `.244`.

From the firmware repository:

```powershell
python tools/test_timer.py
python tools/test_log_format.py
& C:\ti\ccs1281\ccs\utils\bin\gmake.exe -s -C Debug all
python tools/verify_firmware_layout.py Debug/Inkley_PressureSensor.out
```

Before loading firmware, verify and download any retained recording. In CCS use the
correct GH6PM target, 16 MHz external crystal setting, Necessary Pages Only, and the
matching built `.out`. Never mass erase retained evidence. Resume the target after
loading.

A source commit does not identify an uncommitted local build. Record firmware
version, build/source identity, configuration, and dirty worktree state in
acceptance evidence.

## 15. Evidence and maintenance

For each hardware checkpoint record:

- Date, operator, board/revision, firmware version, and source/build identity.
- CAN adapter/port, bitrate, power arrangement, and sensor condition.
- Starting and ending storage state.
- Recording and timer-domain UUIDs, counts, hashes, and saved paths.
- Timing JSON, stack readings, state transitions, and command transcript.
- Failures, deviations, limitations, and the next troubleshooting step.
- Exact scope of what passed and what remains unvalidated.

When behavior changes:

1. Update this guide's commands and limits.
2. Update both repositories' `docs/CURRENT_STATUS.md` copies.
3. Update the acceptance procedure if pass criteria or required sequencing changed.
4. Add or revise the relevant reference runbook.
5. Run appropriate offline checks.
6. Commit validated changes when requested; push only when requested.
