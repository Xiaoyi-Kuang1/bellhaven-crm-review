"""Read-only audit of approved results, billing preservation and rerun behavior."""
import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from discover import accounts
from reconcile import generate, persist

ROOT = Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--db',type=Path,default=ROOT/'data/review.sqlite3')
    args=parser.parse_args()
    token=os.environ.get('BELLHAVEN_API_TOKEN')
    if not token:parser.error('BELLHAVEN_API_TOKEN is required')
    old=json.loads((args.baseline/'accounts.json').read_text())
    cs=json.loads((args.baseline/'communities.json').read_text())
    current=accounts(token);by_id={a['account_id']:a for a in current}
    checks=[];allowed={};created=[];decisions=[]
    with sqlite3.connect(args.db) as db:
        for ident,status,payload in db.execute("SELECT id,status,payload FROM proposals WHERE status!='superseded'"):
            p=json.loads(payload);decisions.append({'id':ident,'status':status,'title':p['title'],'kind':p['kind']})
            if status!='applied':continue
            refs={}
            for index,op in enumerate(p['operations']):
                row=db.execute('SELECT state,result FROM steps WHERE proposal_id=? AND step=?',(ident,index)).fetchone()
                assert row and row[0]=='done',f'Missing completed step {ident}:{index}'
                result=json.loads(row[1]);aid=result['account_id']
                fields={k:refs[v['ref']] if isinstance(v,dict) else v for k,v in op['fields'].items()}
                assert all(by_id[aid].get(k)==v for k,v in fields.items()),f'CRM differs from approved operation {ident}'
                if op['type']=='create':created.append(aid)
                else:allowed.setdefault(aid,set()).update(fields)
                if op.get('ref'):refs[op['ref']]=aid
    checks.append('Every applied operation matches current CRM values')
    for before in old:
        after=by_id[before['account_id']]
        assert before['lifetime_revenue']==after['lifetime_revenue'] and before['outstanding_ar']==after['outstanding_ar'],'Financial history changed'
        for key,value in before.items():
            if key not in allowed.get(before['account_id'],set())|{'updated_at','parent_name'}:
                assert after.get(key)==value,f'Unapproved change: {before["account_id"]}.{key}'
    checks.append('All original revenue and AR values preserved; no unapproved business field changes')
    assert len(current)==len(old)+len(created),'Unexpected account count'
    checks.append('Account count equals baseline plus approved creates')
    result=generate(cs,current)
    new_entries=persist(args.db,result)
    assert new_entries==0,'Rerun created unexpected proposals'
    assert all(p['status']=='rejected' for p in result['proposals']),'Unresolved generated proposal'
    assert all(p['status'] in ('applied','rejected') for p in decisions),'Undecided review records remain'
    matches=[m['account_id'] for m in result['matches']]
    assert len(matches)==len(set(matches))==len(cs),'Website-to-CRM mapping is not one-to-one'
    assert all(by_id[aid]['status']=='Active' and by_id[aid]['parent_id']==result['parent_id'] for aid in matches)
    checks.append('Every website community has a distinct active Bellhaven account')
    checks.append('Rerun generated no new queue entries; rejected decision remained rejected')
    output=ROOT/'data/verification'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True)
    (output/'accounts.json').write_text(json.dumps(current,indent=2))
    report={'verified_at':datetime.now(timezone.utc).isoformat(),'baseline':str(args.baseline),
            'accounts_before':len(old),'accounts_after':len(current),'created_account_ids':created,
            'website_locations':len(cs),'new_queue_entries_on_rerun':new_entries,'checks':checks,
            'decisions':decisions,'remaining_rejected_proposals':result['proposals'],'crm_writes':0}
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('decisions','remaining_rejected_proposals')},indent=2))
    print('Report:',output/'report.json')

if __name__=='__main__':main()
