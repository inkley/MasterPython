# Test Results

## 2026-05-26 - RAM Buffer Dump Validation

Environment:

- Firmware version observed: `0.0.3.236`
- Host CLI: `InkleySensor.py`
- CAN adapter channel: `COM5`
- CAN bitrate: 1 Mbps

Results:

- Empty buffer after Tiva board power cycle: passed.
  - Command: `dump_buffer`
  - Result: `Buffered record count: 0`
- Circular buffer wrap at 256 samples: passed.
  - Commands: `set_buffer_size 256`, stream for more than 256 samples, `dump_buffer`
  - Result: `Buffered record count: 256`
  - Buffer status after stop: capacity `256`, count `256`, full/wrapped `yes`
  - Sequence validation: passed
  - Output: `Data/buffer_seq_wrap.csv`
- Oversized buffer request cap: passed.
  - Commands: `set_buffer_size 999999`, stream about 5 seconds, `dump_buffer`
  - Buffer status after stop: capacity `4094`, count `4094`, full/wrapped `yes`
  - Result: saved `4094` samples
  - Sequence validation: passed
  - Output: `Data/buffer_seq_maxcap.csv`

Conclusion:

The RAM-first workflow is validated for empty, wrapped, and maximum-capacity
buffer dumps. Buffered playback sequence checks passed for both the 256-sample
wrap test and the 4094-sample maximum-capacity test.
