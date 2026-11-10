# Development quick start

Baseline: firmware **0.0.3.241**, build1009. The maximum 4094-pair bounded
capture/persist/download/clean-reboot checkpoint passed. Start with
[current status](docs/CURRENT_STATUS.md), the [acceptance procedure](docs/ACCEPTANCE_PROCEDURE.md),
the [firmware operator guide](docs/FIRMWARE_GUIDE.md), and the
[documentation index](docs/README.md). The original restart guide is
[archived](docs/archive/REENTRY_2026-09-22.md).

```powershell
.\.venv\Scripts\python.exe InkleySensor.py
```

```text
version
flash_recovery
verify_flash
```

COM5 is the last validated SLCAN adapter, CAN1Mbps; select the actual adapter port
if different. One process owns it. Current retained recording is COMMITTED/4094;
see current status for UUID/backups. Do not clear merely to resume development.
`dump_flash LABEL` preserves it. This documentation update requires no reflash.

Next: define acquisition/UTC time model and uncertainty, then measured timing/gap
metadata and Python support. Saved times remain nominal; host receipt is not MCU
acquisition time. Continuous flash logging is unimplemented/unvalidated.

Unflashed candidate .242/build1010 is ready for read-only upgrade checkpoint A in
[measured implementation](docs/reference/MEASURED_IMPLEMENTATION.md). Start by
verifying the retained v1 recording, not by clearing it. New measured mode supports
1024 pairs and actual raw ticks/events; UTC is still unavailable. Do not check the
first implementation item complete until measured hardware acceptance passes.

Unflashed .243 bench candidate: follow [RAM-only gap/stack runbook](docs/reference/BENCH_GAP_STACK.md). Current COMMITTED1024 recording stays protected. No clear/persist command is needed for this bench. Other fault and worst-case stack checks remain open.
