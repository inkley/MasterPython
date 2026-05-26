# MasterPython - Inkley Sensor CAN Interface

Python command-line tools for communicating with Inkley pressure sensor modules
over CAN bus. The CLI is used for lab testing, firmware validation, real-time
CSV logging, and RAM-buffer dump retrieval.

## Features

- Query firmware version over CAN.
- Start and stop real-time pressure streaming.
- Log real-time samples to CSV.
- Set the firmware RAM buffer size.
- Dump RAM-buffered samples after streaming stops.
- Scan for likely SLCAN-compatible USB CAN adapters.

`read_flash` remains available as a compatibility alias, but current firmware
validation should use `dump_buffer`.

## Requirements

```powershell
pip install python-can pyserial
```

Supported adapters include CANable, CANdo, CANtact, USB2CAN, PEAK, Kvaser, and
STM32-based SLCAN devices.

## Quick Start

```powershell
python .\InkleySensor.py
```

Inside the CLI:

```text
scan_ports
set_channel COM5
version
```

Use the COM port reported for your CAN adapter.

## Common Commands

- `version` - request the firmware build/version.
- `start` - start real-time CAN broadcast logging.
- `stop` - stop real-time streaming.
- `set_filename <file.csv>` - set the CSV output filename under `Data/`.
- `set_outdir <path>` - set the CSV output directory.
- `set_buffer_size <samples>` - request a RAM buffer capacity.
- `buffer_status` - show firmware mode, RAM capacity, count, wrap flag, and dump state.
- `dump_buffer` - download stored RAM samples to CSV.
- `read_flash` - alias for `dump_buffer`.

Menu numbers are also supported:

1. Display firmware version
2. Start real-time streaming
3. Stop streaming
4. Dump buffered sensor data
5. Show buffer status
6. Scan and select CAN ports
7. Show system information
8. Exit

## CAN Protocol Summary

- Interface: SLCAN
- Bitrate: 1 Mbps
- Command CAN ID: `0x107`
- PC response CAN ID: `0x108`
- Realtime broadcast CAN ID: `0x7DF`
- Frame size: 8 bytes
- Realtime packed frame type: `0x06`
- Buffered sample playback frame tag: `0x07`

Realtime frames pack two pressure samples per CAN frame. Buffered dump frames
return one stored `Pressure1`/`Pressure2` sample pair per response frame.
Buffered sample frames carry a 16-bit sequence index in bytes `[1..2]`; the
CLI checks this index during `dump_buffer` and writes it to the CSV as
`SampleIndex`.

## RAM Buffer Validation

The firmware stores samples in MCU RAM while real-time streaming is active.
After `stop`, use `dump_buffer` to retrieve the stored records.

Empty-buffer test after power cycle:

```text
version
buffer_status
dump_buffer
```

Expected result:

```text
Buffered record count: 0
No buffered records present on the module.
```

Circular-buffer wrap test:

```text
set_buffer_size 256
buffer_status
set_filename realtime_wrap.csv
start
```

Wait 2-5 seconds, then:

```text
stop
buffer_status
set_filename buffer_wrap.csv
dump_buffer
```

Expected result: `Buffered record count: 256`.

Max-capacity guard test:

```text
set_buffer_size 999999
buffer_status
set_filename realtime_maxcap.csv
start
```

Wait about 5 seconds, then:

```text
stop
buffer_status
set_filename buffer_maxcap.csv
dump_buffer
```

Expected result: the firmware caps the request at `4094` samples and saves
`Data/buffer_maxcap.csv`.

## Project Structure

```text
MasterPython/
|-- InkleySensor.py
|-- BUFFER_DUMP_TEST_WORKFLOW.md
|-- TEST_RESULTS.md
|-- Data/
|-- CHANGES.md
`-- README.md
```

## Troubleshooting

- If no ports are found, verify the USB CAN adapter connection and driver.
- On Windows, set the adapter explicitly with `set_channel COMx`.
- On Linux, ensure the user has serial permissions, for example:

```bash
sudo usermod -a -G dialout $USER
```

## Context

Part of the Inkley Sensor Module development effort for distributed
hydrodynamic sensing and CAN-enabled underwater instrumentation.
