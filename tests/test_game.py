"""Run with: python -m unittest discover -s tests -v (no third-party packages)."""
from __future__ import annotations
import copy
import hashlib
import json
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import (SCENARIOS, BUDGET, RuleError, Store, apply_action, fresh_state,
                    public_state, score_team, validate_state, balance)
from server import GameServer


def set_deck(s, ids):
    """Test-only deterministic fixture, never exposed as a game action."""
    r = s['round']; r['_deck'] = list(ids)
    r['commitment'] = hashlib.sha256(f'{r["id"]}|{r["_salt"]}|{",".join(ids)}'.encode()).hexdigest()


def started(profile='arena', scenario_id=1, count=3):
    s = fresh_state(); s['profile'] = profile; s['scenario_order'] = [scenario_id]; s['incident_count'] = count
    apply_action(s, 'start', {})
    return s


def buy(s, mid, tid='t1', price=None):
    if s['phase'] == 'brief': apply_action(s, 'open_auction', {})
    apply_action(s, 'focus', {'mid': mid})
    sc = next(sc for sc in SCENARIOS if sc['id'] == s['round']['scenario_id'])
    price = next(m['p'] for m in sc['mits'] if m['id'] == mid) if price is None else price
    apply_action(s, 'sell', {'mid': mid, 'team_id': tid, 'price': price})


def finish_incidents(s):
    if s['phase'] == 'brief': apply_action(s, 'open_auction', {})
    apply_action(s, 'close_auction', {})
    for _ in range(s['incident_count']): apply_action(s, 'reveal', {})


class GameRules(unittest.TestCase):
    def test_original_four_catalogues_preserved(self):
        self.assertEqual([len(x['mits']) for x in SCENARIOS], [7, 7, 7, 8])
        self.assertEqual([len(x['risks']) for x in SCENARIOS], [5, 5, 6, 6])

    def test_all_mappings_reference_distinct_existing_items(self):
        for sc in SCENARIOS:
            mids = {m['id'] for m in sc['mits']}
            for risk in sc['risks']:
                m = sc['map'][risk['id']]
                self.assertIn(m['high'], mids); self.assertIn(m['partial'], mids)
                self.assertNotEqual(m['high'], m['partial'])

    def test_initial_state_valid(self):
        s = fresh_state(); validate_state(s)
        self.assertEqual(len(s['teams']), 5)
        self.assertEqual(public_state(s)['leaderboard'][0]['total'], 0)

    def test_round_sealed_before_bidding(self):
        s = started(); self.assertEqual(s['phase'], 'brief')
        self.assertEqual(len(s['round']['_deck']), 3)
        self.assertEqual(len(set(s['round']['_deck'])), 3)
        validate_state(s)

    def test_four_incident_mode(self):
        s = started(count=4); finish_incidents(s)
        self.assertEqual(len(s['round']['revealed']), 4); validate_state(s)

    def test_public_snapshot_never_contains_future_answer_key(self):
        s = started(); snap = public_state(s)
        self.assertNotIn('map', snap['scenario'])
        self.assertNotIn('_deck', json.dumps(snap)); self.assertNotIn('_salt', json.dumps(snap))
        self.assertNotIn('answer_key', snap); self.assertNotIn('proof', snap['round'])
        self.assertIn('answer_key', public_state(s, admin=True))
        self.assertNotIn('_deck', json.dumps(public_state(s, admin=True)))

    def test_first_reveal_shares_only_that_mapping(self):
        s = started(); set_deck(s, ['R1', 'R2', 'R3'])
        apply_action(s, 'open_auction', {}); apply_action(s, 'close_auction', {}); apply_action(s, 'reveal', {})
        snap = public_state(s); self.assertEqual(len(snap['round']['incidents']), 1)
        self.assertEqual(snap['round']['incidents'][0]['rid'], 'R1')
        self.assertNotIn('proof', snap['round'])

    def test_debrief_exposes_verifiable_commitment(self):
        s = started(); finish_incidents(s)
        snap = public_state(s); self.assertTrue(snap['round']['proof']['verified'])
        p = snap['round']['proof']
        digest = hashlib.sha256(f'{p["round_id"]}|{p["salt"]}|{",".join(p["deck"])}'.encode()).hexdigest()
        self.assertEqual(digest, snap['round']['commitment'])

    def test_bid_does_not_spend_money(self):
        s = started(); apply_action(s, 'open_auction', {}); apply_action(s, 'focus', {'mid': 'M1'})
        apply_action(s, 'bid', {'mid': 'M1', 'team_id': 't1', 'price': 3000})
        self.assertEqual(balance(s, 't1'), BUDGET)
        self.assertEqual(len(s['round']['purchases']), 0)

    def test_hammer_requires_a_bid(self):
        s = started(); apply_action(s, 'open_auction', {}); apply_action(s, 'focus', {'mid': 'M1'})
        with self.assertRaises(RuleError): apply_action(s, 'call', {'value': 'twice'})

    def test_sale_spends_exact_integer_amount(self):
        s = started(); buy(s, 'M1', price=2573)
        self.assertEqual(balance(s, 't1'), 7427); validate_state(s)

    def test_price_below_reserve_rejected(self):
        s = started()
        with self.assertRaises(RuleError): buy(s, 'M1', price=2499)
        self.assertEqual(balance(s, 't1'), 10000)

    def test_negative_and_non_integer_prices_rejected(self):
        for value in [-10, 0, 2500.5, '3000', True, None, float('nan')]:
            s = started()
            apply_action(s, 'open_auction', {}); apply_action(s, 'focus', {'mid': 'M1'})
            with self.assertRaises(RuleError, msg=str(value)):
                apply_action(s, 'sell', {'mid': 'M1', 'team_id': 't1', 'price': value})

    def test_budget_limit_enforced(self):
        s = started(); buy(s, 'M4', price=9000)
        with self.assertRaises(RuleError): buy(s, 'M1')
        self.assertEqual(balance(s, 't1'), 1000)

    def test_three_purchase_limit(self):
        s = started(); buy(s, 'M1'); buy(s, 'M2'); buy(s, 'M3')
        with self.assertRaises(RuleError): buy(s, 'M7')

    def test_duplicate_item_same_team_forbidden(self):
        s = started(); buy(s, 'M1')
        with self.assertRaises(RuleError): buy(s, 'M1')

    def test_global_copy_limit(self):
        s = started(); buy(s, 'M1', 't1'); buy(s, 'M1', 't2')
        with self.assertRaises(RuleError): buy(s, 'M1', 't3')

    def test_single_copy_mode(self):
        s = started(); s['copies'] = 1; buy(s, 'M1')
        with self.assertRaises(RuleError): buy(s, 'M1', 't2')

    def test_refund_returns_cash_and_copy(self):
        s = started(); buy(s, 'M1'); pid = s['round']['purchases'][0]['id']
        apply_action(s, 'refund', {'purchase_id': pid})
        self.assertEqual(balance(s, 't1'), 10000)
        buy(s, 'M1', 't2'); validate_state(s)

    def test_auction_lock_prevents_sale_refund_and_reopen(self):
        s = started(); buy(s, 'M1'); pid = s['round']['purchases'][0]['id']
        apply_action(s, 'close_auction', {})
        for action, data in [('sell', {'mid': 'M1', 'team_id': 't2', 'price': 2500}), ('refund', {'purchase_id': pid}), ('open_auction', {}), ('focus', {'mid': 'M2'})]:
            with self.assertRaises(RuleError): apply_action(s, action, data)

    def test_cannot_reveal_while_bidding(self):
        s = started(); apply_action(s, 'open_auction', {})
        with self.assertRaises(RuleError): apply_action(s, 'reveal', {})

    def test_reveal_order_never_changes(self):
        s = started(); deck = list(s['round']['_deck']); finish_incidents(s)
        self.assertEqual(s['round']['revealed'], deck)
        with self.assertRaises(RuleError): apply_action(s, 'reveal', {})

    def test_high_cover_scores_once_not_high_plus_partial(self):
        s = started(); set_deck(s, ['R1', 'R2', 'R3']); buy(s, 'M4'); buy(s, 'M1'); finish_incidents(s)
        self.assertEqual(score_team(s, 't1')['lines'][0]['points'], 10)

    def test_partial_cover(self):
        s = started(); set_deck(s, ['R1', 'R2', 'R3']); buy(s, 'M1'); finish_incidents(s)
        self.assertEqual([l['points'] for l in score_team(s, 't1')['lines']], [5, 10, -10])

    def test_original_no_purchase_score_is_zero_for_three_risks(self):
        s = started('original'); finish_incidents(s)
        r = score_team(s, 't1'); self.assertEqual(r['risk'], -30); self.assertEqual(r['budget'], 30)
        self.assertEqual(r['total'], 0); self.assertEqual(r['all_missed'], 0)

    def test_arena_no_purchase_penalty(self):
        s = started(); finish_incidents(s)
        r = score_team(s, 't1'); self.assertEqual(r['total'], -20)
        self.assertEqual((r['budget'], r['all_missed']), (15, -5))

    def test_partial_avoids_all_missed_penalty(self):
        s = started(); set_deck(s, ['R1', 'R2', 'R3']); buy(s, 'M1'); finish_incidents(s)
        self.assertEqual(score_team(s, 't1')['all_missed'], 0)

    def test_clean_sweep(self):
        s = started(); set_deck(s, ['R1', 'R2', 'R3']); buy(s, 'M4'); buy(s, 'M1'); buy(s, 'M7'); finish_incidents(s)
        r = score_team(s, 't1'); self.assertEqual((r['risk'], r['sweep'], r['budget'], r['total']), (30, 5, 15, 50))

    def test_cash_uses_complete_thousand_blocks(self):
        s = started(); buy(s, 'M1', price=8501); finish_incidents(s)
        self.assertEqual(score_team(s, 't1')['budget'], 5)

    def test_provisional_score_does_not_award_cash_or_sweep(self):
        s = started(); set_deck(s, ['R1', 'R2', 'R3']); buy(s, 'M4'); apply_action(s, 'close_auction', {}); apply_action(s, 'reveal', {})
        r = score_team(s, 't1'); self.assertEqual((r['risk'], r['budget'], r['sweep'], r['total']), (10, 0, 0, 10))

    def test_pitch_requires_debrief_and_reason(self):
        s = started()
        with self.assertRaises(RuleError): apply_action(s, 'bonus', {'team_id': 't1', 'enabled': True, 'reason': 'Defensible trade-off'})
        finish_incidents(s)
        with self.assertRaises(RuleError): apply_action(s, 'bonus', {'team_id': 't1', 'enabled': True, 'reason': 'yes'})
        apply_action(s, 'bonus', {'team_id': 't1', 'enabled': True, 'reason': 'Accepted one risk with a clear fallback.'})
        self.assertEqual(score_team(s, 't1')['creative'], 5)
        apply_action(s, 'bonus', {'team_id': 't1', 'enabled': False})
        self.assertEqual(score_team(s, 't1')['creative'], 0)

    def test_bank_counts_once_and_locks_bonus(self):
        s = started(); finish_incidents(s); value = score_team(s, 't1')['total']; apply_action(s, 'bank', {})
        self.assertEqual(public_state(s)['leaderboard'][0]['total'], value)
        with self.assertRaises(RuleError): apply_action(s, 'bank', {})
        with self.assertRaises(RuleError): apply_action(s, 'bonus', {'team_id': 't1', 'enabled': False})
        validate_state(s)

    def test_next_round_refreshes_wallet_and_retains_scores(self):
        s = fresh_state(); apply_action(s, 'start', {}); buy(s, 'M1'); finish_incidents(s); apply_action(s, 'bank', {})
        saved = score_team(s, 't1')['total']; apply_action(s, 'next', {})
        self.assertEqual((s['phase'], s['round_index'], balance(s, 't1')), ('brief', 1, 10000))
        self.assertEqual(next(r for r in public_state(s)['leaderboard'] if r['team_id'] == 't1')['total'], saved)
        validate_state(s)

    def test_equal_scores_share_first_place(self):
        s = started(); finish_incidents(s); apply_action(s, 'bank', {}); apply_action(s, 'next', {})
        snap = public_state(s); self.assertEqual(s['phase'], 'finished')
        self.assertEqual(len(snap['overall_winners']), 5)
        self.assertTrue(all(r['rank'] == 1 for r in snap['leaderboard']))

    def test_full_four_round_tournament(self):
        s = fresh_state(); apply_action(s, 'start', {})
        for i in range(4):
            buy(s, 'M1'); finish_incidents(s); apply_action(s, 'bank', {}); validate_state(s); apply_action(s, 'next', {})
        self.assertEqual((s['phase'], len(s['archive'])), ('finished', 4)); validate_state(s)

    def test_setup_locks_after_start(self):
        s = started()
        with self.assertRaises(RuleError): apply_action(s, 'setup', {})

    def test_setup_rejects_duplicate_team_names(self):
        s = fresh_state()
        with self.assertRaises(RuleError): apply_action(s, 'setup', {'teams': [{'name': 'Same'}, {'name': 'same'}], 'profile': 'arena', 'copies': 2, 'incident_count': 3})

    def test_timer_has_no_automatic_game_transition(self):
        s = started(); apply_action(s, 'timer', {'operation': 'set', 'seconds': 1}); apply_action(s, 'timer', {'operation': 'start'})
        s['timer']['deadline'] = 0; apply_action(s, 'timer', {'operation': 'pause'})
        self.assertEqual((s['timer']['seconds'], s['phase']), (0, 'brief'))

    def test_tampered_seal_backup_rejected(self):
        s = started(); s['round']['_deck'].reverse()
        with self.assertRaises(RuleError): validate_state(s)

    def test_tampered_archived_total_rejected(self):
        s = started(); finish_incidents(s); apply_action(s, 'bank', {})
        s['archive'][0]['rows'][0]['total'] += 100
        with self.assertRaises(RuleError): validate_state(s)

    def test_reset_requires_explicit_phrase(self):
        s = started()
        with self.assertRaises(RuleError): apply_action(s, 'reset', {'confirmation': 'yes'})
        apply_action(s, 'reset', {'confirmation': 'NEW GAME'}); validate_state(s)
        self.assertEqual(s['phase'], 'lobby')


class Persistence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / 'game.sqlite3'; self.store = Store(self.path)
    def tearDown(self): self.temp.cleanup()
    def command(self, name, data=None, request_id=None):
        return self.store.mutate(name, data or {}, self.store.get()['version'], request_id or uuid.uuid4().hex)

    def test_saved_state_survives_restart(self):
        s = self.command('start')
        self.assertEqual(Store(self.path).get(), s)

    def test_stale_revision_rejected(self):
        self.command('start')
        with self.assertRaises(RuleError) as exc: self.store.mutate('open_auction', {}, 0, uuid.uuid4().hex)
        self.assertEqual(exc.exception.status, 409)

    def test_duplicate_http_request_id_is_idempotent(self):
        req = uuid.uuid4().hex
        first = self.command('start', request_id=req)
        second = self.store.mutate('start', {}, 0, req)
        self.assertEqual(first, second)

    def test_failed_action_rolls_back(self):
        self.command('start'); before = self.store.get()
        with self.assertRaises(RuleError): self.command('sell', {'mid': 'M1'})
        self.assertEqual(before, self.store.get())

    def test_competing_actions_only_one_accepts_same_version(self):
        self.command('start'); version = self.store.get()['version']
        def change(i):
            try: self.store.mutate('announce', {'message': str(i)}, version, uuid.uuid4().hex); return True
            except RuleError: return False
        with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(change, range(8)))
        self.assertEqual(sum(results), 1)

    def test_restore_native_backup(self):
        self.command('start'); saved = self.store.get(); self.command('open_auction')
        result = self.command('restore', {'confirmation': 'RESTORE', 'backup': {'format': 'launchsafe-live-v1', 'state': saved}})
        self.assertEqual(result['phase'], 'brief'); self.assertGreater(result['version'], saved['version'])
        self.assertFalse(result['timer']['running'])

    def test_old_single_page_backup_is_not_silently_imported(self):
        with self.assertRaises(RuleError): self.command('restore', {'confirmation': 'RESTORE', 'backup': {'teams': []}})


class HTTPAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.store = Store(Path(cls.temp.name) / 'http.sqlite3')
        cls.secret = 'secret-' + uuid.uuid4().hex
        cls.server = GameServer(('127.0.0.1', 0), cls.store, cls.secret, 'http://192.168.1.20:8000')
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()
    def request(self, path, data=None, auth=False, content_type='application/json'):
        headers = {'Content-Type': content_type}
        if auth: headers['Authorization'] = 'Bearer ' + self.secret
        request = Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            with urlopen(request, timeout=5) as r: return r.status, r.read(), r.headers
        except HTTPError as ex:
            result = ex.code, ex.read(), ex.headers
            ex.close()
            return result

    def test_public_pages_load(self):
        for path in ['/', '/join', '/team/t1', '/screen', '/host']:
            status, body, _ = self.request(path); self.assertEqual(status, 200); self.assertIn(b'LaunchSafe Live', body)

    def test_team_cannot_mutate(self):
        status, _, _ = self.request('/api/action', {'action': 'start', 'version': 0, 'request_id': uuid.uuid4().hex})
        self.assertEqual(status, 401)

    def test_team_cannot_read_host_state_backup_or_csv(self):
        for path in ['/api/host', '/api/export', '/api/scores.csv']:
            self.assertEqual(self.request(path)[0], 401)

    def test_only_allowlisted_files_are_served(self):
        for path in ['/scenarios.json', '/engine.py', '/server.py', '/data/host.key', '/data/launchsafe.sqlite3', '/static/../engine.py', '/vendor/qrcode/__init__.py']:
            self.assertEqual(self.request(path)[0], 404, path)

    def test_qr_is_local_svg_and_points_to_lan_address(self):
        status, body, headers = self.request('/qr.svg?team=t1')
        self.assertEqual(status, 200); self.assertIn(b'<svg', body); self.assertIn('image/svg', headers['Content-Type'])
        self.assertEqual(self.request('/qr.svg?team=bad')[0], 400)

    def test_host_authentication_and_csp(self):
        status, body, headers = self.request('/api/host', auth=True)
        self.assertEqual(status, 200); self.assertIn('answer_key', json.loads(body))
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_bad_request_cannot_crash_server(self):
        status, _, _ = self.request('/api/action', [], auth=True); self.assertEqual(status, 400)
        self.assertEqual(self.request('/health')[0], 200)

    def test_non_json_post_rejected(self):
        status, _, _ = self.request('/api/action', {'action': 'start'}, auth=True, content_type='text/plain')
        self.assertEqual(status, 415)

    def test_presence_and_unchanged_poll(self):
        version = self.store.get()['version']; viewer = uuid.uuid4().hex
        status, body, _ = self.request(f'/api/state?since={version}&viewer={viewer}&team=t1')
        result = json.loads(body); self.assertEqual(status, 200); self.assertTrue(result['unchanged'])
        self.assertGreaterEqual(result['presence']['t1'], 1)

    def test_twenty_three_simultaneous_viewer_polls(self):
        def fetch(i):
            return self.request('/api/state?viewer=' + uuid.uuid4().hex + '&team=t' + str(i % 5 + 1))[0]
        with ThreadPoolExecutor(max_workers=23) as pool:
            statuses = list(pool.map(fetch, range(23)))
        self.assertEqual(statuses, [200] * 23)

    def test_export_has_no_auth_secret(self):
        status, body, _ = self.request('/api/export', auth=True)
        self.assertEqual(status, 200); self.assertNotIn(self.secret.encode(), body)
        self.assertEqual(json.loads(body)['format'], 'launchsafe-live-v1')


if __name__ == '__main__': unittest.main()
