> Implementation update: [measured .242 candidate](MEASURED_IMPLEMENTATION.md), built but hardware acceptance pending.
> Historical design/offline-only status below describes its checkpoint; .241 bench results remain the validated baseline.

# Offline v2 codec and recovery checkpoint

2026-11-02. Implemented in the host repository only; no MCU/capture/CAN commands
or firmware image changed. This is a Python reference and synthetic corruption
suite, not a production firmware codec or physical power-failure validation.
[METADATA_V2](METADATA_V2.md) defines the layout; [TIME_MODEL](TIME_MODEL.md) defines
timestamp semantics. .241 and the retained v1 recording remain unchanged.

## Files and API (MasterPython root)

- flash_v2.py: explicit little-endian encoding, strict block/record validation,
  journal snapshots and read-only partition classification.
- metadata_v2_schema.json: byte-identical mirror of firmware tools/metadata_v2_schema.json.
- test_flash_v2.py:21 parameterized/adversarial test groups with synthetic images.

Use from an offline Python session with MasterPython on the import path:

```python
from flash_v2 import encode_recording, decode_recording, recover_image
# encode_recording(recording_id, domain_id, samples, events, metadata, summary)
# All observations and quiescent counters are explicitly supplied by the caller.
# A recording is a reconstructed 128 KiB bytes image, not a hardware read.
# decoded = decode_recording(image_bytes)
# classification = recover_image(image_bytes)
```

Samples are dictionaries with trigger_ticks, attempt_index, p1, p2. Event/metadata/
summary dictionaries use every non-reserved field in the schema. empty_fields
is a construction aid; its unknown/zero defaults do not create valid metadata.
Encoder checks caller counts and computes stream CRC; it does not manufacture
acquisition timestamps, gaps, UTC, drift bounds or identity. Zero-sample captures
are rejected. encode_block/decode_block provide envelope/record checks; only
full decode_recording establishes recording-level consistency. Recovery adds
journal/extraneous-page classification. Passing the lower-level decoder alone
does not authorize ACK/deletion or ignore quarantine.

encode_journal(validated_record, operation, generation, request_id) constructs an
offline snapshot; operation1 ACK,2 DELETE. No function issues an erase, programs
flash, opens CAN or runs the live CLI. No clear/reclaim executor is implemented.

## Checked semantics

- Fixed field offsets, endianness, UUIDs, types, unsigned overflow, kind/version,
  sizes/counts, reserved zero fields, erased padding, CRC and separate CMIT marker.
- Metadata clock/reference, known/unknown bounds, no UTC mappings in first profile.
- Ordered raw ticks/attempt indices, exact block packing/indexing, sample bounds,
  common recording/domain/quality, stream CRC and final manifest consistency.
- Stop-on-first-ADC-fault bounded profile, explicit failed-attempt event accounting,
  no duplicate failure/valid identity; unknown missing counts remain unknown.
- Unreported/invented interval faults rejected when all attempt timestamps survive.
  Phase checked only when explicitly assessed with unambiguous attempt schedule;
  unserviced-slot ambiguity cannot be presented as assessed phase compliance.
- Event prefix/capacity, one lost detail then stop, sticky quality/overflow reason,
  known planned-pause boundaries, exact versus estimated count classification.
- Journal generation/target/manifest digest and exact owned-page bitmap, excluding
  journals/spares; conflicting generations or uncertain journals stay protected.

Semantic checks reject inconsistent claims. They cannot establish that supplied
measurements, clock calibration, source identity or physical timing are true.
The codec's supported bounded profile rejects RAM/TX loss counters rather than
pretending it implements a continuous-loss capture path. Broader future profiles
need explicit version/capability review.

## Read-only recovery states

- EMPTY: no programmed bytes observed; not electrical erase-quality evidence.
- COMMITTED / ACKNOWLEDGED / CLEAR_PENDING: valid complete recording; matching
  durable journal affects lifecycle classification but never causes an action.
- *_WITH_QUARANTINE: valid readable recording with unrelated/invalid extra pages;
  those pages remain protected and are not silently included or reclaimed.
- JOURNAL_UNCERTAIN: unusable/conflicting lifecycle authority; valid samples can
  still be reported separately, never treated as erase authority.
- INCOMPLETE_DAMAGED_OR_UNSUPPORTED: no complete v2 recording established; samples0.
- CLEAR_PENDING_PROTECTED: DELETE intent exists, but remaining bytes cannot prove
  a safely resumable footprint. A newer torn capture cannot be ruled out. No erase
  plan is returned, even if all nonblank pages lie inside an older bitmap.
- CLEARED: valid DELETE intent with blank observed body; journals remain.
- LEGACY_V1_PROTECTED: delegate read-only v1 lifecycle classification, do not
  migrate/relabel old data. Original v1 decoder/CLI path is unchanged.

Interrupted erase is deliberately fail-closed. A full future reclaim algorithm
needs stronger transactional proof to resume where content ownership is ambiguous;
this checkpoint does not claim complete interrupted-operation recovery. No salvage
is promoted to a complete recording without valid manifest/stream/count semantics.

## Test execution and evidence

From MasterPython:

```powershell
.\.venv\Scripts\python.exe -m unittest test_reentry test_flash_protocol test_flash_recovery test_flash_lifecycle test_timing_protocol test_flash_v2
```

61 host tests passed (40 existing +21 new groups). Firmware timer/format suites
also pass5+8 tests: **74 offline tests total**, plus the v2 layout/RAM checker.
Coverage includes1/57/58/1023/1024 samples;0/14/15/28/29/32 events/overflow;
actual irregular timestamps and estimated missing slots; low-word rollover and
uint64 overflow; all1024 single-byte flips in each of five block kinds; CRC-repaired
semantic faults; every word-aligned programming prefix in a multi-page capture;
torn journals, conflict, missing/duplicate/foreign/mixed-version pages; and every
word-aligned erase prefix across a synthetic recording's data/event/metadata/
manifest pages. Golden sample bytes, bitmap bit order and standard CRC check
vector reduce reliance on encoder/decoder self-roundtrip alone.

These are deterministic offline fault images. Real interrupted pulses, electrical
erase quality, brownout behavior, C implementation equivalence and MCU timing are
not tested. Runtime stack/RAM footprint is still a planning budget.

## Next gate

Review capability/command negotiation and the time-domain initialization handshake,
including fragmentation, coherent replies, duplicates/timeouts and host reconnect.
Then implement shared RAM accessors/measured capture, C codec and v1/v2 persistence
with cross-language golden vectors and updated hardware acceptance. Preserve the
current v1 recording throughout upgrade. Do not infer v2 write support from the
existence of this offline codec.
