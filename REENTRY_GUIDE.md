# Development quick start

Baseline: firmware **0.0.3.244**, build 1012. Measured 1,024-pair capture,
RAM export, persistence, verified flash download, recovery, durable ACK,
identity-bound reclamation, controlled faults, and observed stack-path coverage
have passed on the eval board. Start with
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

COM5 is the last validated SLCAN adapter at 1 Mbps; select the actual adapter port
if different. One process owns it. The current retained recording is an
unacknowledged COMMITTED1024 measured-v2 recording; see current status for its UUID,
timer domain, hash, and backups. Do not clear merely to resume development.
`dump_flash LABEL` preserves it. Documentation-only changes require no reflash.

Run the complete host regression suite with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -p "test_*.py"
```

Next: obtain recording-duration, IVER transport/outage, UTC/retention, physical
flash-interruption, and deployment-build requirements before changing storage,
clock, or optimization architecture. Continuous logging, validated UTC,
independent-power operation, and custom-PCB acceptance remain open.
