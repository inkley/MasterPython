# Test Results

## 2026-09-22 - Development restart bench checks

Board version `0.0.3.236`, COM5 SLCAN, CAN 1 Mbps. No firmware flash performed.

- Initial read: malformed SLCAN input raised a hexadecimal parsing ValueError.
  Later version requests returned successfully. Host receive handling now
  reports/discards malformed input and continues within the existing deadline.
- Initial stopped buffer: count zero; empty dump returned zero records.
  This was not a controlled power-cycle test.
- Baseline 256 wrap: 3,004 realtime rows; 256 dump rows, sequences 0..255.
  A second dump contained identical sequence/value records. The entire dump
  was not found as a contiguous exact match in realtime. Its first 255 samples
  exactly matched realtime rows 2749..3003; the last RAM sample was unmatched.
  This is consistent with stopping before the final sample is paired for CAN
  transmission, but does not independently prove that explanation.
- Updated host, oversized request 999999: actual capacity 4,094; five-second
  stream logged 5,002 rows. Stopped status: full, count 4,094.
- Maximum dump and repeat: both contained 4,094 rows, valid sequences, identical
  values. The dump exactly matched realtime rows 908..5001 (zero-based).
- All packed pairs in the updated capture had 0.001 s timestamp separation.
  This verifies host formatting, not independent ADC timing accuracy.
- Historical May sequence dumps rechecked: 256 and 4,094 rows, zero sequence
  mismatches, all ADC values in range.
- Python source compilation and TI main.c object compilation passed. Full
  firmware linking/flashing and long-duration tests remain outstanding.
- Six offline regression tests passed: malformed-version recovery, transport
  error propagation, packed timing/day boundary, nominal dump time/calibration,
  filtering rejection of gaps/short records, and low-pass response.
- Python analysis completed on both the historical and new 4,094-row dumps;
  PNGs visually checked. CSV/NPZ/MAT/metadata were generated. MATLAB numerical
  equivalence has not been established. Installed versions are recorded in
  requirements-lock.txt.

Local artifacts (ignored by Git):

- `Data/reentry_20260922_130243/`: baseline realtime, wrap and repeat dumps.
- `Data/reentry_fixed_20260922_130807/`: updated realtime, maximum and repeat dumps.


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
