"""Deterministic, offline reconciliation. Produces proposals, never calls CRM APIs."""
import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from discover import validate_evidence

CARE = {'Assisted Living': 'Assisted Living', 'Memory Support': 'Memory Care',
        'Short-Term Rehabilitation & Nursing': 'Skilled Nursing'}
WORDS = dict(avenue='ave', boulevard='blvd', street='st', road='rd', drive='dr',
             lane='ln', court='ct', northwest='nw', northeast='ne', southwest='sw',
             southeast='se', north='n', south='s', east='e', west='w', pike='pike', pk='pike')


def norm(value):
    return ' '.join(re.findall(r'[a-z0-9]+', (value or '').lower()))


def street(value):
    return ' '.join(WORDS.get(w, w) for w in norm(value).split())


def money(account, field):
    try:
        value = Decimal(str(account[field]))
        if not value.is_finite() or value < 0:
            raise ValueError('Invalid financial value')
        return value
    except (KeyError, InvalidOperation, TypeError):
        raise ValueError(f'Missing or invalid {field} for {account.get("account_id")}')


def protected(account):
    # Evaluate both, so missing AR cannot be treated as zero even when revenue is zero.
    revenue, ar = money(account, 'lifetime_revenue'), money(account, 'outstanding_ar')
    return revenue > 0 and ar > 0


def candidate(c, a):
    same_city = norm(c['city']) == norm(a['billing_city'])
    same_state = c['state'] == a['billing_state']
    address = bool(street(c['street'])) and street(c['street']) == street(a['billing_street'])
    name = norm(c['name']) == norm(a['name'])
    phone = re.sub(r'\D', '', c['phone']) == re.sub(r'\D', '', a['phone']) and bool(re.sub(r'\D', '', c['phone']))
    # ZIP errors are repairable when street, city and state corroborate identity.
    if same_city and same_state and address:
        return 'high', 'City, state, and normalized street address match; ZIP differences are proposed corrections'
    if same_city and same_state and name and phone:
        return 'medium', 'Name, city, state, and phone match, but street addresses differ; review physical versus billing address usage'
    return None


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def append_note(a, message):
    old = a.get('note', '').strip()
    return old if message in old else '\n'.join(x for x in [old, message] if x)


def desired(c, parent):
    kinds = [CARE[k] for k in c['care_offerings']]
    result = dict(name=c['name'], parent_id=parent, billing_street=c['street'],
                  billing_city=c['city'], billing_state=c['state'], billing_zip=c['zip'],
                  status='Active', care_type=kinds[0])
    if len(kinds) > 1:
        result['note'] = 'Website care offerings: ' + '; '.join(kinds) + '. Source: ' + c['source_url']
    return result


def patch_for(c, a, parent):
    wanted = desired(c, parent)
    # Equivalent address spellings do not need cosmetic writes.
    if street(a['billing_street']) == street(wanted['billing_street']):
        wanted.pop('billing_street')
    # API schema exposes a single care_type. Preserve a valid existing primary type;
    # retain ALL offerings in note until multi-value support is verified.
    kinds = [CARE[k] for k in c['care_offerings']]
    if a['care_type'] in kinds:
        wanted.pop('care_type')
    if 'note' in wanted:
        wanted['note'] = append_note(a, wanted['note'])
    return {k: v for k, v in wanted.items() if a.get(k) != v}


def generate(communities, accounts):
    parents = [a for a in accounts if a['name'] == 'Bellhaven Senior Living (Parent Account)' and not a['parent_id']]
    if len(parents) != 1:
        raise ValueError('Expected exactly one verified Bellhaven parent')
    parent = parents[0]['account_id']
    if len({a['account_id'] for a in accounts}) != len(accounts):
        raise ValueError('Duplicate account IDs')
    proposals, matches, used = [], [], set()
    by_id = {a['account_id']: a for a in accounts}
    for a in accounts:
        for field in ('duplicate_of_account', 'chow_current_account'):
            target = a.get(field)
            if target and (target == a['account_id'] or target not in by_id):
                raise ValueError(f'Broken {field} on {a["account_id"]}; investigate before matching')
            if target and (by_id[target].get('duplicate_of_account') or by_id[target].get('chow_current_account')):
                raise ValueError(f'Chained {field} on {a["account_id"]}; investigate before matching')
    active = [a for a in accounts if not a['name'].endswith('(Parent Account)')
              and not a.get('duplicate_of_account') and not a.get('chow_current_account')]
    claims = {}
    for c in communities:
        for a in active:
            if candidate(c, a):
                claims.setdefault(a['account_id'], []).append(c['source_url'])
    conflicts = {key for key, values in claims.items() if len(values) > 1}

    def add(kind, c, rows, changes, reason, confidence='high', dependencies=None):
        # Identity describes the decision, not incidental changes to other accounts.
        # Current before-values remain in evidence for execution-time stale checks.
        evidence = {'community': c, 'accounts': rows, 'reason': reason}
        identity = {'version': 2, 'kind': kind, 'source_url': c['source_url'] if c else None,
                    'changes': changes}
        if not changes:
            identity['account_ids'] = sorted(a['account_id'] for a in rows)
        # A changed before-value of a field being edited is a materially new decision.
        before = []
        for operation in changes:
            if operation['type'] != 'patch':
                continue
            account = by_id[operation['account_id']]
            fields = set(operation['fields'])
            if 'parent_id' in fields or 'chow_current_account' in fields:
                fields.update(('parent_id', 'lifetime_revenue', 'outstanding_ar'))
            before.append({'account_id': account['account_id'],
                           'fields': {k: account.get(k) for k in sorted(fields)}})
        identity['before'] = before
        p = {'id': fingerprint(identity), 'kind': kind, 'confidence': confidence,
             'title': c['name'] if c else rows[0]['name'], 'evidence': evidence,
             'operations': changes, 'depends_on': dependencies or [], 'status': 'pending'}
        proposals.append(p)
        return p['id']

    for c in communities:
        hits = [(a, candidate(c, a)) for a in active if candidate(c, a)]
        if any(a['account_id'] in conflicts for a, _ in hits):
            used.update(a['account_id'] for a, _ in hits)
            add('manual_review', c, [a for a, _ in hits], [], 'One account matches multiple website locations; manual review is required', 'low')
            matches.append({'community': c['name'], 'classification': 'manual_review'})
            continue
        if not hits:
            # Show misleading alternatives explicitly; do not create false matches.
            alternatives = [a for a in active if norm(a['name']) == norm(c['name']) or
                            (norm(a['billing_city']) == norm(c['city']) and a['billing_state'] == c['state'])]
            fields = desired(c, parent)
            add('create', c, alternatives, [{'type': 'create', 'fields': fields}],
                'No address match in the complete CRM snapshot. Same-name or same-city candidates have different addresses and are not reused. Create an account under the Bellhaven parent.')
            matches.append({'community': c['name'], 'classification': 'create'})
            continue
        # Prefer an existing current Bellhaven account, then preserve financial history,
        # then exact name and website phone. Final ID tie-break is deterministic, not evidence.
        hits.sort(key=lambda hit: (hit[1][0] == 'high', hit[0]['status'] == 'Active',
                                  hit[0]['parent_id'] == parent, money(hit[0], 'lifetime_revenue'),
                                  norm(hit[0]['name']) == norm(c['name']),
                                  norm(hit[0]['phone']) == norm(c['phone']),
                                  hit[0]['account_id']), reverse=True)
        a, (confidence, why) = hits[0]
        rows = [h[0] for h in hits]
        used.update(r['account_id'] for r in rows)
        changes = patch_for(c, a, parent)
        dependency = None
        if a['parent_id'] != parent and protected(a):
            kind = 'chow'
            dependency = add(kind, c, [a], [
                {'type': 'create', 'ref': 'current_account', 'fields': desired(c, parent)},
                {'type': 'patch', 'account_id': a['account_id'],
                 'fields': {'chow_current_account': {'ref': 'current_account'}}}],
                why + '; lifetime revenue and outstanding AR are both positive. Preserve the original account fields and parent; only set its CHOW link.', confidence)
        elif changes:
            kind = 'reparent' if 'parent_id' in changes else 'update'
            dependency = add(kind, c, [a], [{'type': 'patch', 'account_id': a['account_id'], 'fields': changes}], why, confidence)
        else:
            kind = 'exact'
        matches.append({'community': c['name'], 'account_id': a['account_id'],
                        'classification': kind, 'candidate_ids': [r['account_id'] for r in rows]})
        for duplicate in rows[1:]:
            if (money(duplicate, 'outstanding_ar') > 0 or money(duplicate, 'lifetime_revenue') > 0 or kind == 'chow'
                    or candidate(c, duplicate)[0] != 'high' or confidence != 'high'
                    or duplicate['care_type'] != a['care_type']):
                add('manual_review', c, [duplicate, a], [], 'Accounts at this location involve billing history, CHOW, or conflicting care types. Do not deactivate an account based on its address alone.', 'low')
                continue
            note = f'Duplicate of {a["account_id"]}; same normalized location. Source: {c["source_url"]}. Preserve contacts and history; no merge/delete.'
            add('duplicate', c, [duplicate, a], [{'type': 'patch', 'account_id': duplicate['account_id'],
                'fields': {'duplicate_of_account': a['account_id'], 'status': 'Inactive',
                           'note': append_note(duplicate, note)}}],
                'Street address, city, state, and care type match. Prefer the current Bellhaven account, billing history, website name, and phone. Use account ID only as a deterministic tie-break requiring review. Preserve the duplicate account parent and contacts.',
                'medium', [dependency] if dependency else [])

    for a in accounts:
        if a['parent_id'] != parent or a['account_id'] in used or a.get('duplicate_of_account') or a.get('chow_current_account'):
            continue
        peers = [r for r in active if r['account_id'] != a['account_id'] and
                 street(r['billing_street']) == street(a['billing_street']) and
                 norm(r['billing_city']) == norm(a['billing_city']) and r['billing_state'] == a['billing_state']]
        note = 'Not found in complete Bellhaven website crawl. Ownership/closure unverified; retain parent and billing history pending investigation.'
        fields = {'status': 'Needs Review', 'note': append_note(a, note)}
        fields = {k: v for k, v in fields.items() if a.get(k) != v}
        if fields:
            add('not_on_website', None, [a] + peers, [{'type': 'patch', 'account_id': a['account_id'], 'fields': fields}],
                'Absence from the website does not establish closure or sale. Other-brand accounts at the same address are leads only; do not change ownership or mark duplicates on that evidence alone. Verify the Needs Review status value before writing.', 'low')
    return {'parent_id': parent, 'matches': matches, 'proposals': proposals,
            'summary': {'communities': len(communities), 'classifications': dict(Counter(m['classification'] for m in matches)),
                        'proposal_types': dict(Counter(p['kind'] for p in proposals)), 'proposals': len(proposals)}}


def persist(db_path, result):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        # Retain history but remove obsolete pending proposals from the active queue.
        current_ids = {p['id'] for p in result['proposals']}
        for (old_id,) in db.execute("SELECT id FROM proposals WHERE status='pending'").fetchall():
            if old_id not in current_ids:
                db.execute("UPDATE proposals SET status='superseded' WHERE id=?", (old_id,))
        inserted = 0
        for p in result['proposals']:
            inserted += db.execute('INSERT OR IGNORE INTO proposals (id,status,payload) VALUES (?,?,?)',
                                   (p['id'], 'pending', json.dumps(p, ensure_ascii=False))).rowcount
            status = db.execute('SELECT status FROM proposals WHERE id=?', (p['id'],)).fetchone()[0]
            if status in ('pending', 'superseded'):
                p['status'] = 'pending'
                db.execute("UPDATE proposals SET status='pending',payload=? WHERE id=?",
                           (json.dumps(p, ensure_ascii=False), p['id']))
            else:
                p['status'] = status
        return inserted



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--db', type=Path, default=Path('data/review.sqlite3'))
    args = parser.parse_args()
    snapshot = args.snapshot or max(p.parent for p in Path('data/snapshots').glob('*/manifest.json'))
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    if manifest.get('complete') is not True:
        raise ValueError('Incomplete snapshot')
    cs = json.loads((snapshot / 'communities.json').read_text())
    aa = json.loads((snapshot / 'accounts.json').read_text())
    if len(cs) != manifest['communities'] or len(aa) != manifest['accounts']:
        raise ValueError('Snapshot count mismatch')
    validate_evidence(snapshot, cs, json.loads((snapshot / 'sources.json').read_text()))
    result = generate(cs, aa)
    inserted = persist(args.db, result)
    (snapshot / 'reconciliation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({**result['summary'], 'new_queue_entries': inserted, 'crm_writes': 0}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
