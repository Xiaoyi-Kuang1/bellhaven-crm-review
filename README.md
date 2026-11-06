# Bellhaven CRM reconciliation

A local, evidence-based review workflow for reconciling Bellhaven's public community directory with its CRM. The daily pipeline proposes changes; only an explicit approval invokes CRM writes.

## Verified outcome

The live sandbox was reconciled on November 4, 2026:

| Result | Count |
| --- | ---: |
| Website communities | 35 |
| Original / final CRM accounts | 121 / 127 |
| Applied proposals | 29 |
| Rejected proposals | 1 |
| Pending / failed proposals | 0 / 0 |
| New queue entries on repeat reconciliation | 0 |

Each website community has a distinct active account under Bellhaven. All original `lifetime_revenue` and `outstanding_ar` values are unchanged, and every changed original business field is covered by an approved operation. The latest read-only audit is `data/verification/20261104T192958Z/report.json`. The assessment submission form has not been submitted.

## Run locally

For a one-command local preview, run `./start.sh`. It creates a virtual environment if needed, installs the pinned dependencies, and starts with CRM writes disabled. To preview the completed review without a token, first run `unzip examples/completed-review.zip -d .`, then `./start.sh`. The evidence bundle contains fictional assessment data and preserved decisions, with no API token. For a fresh independent run, skip extraction and supply `BELLHAVEN_API_TOKEN` for initial discovery. Do not overwrite an existing ledger with the example bundle. `./start.sh --enable-writes` explicitly enables approval writes. Existing servers must be stopped before starting another instance.


Requires Python 3.10+ on macOS or Linux (`fcntl` is used for process locks).

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
export BELLHAVEN_API_TOKEN='<your sandbox token>'

# Discover current evidence and refresh the persistent proposal queue.
python3 daily.py

# Inspect the UI with CRM writes disabled.
python3 review.py
# Open http://127.0.0.1:8765/
```

Stop the preview server before starting write-enabled review:

```sh
python3 review.py --enable-writes
```

In the evidence bundle and delivery archive, `data/review.sqlite3` retains the completed review decisions. Do not delete or replace it between daily runs. With no pending proposals, the UI lists completed decisions. Select a row to open its review drawer. Changes, Evidence, and History are separate views. Long notes, account IDs, and decision rationales expand on demand. The CHOW billing-protection notice remains visible across views. Close or press Escape to return to the queue.

Tokens are supplied through the environment, never embedded in source code. The server binds to loopback only. The project archive contains evidence and the review ledger, but no API credential.

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

## Website discovery and evidence

The crawler follows the homepage, About page, directory pagination and community detail links. The directory advertises 34 communities; the homepage links to Findlay separately, bringing the complete count to 35. Extracted fields include name, street, city, state, ZIP, care offerings and phone.

Each snapshot contains `communities.json`, `accounts.json`, `sources.json`, archived HTML and a completion manifest. Reconciliation validates declared directory pages and counts, the homepage count when present, source references and HTML hashes. Incomplete or inconsistent evidence stops the run before absence proposals can be generated. Failed crawls have no completion manifest.

CRM reads traverse every page and check the total count and unique account IDs. Neither discovery nor reconciliation mutates the CRM.

## Matching and classification

Identity matching requires the same city/state and a normalized street address. Street suffixes and directions are normalized without discarding building numbers or units. An incorrect ZIP can be repaired when the street, city and state corroborate identity. A different street requires matching name, city, state and phone and receives medium confidence for explicit review.

Same-name accounts in another state and accounts at different streets are not reused merely because their names or cities resemble a website location. An account claimed by multiple website locations is routed to manual investigation. Broken, self-referential or chained duplicate/CHOW links stop reconciliation.

The workflow classifies equivalent records, field corrections, direct parent transfers, protected CHOW transfers, missing accounts, duplicates and accounts absent from the website. Every proposal includes source evidence, original account values, confidence, reasoning, operations and dependencies. “Exact” means equivalent in the reconciled fields, not byte-identical records; phone cleanup is outside the requested fields.

Care terminology maps `Memory Support` to `Memory Care` and `Short-Term Rehabilitation & Nursing` to `Skilled Nursing`. The API has a single `care_type`; a valid existing primary care type is preserved, while all website offerings are recorded in `note` where multiple offerings apply.

## Billing SOP and duplicate handling

The API's receivables field is `outstanding_ar`, despite the assignment's reference to `finished_ar`. Both financial fields are validated before any ownership decision.

- When `lifetime_revenue > 0` and `outstanding_ar > 0`, preserve the original account and parent, create a new current account under the correct parent, and set only `chow_current_account` on the original.
- Otherwise, direct reparenting may be proposed for approval.
- Duplicates receive `duplicate_of_account`, `status = Inactive` and an explanatory note. The API supports neither merge nor delete. Their original parents, contacts and history are retained.
- A duplicate with revenue history, positive AR, conflicting care types or conflicting address evidence is routed to investigation instead of deactivation.

Survivor selection favors corroborated street identity, active status, the current Bellhaven parent, financial history, exact website name and phone. An account-ID tie-break is deterministic, not identity evidence, and requires reviewer judgment. Kettering's three financially empty records had no decisive phone match; `001WR41PYNWXCAE2X4` was retained. Its rename/reparent was a prerequisite for deactivating its two duplicates. Owosso's survivor matched the website phone.

## Actual decisions

The 29 applied proposals comprised four new locations, four direct reparentings, nine field updates, two CHOW workflows, seven duplicate links and three `Needs Review` flags. Six accounts were created: four missing locations plus two CHOW current accounts.

- **New accounts:** Amberly Manor in Hudson, Bellhaven at Union Square, Batavia and Carlisle. The Colorado Amberly namesake and the different New Albany street address were not treated as matches.
- **Direct reparenting:** Lima, Findlay, Kettering and Zanesville.
- **CHOW:** Marietta (`51250` revenue / `3800` AR) and Tiffin (`84000` / `12400`). The originals retain their Cedar Trail parents and historical balances; only their CHOW links changed.
- **Absent from website:** Alliance, Coldwater and Sandusky are `Needs Review`. Absence does not prove closure or sale. Sandusky's other-brand same-address account is a lead, not sufficient ownership evidence; its parent and billing history were preserved.
- **Rejected:** Ashtabula's proposed billing-address replacement. A website physical address does not establish that a CRM billing PO box is wrong. This rejection is retained and does not re-enter the queue on an unchanged rerun.

Every mutation passed through the application's approval executor with a recorded rationale. The first examples and final approval/rejection were performed in the UI; the other individually reviewed proposals were approved through the same application's HTTP endpoint in dependency order. No write bypassed the executor. The sandbox accepted `Active`, `Inactive` and `Needs Review`, as well as the approved POST/PATCH payloads, and the results were read back.

## Approval, retries and repeat runs

Approval is persisted before execution; rejection never contacts the CRM. Requests require a per-process review token and valid loopback Host header. A process lock allows only one review server per database. Repeated decision clicks cannot execute a decided proposal again.

Before writes, the executor refetches original accounts, checks for stale evidence, rechecks financial SOP, validates duplicate survivors and enforces prerequisites. Each operation is journaled and read back. A saved create ID allows a failed CHOW link to resume without another create. An ambiguous POST response stops for investigation rather than blindly retrying. Known completed steps are checked again during recovery; interrupted executions are marked failed on restart.

Proposal fingerprints contain the source URL, intended operations and original values of fields being changed. Parent transfers include financial prerequisites. Incidental timestamps, source hashes or unrelated survivor corrections do not generate a new decision. Material changes to relevant fields can generate a new proposal. Pending evidence refreshes, obsolete pending proposals are superseded, and decided records retain their original evidence. The ledger also retains 30 superseded pre-execution development records; they are excluded from the active queue.

## Schedule and validation

`config/crontab.example` runs at 06:15 America/New_York on cron implementations supporting `CRON_TZ`. Replace interpreter/project paths and supply the token securely in the scheduler environment. The example is not installed. The daily process prevents overlapping runs and stops if discovery fails; it never automatically approves changes.

```sh
python3 -m unittest discover -s tests -v
python3 verify.py --baseline data/snapshots/20261104T184236295681Z
```

All 34 tests pass. Coverage includes incomplete evidence, source tampering, namesakes, wrong ZIPs, financial protection, duplicate handling, partial-approval fingerprint stability, rejection persistence, unapproved writes, stale accounts, repeated clicks, CHOW retry, ambiguous POST outcomes and changed read-back data.

The live audit verifies every approved operation against the current CRM, compares original business fields against the initial snapshot, preserves all original financial values, checks account counts, verifies 35 distinct active Bellhaven mappings and regenerates proposals without adding queue entries. It makes no CRM writes; it does use the local proposal ledger to validate rerun behavior.

## Demonstration

The current full-width queue and review drawer are demonstrated in the November 6 silent recording. See [the recording guide](docs/DEMO.md) and [timestamped English voiceover](docs/narration-timed.txt). These show preserved decisions without replaying CRM mutations.


`deliverables/bellhaven-demo.mp4` is approximately 2 minutes 4 seconds. It shows actual Ashland approval, Ashtabula rejection and Tiffin CHOW evidence, with synthesized English narration. The opening dashboard and final CRM confirmation are still captures of the real application. The original tab recording is retained locally as `deliverables/review-recording.webm`.

The video predates the visual refresh of the review interface; its recorded decisions and CRM results remain the same. No approvals were reset or replayed to produce the refreshed UI.

## Limitations and next improvements

- The API has no documented conditional updates or server-side idempotency keys. An external concurrent writer can still change data between GET and PATCH. Local locks and repeated-click guards do not remove that server-side race.
- Ambiguous POST outcomes require operator investigation. A future recovery UI should reconcile a verified created account with the journal before resuming.
- Missing communities need independent ownership evidence. Billing and physical addresses should be separate fields; Ashtabula illustrates the distinction.
- Duplicate contacts are preserved rather than moved without review. A production workflow could add a separately approved contact migration.
- The service is intended for local use, not deployment as a public multi-user application.

## AI assistance

Codex assisted with website/API inspection, implementation, test design, interface work and evidence review. Runtime matching is deterministic: the daily pipeline does not use an LLM or require an AI API key. Reviewer judgment focused on identity evidence, financial safeguards, conservative treatment of missing communities and the Ashtabula rejection. A partial-approval proposal-ID bug was caught and fixed before live writes.

### Interface references

The review interface takes layout inspiration from Rama Zuldi / Odama’s [CRM Dashboard — Table View](https://dribbble.com/shots/23689295-CRM-Dashboard-Table-View) and the Colab CRM/table reference found on [Dribbble](https://dribbble.com/search/crm-dashboard-table). The implementation uses original HTML/CSS and inline icons, with no copied reference assets. It uses a warm-white canvas, forest-green accents, an original arch mark, a full-width queue, and a focused review drawer. Detailed evidence remains accessible on a separate view.

## Reliability update

Approval/rejection rationales are retrieved directly per proposal, independently of the recent event feed. Both global activity and per-proposal history use keyset pagination through `/api/history` (`proposal_id`, `before`, `limit`), with a maximum page size of 100. The interface provides Load more controls; older events remain available without loading the entire ledger at once.

`tests/test_workflow.py` uses synthetic website HTML, a temporary SQLite ledger, a loopback HTTP review server and a fake CRM adapter. It covers crawling through approval/rejection and rerun, request-token enforcement, repeat-approval rejection, protected CHOW balances, restart recovery after a partial CHOW failure, and a decision older than 125 subsequent events. These are automated HTTP integration tests, not automated browser interaction tests. They never contact the real CRM.

Dependencies are pinned to the versions used for validation, including transitive dependencies. Python 3.10+ is required by the pinned soupsieve version.

A manual browser smoke test also completed synthetic rename approval, billing-address rejection and CHOW approval against the isolated fake adapter, ending at two applied and one rejected proposal. The live ledger was only viewed in preview mode. Global history pagination was checked in the browser: 50 initial events plus 9 older events, with no remaining Load more button.

`deliverables/bellhaven-update.mp4` is a supplemental narrated still-image walkthrough of the new history features. It does not replace the original real-action screen recording and contains no replayed live approvals. Screenshots come from the preserved live review ledger in preview mode; narration is synthesized English speech.
