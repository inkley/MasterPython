# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

- Added `dump_buffer` as the primary RAM-buffer retrieval command.
- Kept `read_flash` as a backward-compatible alias.
- Added `buffer_status` to inspect firmware mode, RAM buffer capacity, current count, wrapped/full flag, and dump-active flag.
- Added queued CAN frame draining before buffer dumps to avoid stale playback frames confusing response parsing.
- Reduced `dump_buffer` terminal verbosity while retaining first-frame diagnostics and progress summaries.
- Added buffered playback sequence validation using the 16-bit sequence index carried in bytes `[1..2]` of `0x07` frames.
- Added `SampleIndex` to buffered dump CSV output.
- Fixed streaming response handling so firmware ACK/status responses are handled while realtime broadcast frames are flowing.
- Added RAM buffer validation workflow and test-results documentation.
