# Completed review example

[Back to project](../README.md)

`completed-review.zip` contains fictional Bellhaven assessment data:

- `data/review.sqlite3`: preserved review decisions and execution history.
- `data/snapshots/`: original and subsequent website/CRM evidence.
- `data/verification/`: audit reports from the completed reconciliation.

The bundle contains no API token. It is for local preview and examination of the recorded outcome.

From a fresh project checkout:

```sh
unzip -n examples/completed-review.zip -d .
./start.sh
```

The `-n` flag prevents overwriting existing files. Do not replace a working ledger with this example, or use this example ledger against a different sandbox token. For a fresh sandbox, skip extraction and follow the [operations guide](../docs/operations.md#fresh-discovery).
