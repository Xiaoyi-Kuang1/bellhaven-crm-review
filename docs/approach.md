# Reconciliation approach

[Back to project](../README.md)

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

## Approval, retries and repeat runs

Approval is persisted before execution; rejection never contacts the CRM. Requests require a per-process review token and valid loopback Host header. A process lock allows only one review server per database. Repeated decision clicks cannot execute a decided proposal again.

Before writes, the executor refetches original accounts, checks for stale evidence, rechecks financial SOP, validates duplicate survivors and enforces prerequisites. Each operation is journaled and read back. A saved create ID allows a failed CHOW link to resume without another create. An ambiguous POST response stops for investigation rather than blindly retrying. Known completed steps are checked again during recovery; interrupted executions are marked failed on restart.

Proposal fingerprints contain the source URL, intended operations and original values of fields being changed. Parent transfers include financial prerequisites. Incidental timestamps, source hashes or unrelated survivor corrections do not generate a new decision. Material changes to relevant fields can generate a new proposal. Pending evidence refreshes, obsolete pending proposals are superseded, and decided records retain their original evidence. The ledger also retains 30 superseded pre-execution development records; they are excluded from the active queue.

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
