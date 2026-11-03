# MasterPython: Inkley pressure sensor tools

Host CLI, verified recording retrieval and quick-look analysis for two independent
differential-pressure channels. Firmware companion: [PressureSensor](https://github.com/inkley/PressureSensor).

- [Current validated state and open work](docs/CURRENT_STATUS.md)
- [Repeatable acceptance procedure](docs/ACCEPTANCE_PROCEDURE.md)
- [Specifications and historical evidence index](docs/README.md)
- [Development quick start](REENTRY_GUIDE.md)

## Setup and launch

Validated Windows setup uses a SLCAN/CANable adapter at 1Mbps, last tested on COM5.
Only one process owns the port. Select your actual adapter port with scan_ports /
set_channel. Install dependencies using the project's Python environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe InkleySensor.py
```

requirements-lock.txt records the previously captured environment; requirements.txt
is the maintained dependency input. Firmware .241 is the validated baseline.

Candidate .242 adds measured_capture, dump_measured and raw-tick-aware plots;
[hardware acceptance is pending](docs/reference/MEASURED_IMPLEMENTATION.md).

## Main CLI workflows

| Commands | Purpose |
|---|---|
| version, scan_ports, set_channel, system_info | Identify firmware/interface |
| start, stop, set_filename, set_outdir | Legacy realtime host CSV logging |
| set_buffer_size, buffer_status, dump_buffer | RAM staging and ordered dump |
| flash_capture N, flash_stop, flash_status | Bounded RAM capture; maximum 4094 pairs |
| persist_buffer, verify_flash, dump_flash LABEL | Stopped flash persistence and verified download |
| ack_flash PATH | Durably acknowledge verified host binary; keep MCU recording |
| clear_flash PATH | Explicitly erase the matching ACKed recording |
| flash_recovery | Read-only recovery classification |
| timing_reset, timing_start idle/can, timing_stop, timing_status LABEL | Volatile timing diagnostics |

Use `help COMMAND` for syntax. `read_flash` is a historical alias for RAM
`dump_buffer`; actual persistent storage uses `dump_flash`. Existing committed
recordings prevent a new capture until explicit reclaim. Follow the acceptance
procedure rather than clearing data as part of startup. Bench scratch operations
are described in archived firmware fault-test evidence, not a normal user workflow.

CAN IDs: command 0x107, replies 0x108, broadcast 0x7DF. Normal realtime output packs
two P1/P2 pairs per frame (~500 frames/s at nominal 1000 pairs/s). Pressure values
are raw 12-bit ADC counts unless calibrated by analysis. Data is Git-ignored;
source commits do not back up recordings. Fixed CSV names overwrite; flash dumps
and analysis use new timestamped destinations.

Measured mode has1024-pair capacity; legacy mode remains4094. measured_init
assigns/queries a boot timer domain without resetting its clock or clearing data.

## Analysis

```powershell
.\.venv\Scripts\python.exe analyze_pressure.py Data\YOUR_CAPTURE.csv
```

Use --fs for nominal sample rate (default 1000 Hz), --no-filter or --lowpass for
filtering, --calibration for independent P1/P2 coefficients, --outdir for results.
Without calibration, counts convert to volts with default Vref 3.3 V. Outputs include
processed CSV/NPZ/MAT, metadata and pressure PNG in Data/Results. P1 and P2 each
measure differential pressure independently; no P1-minus-P2 result is implied.
Host receipt times and nominal flash sample times are not measured MCU acquisition
timestamps. Filters/plots cannot restore undetected sample loss. See current status
before interpreting timing or claiming continuous logging.

## Offline checks

```powershell
.\.venv\Scripts\python.exe -m unittest test_reentry test_flash_protocol test_flash_recovery test_flash_lifecycle test_timing_protocol test_flash_v2 test_measured_pipeline
```

Current baseline:76 host checks (including v2 codec and measured integration). Hardware acceptance is a separate procedure.
Documentation organization changes do not modify firmware, host behavior or data.
