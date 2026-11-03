# Short RAM-only gap and observed-stack bench checkpoint (.243)

Candidate build1011 / version0.0.3.243. Built/offline checked, NOT flashed or
hardware accepted. Normal .2421024-pair recording remains protected. This step
adds no RTC/UTC, continuous storage or physical interrupted-flash validation.
ADC fault and event-overflow hardware tests remain OPEN; do not mark the broad
implementation item complete from this gap test alone.

## Exact scope and preservation guards

`measured_bench_gap <protected recording.bin>` verifies/flushes the saved normal
v2 binary. Firmware requires matching current flash recording UUID/manifest CRC,
full MCU verification, a current timer-domain assignment, stopped acquisition,
no retained RAM source, and at least512 observed painted stack bytes. It stages
an independent bench UUID using the existing request fields and starts64 measured
pairs in the shared RAM arena. The bench is deliberately unavailable if another
RAM capture is retained. No normal capture/clear command is sent implicitly.

After attempt16 is recorded, the SysTick handler deliberately waits at least
100000 hardware timer ticks (nominal5 ms) exactly once. Timer continues running;
subsequent real trigger intervals exercise late/estimated-unserviced reporting.
There is no ADC result fabrication. CAN service may pause during this bounded
negative test. Exact estimated missing count is NOT prescribed; require a visible
>=5 ms interval, timing/gap events and explicitly estimated classification.
A following early interval can legitimately generate another event.

Metadata payload schema2 (256-byte layout unchanged), envelope payload_schema2,
feature_bits1=BENCH_GAP_RAM_ONLY, flags/time reference/CRC unchanged. Normal metadata
schema1/feature0 is untouched. Unknown profiles are rejected. This explicit schema
extension makes bench provenance part of the binary CRC, not merely a filename.
Host exports origin MCU_BENCH_RAM, bench_injection=true; plot title identifies
BENCH gap injection. Offline fixtures remain labeled OFFLINE. Recovery classifies
a reconstructed bench image as BENCH_RAM_IMAGE_PROTECTED, not normal committed data.

Firmware blocks persist_buffer for bench mode. Host blocks flash ACK/CLEAR using
a bench binary. Original flash must still verify1024 pairs throughout. Bench RAM
can only be explicitly discarded with the matching verified/flushed saved bench
file, current RAM UUID and manifest CRC; MCU also reverifies the protected flash
and its original CRC before discarding. Discard restores status from actual flash,
without any erase/program call. Reset loses disposable RAM but not the protected
recording. Normal acquisition/lifecycle semantics are otherwise unchanged.

## Stack watermark (observed paths only)

ResetISR paints unused MSP RAM below actual MSP-64 with0xA5A5A5A5 before C runtime;
no calls, no stack pushes in the inspected paint sequence, PRIMASK saved/restored.
Linker __STACK_BOTTOM/__STACK_TOP bound the4096-byte allocation. Painting never
crosses below bottom or into the current active frame. Disassembly was checked:
MRS MSP, subtract64, bounded postincrement stores, restore PRIMASK, branch to C init.
The ELF checker now verifies the bottom symbol matches the allocated stack.

`stack_status` scans from the bottom with acquisition stopped and interrupts
briefly masked. Reports pattern-unused bytes and4096-minus-unused as touched/
unknown estimate, including at least64 conservative unpainted bytes. A<512-byte or
unavailable report blocks bench start; it is not an approved worst-case margin.
Watermarks can miss reserved/unwritten frames (including lazy FPU stacking) and
pattern collisions. This is NOT exact peak-SP measurement or a stack-overflow proof.
No PSP/RTOS stack coverage is implied. Fresh reset/ResetISR execution is required.

Query after boot/readback/download and after the bench RAM export to observe those
paths. Flash-program/erase-path stack stress is not exercised by this RAM-only test.
Keep runtime worst-case acceptance open; do not erase a protected recording merely
to obtain another stack number near the end of a session.

## Wire additions

Normal0x30 selector0 stays0x49500201. Selector8 returns0x424E4301 for this bench/stack
extension; old .242 rejects it and host starts no test. Request/target staging0x20..27
holds fresh bench UUID / protected flash UUID.0x39 argument is the protected manifest
CRC; success64. No persist or deletion is part of0x39.
0x3D uses newly staged request/target (target=current bench UUID) and bench manifest
CRC for verified RAM-only discard; success0.0x3E argument0x5354414B returns painted
unused stack bytes0..4032; errors have high bit set. New error14 blocks the bench
when watermark margin is insufficient/unavailable.0x37/tag0x3B frozen RAM transfer
and all normal v1/v2 operations retain their framing.

## Short bench sequence

Exit CLI. Build/load Debug/Inkley_PressureSensor.out using **Necessary Pages Only**,
correct GH6PM target and16MHz crystal. Resume (run ResetISR after program load;
no breakpoint/step during capture). Restart updated Python CLI.

```text
version
flash_recovery
verify_flash
stack_status
timing_reset
measured_bench_gap Data/v242_after_reboot_1024_20261102_170605_111615/recording.bin
```

Require .243, COMMITTED1024, successful verification and a usable stack report.
Stop on errors or insufficient/unknown margin; never clear the protected recording.
Wait one second, then:

```text
flash_status
dump_measured bench_gap_01
timing_status bench_gap_01
stack_status
verify_flash
dump_flash v243_protected_after_gap
```

Expected RAM_READY64; flagged bench metadata/events, zero ADC errors, a measured
long interval and estimated missing-slot count, no lost event details, zero flash
erase/program calls in the timing report, and protected flash still1024 verified.
Compare the downloaded normal flash binary byte-for-byte to the prior saved copy.
Analyze bench samples.csv; expect a broken line and timing marker at the gap,
BENCH label and filtering disabled. Do not interpret the inserted gap as a sensor
phenomenon or normal timing acceptance. Delay is intentional negative testing.

After saved bench evidence is reviewed, discard ONLY bench RAM:

```text
measured_bench_discard Data/ACTUAL_BENCH_DIRECTORY/recording.bin
flash_recovery
verify_flash
```

Expect original COMMITTED1024, unchanged. Leave that recording intact. Do not use
clear_flash or persist_buffer for the bench. Keep exact directory/UUID/raw ticks/
events/timing reports and stack outputs as evidence. No actual bench hardware
result exists until those outputs/files are reviewed.

## Offline validation

86 host tests (including10 new bench guards/provenance tests), plus5 timer/8 format
checks:99 offline tests. Debug build and reserved-region/vector/stack layout checks
pass; stack4096, occupied SRAM25144/32768 (7624 unallocated). Stack usage remains
unmeasured until the board run. Synthetic codec/plot checks do not execute C ISR,
prove flash preservation on hardware, or establish physical fault recovery.

### .243 observed bench result — 2026-11-02

RAM-only gap capture 808f6dc2-15a8-48ed-b8d6-d992e5208c07 completed64/64 pairs.
Two events retained, none lost: late/estimated-gap at attempt16 (4 estimated
missing slots), then early interval at attempt17. Diagnostic trigger range
927.500–5073.100us; zero ADC failures, CAN drops/overruns, or flash calls.
Event ticks describe pre-trigger timestamps; diagnostic intervals are a separate
instrumentation point. Stack watermark after a physical startup and bench export:
3600/4096 bytes pattern-unused (496 touched/unknown), not worst-case acceptance.
CCS post-load startup initially bypassed stack painting; power cycling enabled it.
Protected1024-pair flash copy after bench is byte-identical to .242 reboot backup:
SHA256 881ff56d986240b2d304137a044ead995a1b5b5c8c85b462b69c0239a6f482a0.
Bench export: Data/bench_gap_01_20261102_173144_511710; protected export:
Data/v243_protected_after_gap_20261102_173148_436910. Bench RAM discard pending.
Controlled gap reporting passed this fixture; ADC-error/event-overflow hardware
checks, worst-case stack and physical interrupted-flash tests remain OPEN.

Final bench cleanup confirmed by operator: matching disposable bench RAM discarded;
recovery COMMITTED1024 and flash CRC verification passed. Protected recording
899dee62-92d9-48ea-94c5-fcf239668008 remains intact. Resume with ADC-error,
event-overflow and broader stack checks; do not clear the protected recording.
