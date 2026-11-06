# Running and maintaining the project

[Back to project](../README.md)

## Local preview

Requires Python 3.10+ on macOS or Linux. The launcher installs pinned dependencies into `.venv` and starts on `http://127.0.0.1:8765/`, with CRM writes disabled.

```sh
# Optional: restore the completed fictional example without overwriting files.
unzip -n examples/completed-review.zip -d .
./start.sh
```

The example retains 29 applied proposals and one rejection. Select a row to open the review drawer; use Changes, Evidence, and History to inspect it. Close or press Escape to return.

## Fresh discovery

For your own sandbox, use a fresh checkout and skip example extraction. Supply `BELLHAVEN_API_TOKEN` through your shell or secret manager, then run `./start.sh`. The launcher discovers evidence when no ledger exists. To refresh an existing queue, run `.venv/bin/python daily.py`.

Do not replace a live ledger with the example. Keep `data/review.sqlite3` across daily runs; it retains decisions and execution state. Generated snapshots and credentials are excluded from Git.

## Enabling approval writes

Stop the preview server, supply your sandbox token, and run:

```sh
./start.sh --enable-writes
```

Only explicitly approved proposals invoke CRM writes. Rejection records a local decision. The server is loopback-only, uses a per-process request token, and allows only one review server per database. Do not expose it as a public service.

## Components

| File | Responsibility |
| --- | --- |
| `discover.py` | Crawl website details and read every CRM page; save timestamped evidence |
| `reconcile.py` | Deterministic matching, proposal generation and persistent decision identity |
| `review.py` | Local HTTP application, approve/reject endpoints and guarded write executor |
| `web/index.html` | English review UI, source evidence, field comparisons and recorded rationales |
| `daily.py` | Non-overlapping discovery and reconciliation; never approves or writes to CRM |
| `verify.py` | Live CRM read-back audit against baseline, decisions and operation journal |
| `config/crontab.example` | Daily scheduling example; not installed |
| `tests/` | 34 automated tests covering discovery, matching and write safeguards |

## Schedule and validation

[config/crontab.example](../config/crontab.example) runs at 06:15 America/New_York on cron implementations supporting `CRON_TZ`. Replace interpreter/project paths and supply the token securely in the scheduler environment. The example is not installed. The daily process prevents overlapping runs and stops if discovery fails; it never automatically approves changes.

```sh
python3 -m unittest discover -s tests -v
python3 verify.py --baseline data/snapshots/20261104T184236295681Z
```

All 34 tests pass. Coverage includes incomplete evidence, source tampering, namesakes, wrong ZIPs, financial protection, duplicate handling, partial-approval fingerprint stability, rejection persistence, unapproved writes, stale accounts, repeated clicks, CHOW retry, ambiguous POST outcomes and changed read-back data.

The live audit verifies every approved operation against the current CRM, compares original business fields against the initial snapshot, preserves all original financial values, checks account counts, verifies 35 distinct active Bellhaven mappings and regenerates proposals without adding queue entries. It makes no CRM writes; it does use the local proposal ledger to validate rerun behavior.

## Audit history and integration coverage

Approval/rejection rationales are retrieved directly per proposal, independently of the recent event feed. Both global activity and per-proposal history use keyset pagination through `/api/history` (`proposal_id`, `before`, `limit`), with a maximum page size of 100. The interface provides Load more controls; older events remain available without loading the entire ledger at once.

`tests/test_workflow.py` uses synthetic website HTML, a temporary SQLite ledger, a loopback HTTP review server and a fake CRM adapter. It covers crawling through approval/rejection and rerun, request-token enforcement, repeat-approval rejection, protected CHOW balances, restart recovery after a partial CHOW failure, and a decision older than 125 subsequent events. These are automated HTTP integration tests, not automated browser interaction tests. They never contact the real CRM.

Dependencies are pinned to the versions used for validation, including transitive dependencies. Python 3.10+ is required by the pinned soupsieve version.

A manual browser smoke test also completed synthetic rename approval, billing-address rejection and CHOW approval against the isolated fake adapter, ending at two applied and one rejected proposal. The live ledger was only viewed in preview mode. Global history pagination was checked in the browser: 50 initial events plus 9 older events, with no remaining Load more button.
