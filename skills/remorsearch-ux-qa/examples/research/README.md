# Offline research example

All content, institutions, measurements and permissions in this example are invented. The outputs are diagnostic examples and must never be used as evidence about real people.

From the repository root, with Python 3.10 or newer:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 skills/remorsearch-ux-qa/examples/research/run_fixture.py
```

The script creates a private temporary run, a reviewed native team import and one invented search receipt. It makes no network requests. Merge, gate, report-check, export-audience, the draft check and minimize must pass. The draft retains missing ages, devices and task information as todos. Use `--out /absolute/private/run` to retain the artifacts. Ordinary reader test hooks remain disabled so the script can exercise export; these invented artifacts do not represent actual research. Explicit reader fixture-mode runs are separately refused by export with exit 2.

Read reader-return.example.json for a successful page-return example. The machine schema validates it; agents need only the example and the audience-pipeline field guide.

failures.json lists mutations and expected exits. The repository test file tests/test_research_engine.py (not installed) executes them. Privacy, harvest, caps and counter-process failures exit 1; malformed schemas, invented provenance or quotations, numeric mismatch and stale gates exit 2; lock contention exits 3. Unsupported claim statuses alone allow gate exit 0.
