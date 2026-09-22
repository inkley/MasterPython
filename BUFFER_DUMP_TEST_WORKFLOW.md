# RAM Buffer and Dump Test Workflow

This workflow is for moving away from MCU internal flash logging as the normal
test path. Treat the sensor module as a RAM-buffered producer: sample locally,
hold recent records in RAM, and dump records over CAN when the PC polls.

## Storage Model

- Primary data path: circular RAM sample buffer on the MCU.
- Normal retrieval: PC sends `CMD_STREAM_BUFFER` (`0x03`), firmware replies with
  a record count, then sends packed sample records over CAN.
- Real-time path: PC sends `CMD_START_STREAM` (`0x02`) and logs broadcast frames.
- Config/calibration: use MCU EEPROM if available, or a small external EEPROM or
  FRAM later.
- Backup logging: add soldered SPI FRAM or SPI flash later. Keep this separate
  from the real-time RAM buffer so flash erase/write timing cannot disturb
  sampling.

## Current PC Commands

From `InkleySensor.py`:

- `scan_ports`: find the CAN adapter.
- `set_channel COMx`: set the adapter manually.
- `version`: verify command/response traffic.
- `set_buffer_size <samples>`: ask firmware to resize/cap its RAM buffer.
- `buffer_status`: inspect mode, capacity, count, wrap flag, and dump state.
- `start`: begin real-time CAN broadcast logging to CSV.
- `stop`: stop real-time streaming.
- `dump_buffer`: request stored/buffered samples and save them to CSV.
- `read_flash`: old alias for `dump_buffer`, kept for compatibility.

The wire protocol may still label playback frames as `CMD_READ_FLASH` (`0x07`).
That is only a historical frame tag on the PC side; the intended behavior is a
buffer dump.

Current firmware keeps wire value `0x07` but treats it as buffered sample data.
Payload frames include a 16-bit sequence index in bytes `[1..2]`; the Python
CLI checks this during `dump_buffer` and writes it to the CSV as `SampleIndex`.

## Bench Test Sequence

1. Connect the CAN transceiver and USB CAN adapter.
2. Confirm common ground, 3.3 V CAN logic compatibility, CANH/CANL wiring, and
   proper bus termination.
3. Start the Python CLI:

   ```powershell
   python InkleySensor.py
   ```

4. Select the adapter:

   ```text
   scan_ports
   set_channel COM5
   ```

5. Confirm basic command traffic:

   ```text
   version
   ```

6. Pick a small RAM buffer first:

   ```text
   set_buffer_size 256
   buffer_status
   ```

7. Start real-time streaming for 5-10 seconds:

   ```text
   set_filename realtime_smoke.csv
   start
   stop
   ```

8. Confirm the CSV has plausible pressure values and a sample count close to the
   expected sample rate.
9. Without power cycling, dump the buffered records:

   ```text
   set_filename buffer_dump_smoke.csv
   buffer_status
   dump_buffer
   ```

10. Compare `realtime_smoke.csv` and `buffer_dump_smoke.csv`:

    - Values should be in the same ADC range.
    - Dump count should not exceed the configured buffer capacity.
    - If the buffer is circular, the dump should contain the most recent records.

## Buffer Behavior Tests

Run these after the smoke test passes:

- Empty buffer: boot the module and run `dump_buffer` before `start`. Expect zero
  records or a clearly initialized record count.
- Exact fill: configure `set_buffer_size 256`, stream exactly long enough to
  collect about 256 records, stop, then `dump_buffer`.
- Wraparound: configure `set_buffer_size 256`, stream long enough to collect more
  than 256 records, stop, then `dump_buffer`. Expect the newest 256 records.
- Repeated dumps: run `dump_buffer` twice without restarting. Decide whether the
  firmware should preserve records after dump or clear them, then verify that
  behavior consistently.
- Power-cycle behavior: stream, stop, power cycle, then `dump_buffer`. For
  RAM-only storage, expect records to be gone.

## Firmware Acceptance Criteria

- Sampling ISR or timer path never writes internal flash.
- CAN transmit backpressure does not block sampling.
- RAM buffer writes are constant time.
- `CMD_STREAM_BUFFER_SET` acknowledges the actual buffer capacity if the requested
  size is capped.
- `CMD_STREAM_BUFFER` returns a record count before payload frames.
- Payload frames include enough ordering information to detect dropped or
  reordered records. Current buffered payload frames include a 16-bit sequence
  index.
- Buffer dump is disabled or clearly defined while real-time streaming is active.

## Next Hardware Storage Steps

RAM buffering is the right first-stage architecture for deterministic sampling
and CAN retrieval validation. For longer-duration local logging, the current
TM4C internal RAM is capacity-limited to seconds, so the next hardware step
should be external FRAM or flash, with FRAM preferred for high-endurance
time-series logging.

Current RAM storage math:

- Buffered sample format: one `Pressure1`/`Pressure2` pair per `uint32_t`.
- Storage rate at 1000 Hz: `4 bytes/sample * 1000 samples/s = 4 KB/s`.
- Current tested capacity: `4094 samples`.
- Current tested duration: `4094 / 1000 Hz = 4.094 seconds`.

Longer-duration storage estimates at the current 4-byte sample-pair format:

```text
30 sec  -> 120 KB
60 sec  -> 240 KB
5 min   -> 1.2 MB
10 min  -> 2.4 MB
```

Use this order when expanding storage:

1. RAM buffer only for recent samples, debugging, smoke tests, short bursts,
   and CAN dump validation.
2. MCU EEPROM only for persistent configuration/calibration data such as
   settings, calibration constants, or device ID. The available EEPROM is too
   small for high-rate sampled data.
3. Soldered SPI FRAM for high-endurance backup logging. FRAM avoids
   erase-before-write behavior, supports simple circular log semantics, and is
   more predictable for repeated sampling.
4. Soldered SPI flash only if capacity matters more than write endurance and
   erase-block management complexity.

Avoid internal flash for normal high-rate sample logging. Internal flash has
erase-block constraints, slower writes, and endurance limits; it is better used
for firmware storage than repeated time-series logging.

Avoid removable SD for this workflow unless field-service data removal becomes a
hard requirement.
