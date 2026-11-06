"""Local approval UI and journaled CRM executor. Bind to loopback only."""
import argparse
import fcntl
import json
import os
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from discover import BASE, accounts
from reconcile import protected, street

ROOT = Path(__file__).resolve().parent


class CRM:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, fields=None):
        data = json.dumps(fields).encode() if fields is not None else None
        req = Request(BASE + '/api/v1' + path, data=data, method=method,
                      headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=30) as response:
            value = json.load(response)
        return value.get('data', value) if isinstance(value, dict) else value

    def get(self, ident):
        return self.request('GET', '/accounts/' + ident)

    def all(self):
        return accounts(self.token)

    def create(self, fields):
        return self.request('POST', '/accounts', fields)

    def patch(self, ident, fields):
        return self.request('PATCH', '/accounts/' + ident, fields)


class Review:
    def __init__(self, path, crm=None):
        self.path, self.crm = str(path), crm
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, proposal_id TEXT, action TEXT, reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS steps (proposal_id TEXT, step INTEGER, state TEXT, result TEXT, PRIMARY KEY(proposal_id,step));
            CREATE INDEX IF NOT EXISTS events_proposal_id ON events(proposal_id,id);
            ''')

    def db(self):
        return sqlite3.connect(self.path, timeout=30)

    def get(self, ident):
        with self.db() as db:
            row = db.execute('SELECT status,payload FROM proposals WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('Unknown proposal')
        p = json.loads(row[1]); p['status'] = row[0]
        with self.db() as db:
            decision = db.execute("SELECT action,reason,created_at FROM events WHERE proposal_id=? AND action IN ('approve','reject') ORDER BY id DESC LIMIT 1", (ident,)).fetchone()
        p['decision'] = dict(zip(('action','reason','created_at'), decision)) if decision else None
        return p

    def history(self, proposal_id=None, before=None, limit=50):
        if not 1 <= limit <= 100 or (before is not None and before < 1):
            raise ValueError('Invalid history page parameters')
        clauses, values = [], []
        if proposal_id:
            self.get(proposal_id)
            clauses.append('proposal_id=?'); values.append(proposal_id)
        if before is not None:
            clauses.append('id<?'); values.append(before)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.db() as db:
            rows = db.execute('SELECT id,proposal_id,action,reason,created_at FROM events'+where+' ORDER BY id DESC LIMIT ?', values+[limit+1]).fetchall()
        events = [dict(zip(('id','proposal_id','action','reason','created_at'), r)) for r in rows[:limit]]
        return {'events':events, 'next_cursor':events[-1]['id'] if len(rows)>limit else None}

    def list(self):
        with self.db() as db:
            rows = db.execute("SELECT id FROM proposals WHERE status != 'superseded' ORDER BY created_at,id").fetchall()
            events = [dict(zip(('proposal_id','action','reason','created_at'), r)) for r in db.execute('SELECT proposal_id,action,reason,created_at FROM events ORDER BY id DESC LIMIT 100')]
        return {'proposals': [self.get(r[0]) for r in rows], 'events': events, 'writes_enabled': self.crm is not None}

    def decision(self, ident, action, reason):
        if action not in ('approve', 'reject') or not reason.strip():
            raise ValueError('A decision and review reason are required')
        if action == 'approve' and self.crm is None:
            raise ValueError('CRM writes are disabled; start with --enable-writes and an API token')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,payload FROM proposals WHERE id=?', (ident,)).fetchone()
            if not row or row[0] != 'pending':
                raise ValueError('Only pending proposals can be decided')
            p = json.loads(row[1])
            if action == 'approve':
                if not p['operations']:
                    raise ValueError('Manual investigation required; no executable operation')
                for dep in p['depends_on']:
                    state = db.execute('SELECT status FROM proposals WHERE id=?', (dep,)).fetchone()
                    if not state or state[0] != 'applied':
                        raise ValueError('Apply prerequisite proposals first')
            db.execute('UPDATE proposals SET status=? WHERE id=?', ('approved' if action == 'approve' else 'rejected', ident))
            db.execute('INSERT INTO events(proposal_id,action,reason) VALUES (?,?,?)', (ident,action,reason))
        if action == 'approve':
            self.execute(ident)
        return self.get(ident)

    def execute(self, ident):
        if self.crm is None:
            raise ValueError('CRM writes disabled')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = db.execute('SELECT status FROM proposals WHERE id=?', (ident,)).fetchone()
            if not state or state[0] not in ('approved','failed'):
                raise ValueError('Execution requires an approved or retryable failed proposal')
            db.execute("UPDATE proposals SET status='applying' WHERE id=?", (ident,))
        p = self.get(ident)
        try:
            for dep in p['depends_on']:
                if self.get(dep)['status'] != 'applied':
                    raise ValueError('Prerequisite is not applied')
            refs = {}
            before = {a['account_id']: a for a in p['evidence']['accounts']}
            for index, op in enumerate(p['operations']):
                with self.db() as db:
                    step = db.execute('SELECT state,result FROM steps WHERE proposal_id=? AND step=?', (ident,index)).fetchone()
                fields = {k: refs[v['ref']] if isinstance(v,dict) else v for k,v in op['fields'].items()}
                if step and step[0] == 'done':
                    saved = json.loads(step[1])
                    fresh = self.crm.get(saved['account_id'])
                    if any(fresh.get(k) != v for k,v in fields.items()):
                        raise RuntimeError('Completed step no longer matches approved fields; investigate before retrying')
                    if op.get('ref'):
                        refs[op['ref']] = saved['account_id']
                    continue
                if op['type'] == 'create':
                    # A crash or timeout after sending POST is ambiguous: never send it twice.
                    if step:
                        raise RuntimeError('Uncertain creation outcome. Inspect CRM and resolve the journal before retrying; no second POST sent.')
                    if p['kind'] == 'chow':
                        old = p['evidence']['accounts'][0]
                        self.check_before(old, self.crm.get(old['account_id']))
                        if not protected(old):
                            raise ValueError('CHOW financial prerequisites changed')
                    for a in self.crm.all():
                        if (a['parent_id'] == fields['parent_id'] and not a.get('duplicate_of_account')
                            and street(a['billing_street']) == street(fields['billing_street'])
                            and a['billing_city'].lower() == fields['billing_city'].lower()
                            and a['billing_state'] == fields['billing_state']):
                            raise ValueError('A current account already exists at this location; refresh reconciliation')
                else:
                    current = self.crm.get(op['account_id'])
                    # Recover a PATCH whose response was lost, but only when journaled.
                    if step and all(current.get(k) == v for k,v in fields.items()):
                        self.done(ident,index,current)
                        continue
                    self.check_before(before[op['account_id']], current)
                    if 'parent_id' in fields and fields['parent_id'] != current['parent_id'] and protected(current):
                        raise ValueError('SOP prevents moving an account with revenue and outstanding AR')
                    if 'duplicate_of_account' in fields:
                        survivor = self.crm.get(fields['duplicate_of_account'])
                        if survivor.get('duplicate_of_account') or survivor.get('chow_current_account') or survivor['status'] != 'Active':
                            raise ValueError('Duplicate survivor is not a current active account')
                        c = p['evidence']['community']
                        if street(survivor['billing_street']) != street(c['street']) or survivor['billing_city'] != c['city'] or survivor['billing_state'] != c['state']:
                            raise ValueError('Survivor location changed')
                        if current['lifetime_revenue'] > 0 or current['outstanding_ar'] > 0:
                            raise ValueError('Do not deactivate a duplicate with billing history')
                with self.db() as db:
                    db.execute('INSERT OR REPLACE INTO steps VALUES (?,?,?,?)', (ident,index,'sending',None))
                result = self.crm.create(fields) if op['type']=='create' else self.crm.patch(op['account_id'],fields)
                account_id = result.get('account_id')
                if not account_id:
                    raise RuntimeError('Write response omitted account_id; outcome requires investigation')
                # Save the create ID before verification so a later GET failure cannot cause another POST.
                self.done(ident,index,result)
                fresh = self.crm.get(account_id)
                if any(fresh.get(k) != v for k,v in fields.items()):
                    raise RuntimeError('CRM read-back does not match the approved fields; inspect before proceeding')
                if op.get('ref'):
                    refs[op['ref']] = account_id
            with self.db() as db:
                db.execute("UPDATE proposals SET status='applied' WHERE id=?", (ident,))
                db.execute('INSERT INTO events(proposal_id,action,reason) VALUES (?,?,?)', (ident,'applied','All approved steps completed and read back'))
        except Exception as exc:
            with self.db() as db:
                db.execute("UPDATE proposals SET status='failed' WHERE id=?", (ident,))
                db.execute('INSERT INTO events(proposal_id,action,reason) VALUES (?,?,?)', (ident,'failed',str(exc)))
            raise

    @staticmethod
    def check_before(expected, current):
        changed = [k for k,v in expected.items() if k not in ('updated_at','parent_name') and current.get(k) != v]
        if changed:
            raise ValueError('Stale proposal: CRM changed fields: ' + ', '.join(changed))

    def done(self, ident,index,result):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO steps VALUES (?,?,?,?)', (ident,index,'done',json.dumps(result)))


def make_server(review, port=0):
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def send(self,value,status=200,content_type='application/json'):
            body = json.dumps(value).encode() if content_type=='application/json' else value
            self.send_response(status);self.send_header('Content-Type',content_type)
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers();self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.valid_host():
                self.send({'error':'Invalid host'},403);return
            if self.path=='/':
                self.send((ROOT/'web/index.html').read_bytes(),content_type='text/html; charset=utf-8')
            elif urlparse(self.path).path=='/api/history':
                try:
                    query=parse_qs(urlparse(self.path).query)
                    self.send(review.history(query.get('proposal_id',[None])[0], int(query['before'][0]) if 'before' in query else None, int(query.get('limit',['50'])[0])))
                except (ValueError, KeyError) as exc:
                    self.send({'error':str(exc)},400)
            elif self.path=='/api/queue':
                self.send({**review.list(),'csrf':csrf})
            else:
                self.send({'error':'Not found'},404)

        def do_POST(self):
            if not self.valid_host():
                self.send({'error':'Invalid host'},403);return
            if self.headers.get('X-Review-Token') != csrf:
                self.send({'error':'Invalid review token'},403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size > 10000: raise ValueError('Request too large')
                body=json.loads(self.rfile.read(size))
                if self.path=='/api/decide':result=review.decision(body['id'],body['action'],body['reason'])
                elif self.path=='/api/retry':
                    review.execute(body['id']);result=review.get(body['id'])
                else:raise ValueError('Unknown action')
                self.send(result)
            except Exception as exc:
                self.send({'error':str(exc)},409)

        def log_message(self,*args):
            pass

    return HTTPServer(('127.0.0.1',port),Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--db',type=Path,default=ROOT/'data/review.sqlite3')
    parser.add_argument('--enable-writes',action='store_true')
    args = parser.parse_args()
    token = os.environ.get('BELLHAVEN_API_TOKEN','')
    if args.enable_writes and not token:
        parser.error('BELLHAVEN_API_TOKEN is required to enable writes')
    # Hold a process lock so only one review server can execute this queue.
    instance_lock = open(str(args.db) + '.app.lock', 'a')
    try:
        fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Another review server is using this database')
    review = Review(args.db, CRM(token) if args.enable_writes else None)
    with review.db() as db:
        interrupted = db.execute("SELECT id FROM proposals WHERE status='applying'").fetchall()
        for (ident,) in interrupted:
            db.execute("UPDATE proposals SET status='failed' WHERE id=?", (ident,))
            db.execute('INSERT INTO events(proposal_id,action,reason) VALUES (?,?,?)',
                       (ident, 'interrupted', 'Server restarted during execution; inspect journal and retry approved operation'))
    print(f'Review app: http://127.0.0.1:{args.port} | writes enabled: {args.enable_writes}',flush=True)
    make_server(review,args.port).serve_forever()


if __name__=='__main__':
    main()
