# Host regression tests

These tests exercise the Python protocols, recording lifecycle, measured-data
pipeline, timing transport, analysis path, and controlled bench fixtures. They do
not open sensor hardware or certify physical flash/power behavior.

Run the complete suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -p "test_*.py"
```

Keep shared synthetic fixtures inside this package and use package-relative
imports so test discovery does not depend on repository-root test modules.
