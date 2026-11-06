"""Isolated crawler -> reconciliation -> HTTP review -> CRM adapter -> rerun tests."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from discover import scrape
from reconcile import generate, persist
from review import Review, make_server
from test_reconcile import PARENT, ACCOUNT
from test_review import FakeCRM


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / 'raw').mkdir()
        self.db = self.folder / 'review.sqlite3'
        self.server = None
        names = ['Rename Test', 'Billing Test', 'CHOW Test']
        details = {}
        for i, name in enumerate(names):
            details[f'/communities/{i}'] = f'''<div class="wrap"><h1>{name}</h1><dl class="detail">
            <dt>Address</dt><dd>{10+i} Main Street<br>Test City, OH 44101</dd>
            <dt>Care Offerings</dt><dd><span class="badge">Assisted Living</span></dd>
            <dt>Phone</dt><dd>1234567890</dd></dl></div>'''
        links = ''.join(f'<div class="card"><h3><a href="/communities/{i}">{name}</a></h3></div>' for i,name in enumerate(names))
        pages = {'/':'<p>We serve 3 communities</p>'+links, '/about':links,
                 '/communities':'<p>Page 1 of 1 · 3 communities listed</p>'+links, **details}
        with patch('discover.fetch', side_effect=lambda path: pages[path].encode()):
            self.communities, self.sources = scrape(self.folder)
        rows = [copy.deepcopy(PARENT)]
        for i,name in enumerate(names):
            rows.append({**ACCOUNT, 'account_id':str(i), 'name':name, 'billing_street':f'{10+i} Main St'})
        rows[1]['name']='Outdated Name'
        rows[2]['billing_street']='PO Box 123'
        rows[3].update(parent_id='old', lifetime_revenue=100, outstanding_ar=20)
        self.crm = FakeCRM(rows)
        self.initial = copy.deepcopy(rows)
        result = generate(self.communities, rows)
        persist(self.db,result)
        self.ids = {p['title']:p['id'] for p in result['proposals']}
        self.start()

    def start(self):
        self.app = Review(self.db,self.crm)
        self.server = make_server(self.app)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.csrf = self.request('/api/queue')['csrf']

    def stop(self):
        if self.server:
            self.server.shutdown();self.server.server_close();self.thread.join()
            self.server=None

    def tearDown(self):
        self.stop();self.tmp.cleanup()

    def request(self,path,body=None,csrf=True):
        headers={'Content-Type':'application/json'}
        if body is not None and csrf:headers['X-Review-Token']=self.csrf
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urlopen(req,timeout=5) as response:return json.load(response)

    def decide(self,title,action):
        return self.request('/api/decide',{'id':self.ids[title],'action':action,'reason':'Reviewed fixture evidence'})

    def test_complete_workflow_and_restart_rerun(self):
        self.assertEqual(len(self.communities),3)
        with self.assertRaises(HTTPError) as error:
            self.request('/api/decide',{'id':self.ids['Rename Test'],'action':'approve','reason':'test'},csrf=False)
        self.assertEqual(error.exception.code,403)
        self.assertEqual(self.crm.writes,[])
        self.decide('Rename Test','approve')
        self.decide('Billing Test','reject')
        self.decide('CHOW Test','approve')
        self.assertEqual(len(self.crm.writes),3)
        old=self.crm.get('2')
        self.assertEqual({k:v for k,v in old.items() if k!='chow_current_account'},
                         {k:v for k,v in self.initial[3].items() if k!='chow_current_account'})
        self.stop();self.start()
        rerun=generate(self.communities,self.crm.all())
        self.assertEqual(persist(self.db,rerun),0)
        self.assertEqual([p['status'] for p in rerun['proposals']],['rejected'])
        with self.assertRaises(HTTPError):self.decide('Rename Test','approve')
        self.assertEqual(len(self.crm.writes),3)

    def test_partial_chow_resume_over_http_after_restart(self):
        self.crm.fail_patch=True
        with self.assertRaises(HTTPError):self.decide('CHOW Test','approve')
        self.assertEqual(self.app.get(self.ids['CHOW Test'])['status'],'failed')
        self.stop();self.crm.fail_patch=False;self.start()
        self.request('/api/retry',{'id':self.ids['CHOW Test']})
        self.assertEqual(sum(kind=='create' for kind,_ in self.crm.writes),1)
        self.assertEqual(self.crm.get('2')['parent_id'],'old')
        self.assertEqual(self.crm.get('2')['chow_current_account'],'new')

    def test_older_decision_and_paginated_history(self):
        ident=self.ids['Billing Test']
        self.decide('Billing Test','reject')
        with self.app.db() as db:
            for i in range(125):
                db.execute('INSERT INTO events(proposal_id,action,reason) VALUES (?,?,?)',(ident,'audit',str(i)))
        queue=self.request('/api/queue')
        proposal=next(p for p in queue['proposals'] if p['id']==ident)
        self.assertEqual(proposal['decision']['reason'],'Reviewed fixture evidence')
        cursor=None;seen=[]
        while True:
            page=self.request('/api/history?proposal_id='+ident+('&before='+str(cursor) if cursor else ''))
            seen.extend(page['events']);cursor=page['next_cursor']
            if cursor is None:break
        self.assertEqual(len(seen),126)
        self.assertEqual(len({e['id'] for e in seen}),126)
        self.assertEqual(seen[-1]['action'],'reject')
        with self.assertRaises(HTTPError):self.request('/api/history?limit=1000')
