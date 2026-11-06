import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from reconcile import generate, persist
from review import Review
from test_reconcile import PARENT, COMMUNITY, ACCOUNT


class FakeCRM:
    def __init__(self, rows):
        self.rows={a['account_id']:copy.deepcopy(a) for a in rows};self.writes=[]
        self.fail_patch=False;self.lose_create=False
    def get(self, ident):return copy.deepcopy(self.rows[ident])
    def all(self):return list(self.rows.values())
    def create(self,fields):
        self.writes.append(('create',fields))
        a={**ACCOUNT,**fields,'account_id':'new'};self.rows['new']=a
        if self.lose_create:raise TimeoutError('Simulated lost POST response')
        return copy.deepcopy(a)
    def patch(self,ident,fields):
        if self.fail_patch:raise TimeoutError('Simulated PATCH failure')
        self.writes.append(('patch',fields));self.rows[ident].update(fields)
        return self.get(ident)


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'test.sqlite3'
    def tearDown(self):self.tmp.cleanup()
    def setup_case(self,**changes):
        a={**ACCOUNT,**changes};crm=FakeCRM([PARENT,a]);r=generate([COMMUNITY],[PARENT,a]);persist(self.db,r)
        return Review(self.db,crm),crm,r['proposals'][0]['id']
    def test_no_unapproved_writes(self):
        app,crm,ident=self.setup_case(name='Old')
        with self.assertRaises(ValueError):app.execute(ident)
        self.assertEqual(crm.writes,[])
    def test_rejection_never_writes(self):
        app,crm,ident=self.setup_case(name='Old');app.decision(ident,'reject','Insufficient evidence')
        self.assertEqual(app.get(ident)['status'],'rejected');self.assertEqual(crm.writes,[])
    def test_approve_and_repeat_click(self):
        app,crm,ident=self.setup_case(name='Old');app.decision(ident,'approve','Address matches')
        self.assertEqual(app.get(ident)['status'],'applied')
        with self.assertRaises(ValueError):app.decision(ident,'approve','Again')
        self.assertEqual(len(crm.writes),1)
    def test_stale_account_blocks_write(self):
        app,crm,ident=self.setup_case(name='Old');crm.rows['a']['note']='New human edit'
        with self.assertRaises(ValueError):app.decision(ident,'approve','Address matches')
        self.assertEqual(crm.writes,[])
    def test_financial_change_blocks_reparent(self):
        app,crm,ident=self.setup_case(parent_id='old');crm.rows['a'].update(lifetime_revenue=100,outstanding_ar=20)
        with self.assertRaises(ValueError):app.decision(ident,'approve','Move')
        self.assertEqual(crm.writes,[])
    def test_chow_retry_does_not_create_twice(self):
        app,crm,ident=self.setup_case(parent_id='old',lifetime_revenue=100,outstanding_ar=20)
        crm.fail_patch=True
        with self.assertRaises(TimeoutError):app.decision(ident,'approve','Preserve billing')
        crm.fail_patch=False;app.execute(ident)
        self.assertEqual(sum(k=='create' for k,v in crm.writes),1)
        self.assertEqual(crm.rows['a']['parent_id'],'old')
        self.assertEqual(crm.rows['a']['chow_current_account'],'new')
    def test_lost_create_response_never_reposts(self):
        app,crm,ident=self.setup_case(parent_id='old',lifetime_revenue=100,outstanding_ar=20)
        crm.lose_create=True
        with self.assertRaises(TimeoutError):app.decision(ident,'approve','Preserve billing')
        with self.assertRaises(RuntimeError):app.execute(ident)
        self.assertEqual(len(crm.writes),1)
    def test_changed_completed_step_does_not_silently_pass(self):
        app,crm,ident=self.setup_case(parent_id='old',lifetime_revenue=100,outstanding_ar=20)
        crm.fail_patch=True
        with self.assertRaises(TimeoutError):app.decision(ident,'approve','Preserve billing')
        crm.rows['new']['name']='Someone changed this';crm.fail_patch=False
        with self.assertRaises(RuntimeError):app.execute(ident)
        self.assertEqual(crm.rows['a']['chow_current_account'],'')

if __name__=='__main__':unittest.main()
