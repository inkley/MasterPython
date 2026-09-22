# Development restart: 2026-09-22

## Where the project stands

Two separate Git repositories are open in the workspace:

- `MasterPython`: https://github.com/inkley/MasterPython
- `C:/Users/Lab-User/workspace_v12/Inkley_PressureSensor`:
  https://github.com/inkley/PressureSensor

The last committed work in each was May 26. Remote main tips were checked on
September 22 and matched local HEAD before this session's changes:
`4e3ee6d` (host), `310fa3d` (firmware).

Existing local changes included CLI `clear`/`home` commands, storage guidance,
firmware build products, and main.c line-ending differences. Preserve these
when reviewing changes. Debug artifacts are already tracked by the firmware
repository; simply adding an ignore rule will not untrack them.

## Data path refresher

1. TM4C123GE6PM samples PE3/AIN0 and PE2/AIN1 every nominal 1 ms.
2. During streaming, each two-channel sample enters a circular RAM buffer.
3. With `STREAM_DECIMATE=2`, two consecutive sample pairs share one CAN frame:
   nominally 1,000 sample pairs/s and 500 broadcast frames/s.
4. The USB SLCAN adapter carries 1 Mbps CAN traffic to `InkleySensor.py` on COM5.
5. `stop` preserves RAM contents; `dump_buffer` downloads oldest-to-newest
   retained samples. Each dump has its own sequence starting at zero.

Commands use CAN ID `0x107`, replies `0x108`, broadcasts `0x7DF`.
`Pressure1` and `Pressure2` are 12-bit ADC counts, not calibrated pressure.
At 4,094 sample pairs, RAM retains about 4.094 seconds. Starting a new stream
or resizing the buffer clears the old capture. Power loss clears RAM.
`read_flash` is a compatibility alias for RAM dumping.

Observed board version: `0.0.3.236`, the four-byte rendering of build 1004.
COM3 is the Stellaris virtual serial port; COM5 is the USB CAN adapter.

## Use from the VS Code terminal

The project `.venv` contains CAN and analysis dependencies. Select its Python
interpreter in VS Code, or invoke it explicitly:

```powershell
.\.venv\Scripts\python.exe InkleySensor.py
```

In the CLI, use new filenames for every capture (existing names are overwritten):

```text
version
buffer_status
set_buffer_size 256
set_filename realtime_new.csv
start
```

Wait three seconds, then:

```text
stop
buffer_status
set_filename buffer_new.csv
dump_buffer
```

Only one process should own COM5 at a time. Fresh environment setup:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest -v test_reentry
```

Use `requirements-lock.txt` instead of `requirements.txt` to reproduce the exact
dependency versions installed for this session (Windows, Python 3.13.5).

## Python analysis

`analyze_pressure.py` ports the core quick-look workflow from
`C:/Users/Lab-User/Desktop/INKLEY/Scripts/IPS_TI_Raw_v19.m`:

- Import realtime or sequence-tagged buffer CSV, retaining raw ADC counts.
- Convert counts to volts using `counts * Vref / 4095` (default Vref 3.3 V).
- Optionally apply `P = (V-b)/m` using separate P1/P2 calibration coefficients.
- Calculate P1 minus P2; optionally filter with an eighth-order Butterworth
  low-pass and forward/backward filtering (default 50 Hz).
- Export processed CSV, NPZ, MAT, metadata JSON, and a three-panel PNG to a new
  timestamped `Data/Results/` folder. Existing results are not overwritten.

```powershell
.\.venv\Scripts\python.exe analyze_pressure.py Data\buffer_seq_maxcap.csv
.\.venv\Scripts\python.exe analyze_pressure.py Data\realtime_seq_wrap.csv --no-filter
```

Optional calibration JSON, with m in V/Pa and b in V:

```json
{"P1": {"m": 0.01, "b": 1.65}, "P2": {"m": 0.01, "b": 1.65}}
```

These are illustrative coefficients, not measured sensor calibration. Supply
your own with `--calibration path/to/calibration.json`. Without calibration,
outputs are explicitly labeled volts. This is application of existing fits,
not a replacement for the calibration fitting/overlay MATLAB scripts.

Time deliberately differs from v19: buffer timestamps are dump-write times
(identical for every row); realtime timestamps are USB/host receipt estimates.
Analysis uses `SampleIndex / fs`, or row number / fs when no index exists.
The nominal rate defaults to 1,000 Hz and must match acquisition settings.
This cannot recover undetected realtime losses or deliberate decimation.
Filters reject known index gaps. Do not infer an ADC rate from these host
timestamps. Packed logger timestamps now retain microseconds and place A
1 ms before B; they are still not device timestamps.

Filter implementation follows SciPy's
[second-order-section forward/backward filtering](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html).
MATLAB numerical parity, especially filter endpoint handling, has not been
verified. The original MATLAB scripts remain available for comparison.

`Data/IPS_TI_Raw_v24.m` is another, newer local workflow with realtime/buffer
alignment. It is inside ignored Data and is not backed up by Git. Its comparison
and figure-export features are not yet ported. A buffer dump sequence is local
to the dump, so do not equate it to a realtime row index without alignment.

## Firmware next steps

The installed TI ARM 20.2.7.LTS compiler compiled current main.c successfully.
This session did not link the full CCS project or flash the MCU.
Use CCS to build and flash when firmware changes are ready, then record build
ID, source commit, and bench results together.

Review before further firmware changes:

- Buffer state is shared by the sampling ISR and command handlers; reset,
  resize, and status snapshots need an interrupt/concurrency review.
- Firmware itself does not reject dump/resize commands during acquisition;
  host-side restrictions alone are not a complete guard.
- Realtime frames have no acquisition counter/timestamp. Add these, or a
  protocol extension, before claiming reliable loss detection or time analysis.
- Some SysTick early returns skip GlobalTimer increment; audit its intended
  meaning before using it as elapsed time.

See TEST_RESULTS.md for today's measurements and limitations. Remaining bench
work includes power-cycle retention, precise fill boundaries, long-duration
streaming, deliberate CAN interruption, and calibrated physical stimuli.
