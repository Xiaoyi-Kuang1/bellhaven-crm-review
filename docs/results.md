# Verified review results

[Back to project](../README.md)

These results describe the November 4, 2026 sandbox reconciliation. They are historical verification results, not a new live audit. The [evidence bundle](../examples/completed-review.zip) preserves the review ledger, snapshots, and audit reports.

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

Each website community has a distinct active account under Bellhaven. All original `lifetime_revenue` and `outstanding_ar` values are unchanged, and every changed original business field is covered by an approved operation. The latest read-only audit is `data/verification/20261104T192958Z/report.json`. 

## Actual decisions

The 29 applied proposals comprised four new locations, four direct reparentings, nine field updates, two CHOW workflows, seven duplicate links and three `Needs Review` flags. Six accounts were created: four missing locations plus two CHOW current accounts.

- **New accounts:** Amberly Manor in Hudson, Bellhaven at Union Square, Batavia and Carlisle. The Colorado Amberly namesake and the different New Albany street address were not treated as matches.
- **Direct reparenting:** Lima, Findlay, Kettering and Zanesville.
- **CHOW:** Marietta (`51250` revenue / `3800` AR) and Tiffin (`84000` / `12400`). The originals retain their Cedar Trail parents and historical balances; only their CHOW links changed.
- **Absent from website:** Alliance, Coldwater and Sandusky are `Needs Review`. Absence does not prove closure or sale. Sandusky's other-brand same-address account is a lead, not sufficient ownership evidence; its parent and billing history were preserved.
- **Rejected:** Ashtabula's proposed billing-address replacement. A website physical address does not establish that a CRM billing PO box is wrong. This rejection is retained and does not re-enter the queue on an unchanged rerun.

Every mutation passed through the application's approval executor with a recorded rationale. The first examples and final approval/rejection were performed in the UI; the other individually reviewed proposals were approved through the same application's HTTP endpoint in dependency order. No write bypassed the executor. The sandbox accepted `Active`, `Inactive` and `Needs Review`, as well as the approved POST/PATCH payloads, and the results were read back.

## Demonstration evidence

The [current-interface recording](demo/README.md) walks through the preserved decisions. The original live approval and rejection footage is linked in that guide. No decisions were reset for recording.
