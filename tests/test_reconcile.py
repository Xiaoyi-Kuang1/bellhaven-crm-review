import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from reconcile import generate, persist, protected, street

PARENT = dict(account_id='parent', name='Bellhaven Senior Living (Parent Account)', parent_id='')
COMMUNITY = dict(name='Bellhaven Test', street='10 Northwest Main Street', city='Test City',
                 state='OH', zip='44101', care_offerings=['Assisted Living'],
                 phone='1234567890', source_url='https://example.test/test', source_sha256='abc')
ACCOUNT = dict(account_id='a', name='Bellhaven Test', parent_id='parent', billing_street='10 NW Main St',
               billing_city='Test City', billing_state='OH', billing_zip='44101', care_type='Assisted Living',
               status='Active', phone='1234567890', lifetime_revenue=0, outstanding_ar=0,
               chow_current_account='', duplicate_of_account='', note='')


class ReconciliationTests(unittest.TestCase):
    def run_case(self, **changes):
        return generate([COMMUNITY], [PARENT, {**ACCOUNT, **changes}])

    def test_equivalent_street_is_noop(self):
        self.assertEqual(street('10 Northwest Main Street'), street('10 NW Main St.'))
        self.assertEqual(self.run_case()['proposals'], [])

    def test_same_name_wrong_state_is_new_account(self):
        self.assertEqual(self.run_case(billing_state='CO')['proposals'][0]['kind'], 'create')

    def test_same_city_different_street_and_phone_is_not_match(self):
        self.assertEqual(self.run_case(billing_street='30 Other Rd', phone='different')['proposals'][0]['kind'], 'create')

    def test_wrong_zip_repair(self):
        p = self.run_case(billing_zip='44110')['proposals'][0]
        self.assertEqual(p['operations'][0]['fields'], {'billing_zip': '44101'})

    def test_chow_preserves_old_account(self):
        p = self.run_case(parent_id='old', lifetime_revenue=100, outstanding_ar=1)['proposals'][0]
        self.assertEqual(p['kind'], 'chow')
        self.assertEqual(p['operations'][0]['fields']['parent_id'], 'parent')
        self.assertEqual(set(p['operations'][1]['fields']), {'chow_current_account'})

    def test_reparent_without_open_ar(self):
        self.assertEqual(self.run_case(parent_id='old', lifetime_revenue=100)['proposals'][0]['kind'], 'reparent')

    def test_unknown_financials_fail_closed(self):
        a = dict(ACCOUNT)
        del a['outstanding_ar']
        with self.assertRaises(ValueError):
            protected(a)

    def test_duplicates_have_survivor_and_do_not_move_parent(self):
        r = generate([COMMUNITY], [PARENT, ACCOUNT, {**ACCOUNT, 'account_id': 'b', 'parent_id': 'old'}])
        p = next(p for p in r['proposals'] if p['kind'] == 'duplicate')
        self.assertEqual(p['operations'][0]['fields']['duplicate_of_account'], 'a')
        self.assertNotIn('parent_id', p['operations'][0]['fields'])

    def test_completed_chow_legacy_is_not_duplicate(self):
        r = generate([COMMUNITY], [PARENT, ACCOUNT, {**ACCOUNT, 'account_id': 'old', 'chow_current_account': 'a'}])
        self.assertEqual(r['proposals'], [])

    def test_missing_website_preserves_finances_and_parent(self):
        r = generate([], [PARENT, {**ACCOUNT, 'lifetime_revenue': 100, 'outstanding_ar': 1}])
        fields = r['proposals'][0]['operations'][0]['fields']
        self.assertEqual(set(fields), {'status', 'note'})

    def test_multicare_not_lost(self):
        c = {**COMMUNITY, 'care_offerings': ['Assisted Living', 'Memory Support']}
        p = generate([c], [PARENT, ACCOUNT])['proposals'][0]
        self.assertIn('Memory Care', p['operations'][0]['fields']['note'])

    def test_decisions_survive_rerun_and_timestamp_change(self):
        result = self.run_case(name='Old name')
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'review.sqlite3'
            self.assertEqual(persist(db, result), 1)
            for status in ['rejected', 'applied']:
                with sqlite3.connect(db) as con:
                    con.execute('UPDATE proposals SET status=?', (status,))
                again = self.run_case(name='Old name', updated_at='later')
                self.assertEqual(persist(db, again), 0)
                self.assertEqual(again['proposals'][0]['status'], status)

    def test_post_apply_snapshot_has_no_repeated_update(self):
        result = self.run_case(name='Old name')
        a = {**ACCOUNT, 'name': 'Old name'}
        a.update(result['proposals'][0]['operations'][0]['fields'])
        self.assertEqual(generate([COMMUNITY], [PARENT, a])['proposals'], [])

    def test_duplicate_decision_survives_primary_update(self):
        primary = {**ACCOUNT, 'name': 'Old name', 'parent_id': 'old'}
        duplicate = {**ACCOUNT, 'account_id': '0', 'name': 'Other name', 'parent_id': 'other'}
        first = generate([COMMUNITY], [PARENT, primary, duplicate])
        update = next(p for p in first['proposals'] if p['kind'] == 'reparent')
        original = next(p for p in first['proposals'] if p['kind'] == 'duplicate')
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'review.sqlite3'
            persist(db, first)
            with sqlite3.connect(db) as con:
                con.execute("UPDATE proposals SET status='rejected' WHERE id=?", (original['id'],))
            primary.update(update['operations'][0]['fields'])
            second = generate([COMMUNITY], [PARENT, primary, duplicate])
            self.assertEqual(persist(db, second), 0)
            repeated = next(p for p in second['proposals'] if p['kind'] == 'duplicate')
            self.assertEqual(original['id'], repeated['id'])
            self.assertEqual(repeated['status'], 'rejected')
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT status FROM proposals WHERE id=?', (update['id'],)).fetchone()[0], 'superseded')

    def test_broken_chow_link_aborts(self):
        with self.assertRaises(ValueError):
            self.run_case(chow_current_account='missing')

    def test_ar_without_revenue_not_deactivated(self):
        r = generate([COMMUNITY], [PARENT, ACCOUNT, {**ACCOUNT, 'account_id': 'b',
                     'parent_id': 'old', 'outstanding_ar': 25}])
        self.assertFalse(any(p['kind'] == 'duplicate' for p in r['proposals']))
        self.assertTrue(any(p['kind'] == 'manual_review' for p in r['proposals']))

    def test_different_street_candidate_not_marked_duplicate(self):
        r = generate([COMMUNITY], [PARENT, ACCOUNT, {**ACCOUNT, 'account_id': 'b',
                     'billing_street': 'PO Box 1'}])
        self.assertFalse(any(p['kind'] == 'duplicate' for p in r['proposals']))

    def test_phone_punctuation_does_not_prevent_match(self):
        r = self.run_case(billing_street='PO Box 1', phone='(123) 456-7890')
        self.assertEqual(r['proposals'][0]['kind'], 'update')

    def test_new_before_value_generates_new_decision(self):
        first = self.run_case(name='Old name')['proposals'][0]['id']
        second = self.run_case(name='Another old name')['proposals'][0]['id']
        self.assertNotEqual(first, second)

    def test_unrelated_note_does_not_requeue_rejected_name_change(self):
        first = self.run_case(name='Old name')['proposals'][0]['id']
        second = self.run_case(name='Old name', note='Unrelated sales call')['proposals'][0]['id']
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
