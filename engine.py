"""Authoritative LaunchSafe rules. No browser is trusted to change this state."""
from __future__ import annotations
import copy
from contextlib import contextmanager
import hashlib
import json
import math
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCENARIOS = json.loads((ROOT / 'scenarios.json').read_text(encoding='utf-8'))
SCENARIO_BY_ID = {s['id']: s for s in SCENARIOS}
PROFILES = {
    'arena': {'name': 'Arena', 'high': 10, 'partial': 5, 'none': -10, 'sweep': 5,
              'creative': 5, 'per_1000': 5, 'budget_cap': 15, 'all_missed': -5},
    'original': {'name': 'Original', 'high': 10, 'partial': 5, 'none': -10, 'sweep': 5,
                 'creative': 5, 'per_1000': 5, 'budget_cap': 30, 'all_missed': 0},
}
BUDGET = 10000
MAX_BUYS = 3
PHASES = ('lobby', 'brief', 'auction', 'simulation', 'debrief', 'round_end', 'finished')
ROLES = [
    {'name': 'Risk detective', 'job': 'Which failures would hurt most? Challenge the assumptions.'},
    {'name': 'Finance lead', 'job': 'Set a walk-away price. Keep your team inside its budget.'},
    {'name': 'Auction voice', 'job': 'Raise your hand and call the team\'s bids out loud.'},
    {'name': 'Board spokesperson', 'job': 'Explain the trade-off, not just the purchase.'},
    {'name': 'Devil\'s advocate', 'job': 'Ask what this mitigation will NOT protect.'},
]
CHALLENGES = [
    'Which risk did you consciously accept, and why was that the better trade-off?',
    'What evidence would you demand before trusting your most expensive mitigation?',
    'Which single assumption could make your strategy fail? Explain your fallback.',
    'What would you change with the same budget, and what would you deliberately leave exposed?',
]
# Added fictional incident narration, not extra rules or factual business claims.
HEADLINES = {
  1: ['Legal puts the launch on hold', 'Payment failures hit the demo', 'The team reaches breaking point', 'An untested feature breaks the happy path', 'A last-minute redesign lands'],
  2: ['A fairness complaint goes public', 'Regional-language candidates get inconsistent results', 'The gender audit finds a gap', 'Internal audit cannot help', 'Investors expect a live demo anyway'],
  3: ['Customer records fail to reconcile', 'Key engineers are reassigned', 'One more dashboard, please', 'The board sees duplicate numbers', 'Customers cannot access the CRM', 'The live demo is brought forward'],
  4: ['Checkout buckles under demand', 'The vulnerable payment library is flagged', 'Orders stop reaching the warehouse', 'Support queues spiral', 'The store sells stock it does not have', 'Marketing says the date is fixed'],
}

class RuleError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def require(condition: Any, message: str, status: int = 400) -> None:
    if not condition:
        raise RuleError(message, status)


def integer(value: Any, low: int, high: int, label: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f'{label} must be a whole number.')
    require(low <= value <= high, f'{label} must be between {low} and {high}.')
    return value


def text(value: Any, maximum: int, label: str, minimum: int = 0) -> str:
    require(isinstance(value, str), f'{label} must be text.')
    value = value.strip()
    require(minimum <= len(value) <= maximum, f'{label} needs {minimum}-{maximum} characters.')
    require(not any(ord(c) < 32 and c not in '\n\t' for c in value), f'{label} contains invalid characters.')
    return value


def fresh_state() -> dict:
    return {
        'schema': 1, 'version': 0, 'game_id': uuid.uuid4().hex, 'phase': 'lobby',
        'title': 'LaunchSafe Live', 'profile': 'arena', 'copies': 2, 'incident_count': 3,
        'scenario_order': [1, 2, 3, 4], 'round_index': 0,
        'teams': [{'id': f't{i}', 'name': f'Team {i}', 'members': ''} for i in range(1, 6)],
        'round': None, 'archive': [], 'timer': {'running': False, 'seconds': 180, 'deadline': None},
        'announcement': '', 'pitch_team': None, 'audit': [],
    }


def scenario(state: dict) -> dict:
    return SCENARIO_BY_ID[state['scenario_order'][state['round_index']]]


def current_team(state: dict, team_id: str) -> dict:
    require(any(t['id'] == team_id for t in state['teams']), 'Unknown team.')
    return next(t for t in state['teams'] if t['id'] == team_id)


def buys_for(state: dict, team_id: str) -> list:
    return [b for b in state['round']['purchases'] if b['team_id'] == team_id] if state['round'] else []


def balance(state: dict, team_id: str) -> int:
    return BUDGET - sum(b['price'] for b in buys_for(state, team_id))


def log(state: dict, message: str, kind: str = 'info') -> None:
    state['audit'].append({'id': uuid.uuid4().hex, 'time': time.time(), 'message': message, 'kind': kind})
    state['audit'] = state['audit'][-160:]


def stop_timer(state: dict) -> None:
    tm = state['timer']
    if tm['running']:
        tm['seconds'] = max(0, math.ceil(tm['deadline'] - time.time()))
    tm['running'] = False
    tm['deadline'] = None


def seal_round(state: dict) -> None:
    sc = scenario(state)
    deck = secrets.SystemRandom().sample([r['id'] for r in sc['risks']], state['incident_count'])
    salt = secrets.token_hex(24)
    rid = uuid.uuid4().hex
    payload = f'{rid}|{salt}|{",".join(deck)}'
    state['round'] = {
        'id': rid, 'scenario_id': sc['id'], 'purchases': [], 'revealed': [],
        'bonuses': {}, 'focus': None, 'bid': None, 'call': 'open',
        'passed': [], '_deck': deck, '_salt': salt,
        'commitment': hashlib.sha256(payload.encode()).hexdigest(),
    }
    state['phase'] = 'brief'
    state['pitch_team'] = None
    state['announcement'] = ''
    state['timer'] = {'running': False, 'seconds': 180, 'deadline': None}
    log(state, f'Round {state["round_index"] + 1}: {sc["name"]}. Incidents sealed before bidding.', 'round')


def score_team(state: dict, team_id: str) -> dict:
    profile = PROFILES[state['profile']]
    r = state['round']
    bought = buys_for(state, team_id)
    owned = {b['mid'] for b in bought}
    revealed = r['revealed'] if r else []
    sc = scenario(state)
    risk_map = {x['id']: x['d'] for x in sc['risks']}
    lines = []
    for risk_id in revealed:
        mapping = sc['map'][risk_id]
        kind = 'high' if mapping['high'] in owned else 'partial' if mapping['partial'] in owned else 'none'
        lines.append({'rid': risk_id, 'description': risk_map[risk_id], 'kind': kind,
                      'mid': mapping.get(kind), 'points': profile[kind]})
    completed = len(revealed) == state['incident_count']
    remaining = balance(state, team_id)
    budget = min((remaining // 1000) * profile['per_1000'], profile['budget_cap']) if completed else 0
    sweep = profile['sweep'] if completed and all(l['kind'] == 'high' for l in lines) else 0
    all_missed = profile['all_missed'] if completed and all(l['kind'] == 'none' for l in lines) else 0
    reason = r['bonuses'].get(team_id, '') if r else ''
    creative = profile['creative'] if completed and reason else 0
    risk_points = sum(l['points'] for l in lines)
    return {'team_id': team_id, 'lines': lines, 'risk': risk_points, 'budget': budget,
            'sweep': sweep, 'all_missed': all_missed, 'creative': creative, 'reason': reason,
            'remaining': remaining, 'spent': BUDGET - remaining, 'complete': completed,
            'total': risk_points + budget + sweep + all_missed + creative}


def rankings(rows: list, key: str) -> list:
    rows = sorted(rows, key=lambda x: (-x[key], x['team_id']))
    last = None
    rank = 0
    for i, row in enumerate(rows, 1):
        if row[key] != last:
            rank = i
        row['rank'] = rank
        last = row[key]
    return rows


def public_state(state: dict, admin: bool = False) -> dict:
    """Whitelist fields. Never send hidden incident decks or future answer keys to viewers."""
    phase = state['phase']
    sc = scenario(state)
    r = state['round']
    finished_round = phase in ('debrief', 'round_end', 'finished')
    public_sc = {'id': sc['id'], 'name': sc['name'], 'context': sc['context'], 'list': sc['list'],
                 'risks': sc['risks'], 'mits': []}
    if phase != 'lobby':
        public_sc['mits'] = [{'id': m['id'], 'd': m['d'].removesuffix(' (partial)'), 'p': m['p']} for m in sc['mits']]
    out = {k: copy.deepcopy(state[k]) for k in ['schema', 'version', 'game_id', 'phase', 'title', 'profile',
           'copies', 'incident_count', 'scenario_order', 'round_index', 'teams', 'timer',
           'announcement', 'pitch_team', 'archive']}
    out['server_now'] = time.time()
    out['rules'] = {**PROFILES[state['profile']], 'budget': BUDGET, 'max_buys': MAX_BUYS}
    out['scenario'] = public_sc
    out['scenarios'] = [{'id': s['id'], 'name': s['name'], 'risk_count': len(s['risks']), 'lot_count': len(s['mits'])} for s in SCENARIOS]
    out['roles'] = ROLES
    out['challenge'] = CHALLENGES[state['round_index'] % len(CHALLENGES)]
    out['audit'] = copy.deepcopy(state['audit'][-30:])
    out['round'] = None
    if r:
        out['round'] = {k: copy.deepcopy(r[k]) for k in ['id', 'scenario_id', 'purchases', 'revealed', 'bonuses',
                         'focus', 'bid', 'call', 'passed', 'commitment']}
        out['round']['incidents'] = [{'rid': risk_id, 'headline': HEADLINES[sc['id']][int(risk_id[1:]) - 1],
          'description': next(x['d'] for x in sc['risks'] if x['id'] == risk_id),
          'answer': copy.deepcopy(sc['map'][risk_id])} for risk_id in r['revealed']]
        if finished_round:
            out['round']['proof'] = {'round_id': r['id'], 'salt': r['_salt'], 'deck': r['_deck'],
                 'format': 'SHA-256(round_id + "|" + salt + "|" + deck.join(","))',
                 'verified': hashlib.sha256(f'{r["id"]}|{r["_salt"]}|{",".join(r["_deck"])}'.encode()).hexdigest() == r['commitment']}
    round_scores = [score_team(state, t['id']) for t in state['teams']]
    out['round_scores'] = rankings(round_scores, 'total')
    archived_current = bool(r and any(a['round_id'] == r['id'] for a in state['archive']))
    overall = []
    for team in state['teams']:
        banked = sum(next((x['total'] for x in a['rows'] if x['team_id'] == team['id']), 0) for a in state['archive'])
        live = next(x['total'] for x in round_scores if x['team_id'] == team['id']) if r and not archived_current else 0
        overall.append({'team_id': team['id'], 'banked': banked, 'live': live, 'total': banked + live})
    out['leaderboard'] = rankings(overall, 'total')
    out['round_winners'] = [x['team_id'] for x in out['round_scores'] if x['rank'] == 1] if finished_round else []
    out['overall_winners'] = [x['team_id'] for x in out['leaderboard'] if x['rank'] == 1] if state['archive'] else []
    if admin:
        out['answer_key'] = copy.deepcopy(sc['map'])
        out['profiles'] = PROFILES
    return out


def apply_action(state: dict, action: str, data: dict) -> None:
    phase = state['phase']
    r = state['round']
    sc = scenario(state)
    if action == 'setup':
        require(phase == 'lobby', 'Setup is locked once a game starts. Start a new game to change it.')
        names = data.get('teams')
        require(isinstance(names, list) and 2 <= len(names) <= 12, 'Use 2 to 12 teams.')
        teams = []
        for i, t in enumerate(names, 1):
            require(isinstance(t, dict), 'Invalid team details.')
            teams.append({'id': f't{i}', 'name': text(t.get('name'), 32, 'Team name', 1),
                          'members': text(t.get('members', ''), 180, 'Member names')})
        require(len({t['name'].casefold() for t in teams}) == len(teams), 'Use a different name for each team.')
        profile = data.get('profile')
        require(profile in PROFILES, 'Unknown scoring profile.')
        order = data.get('scenario_order', [1, 2, 3, 4])
        require(isinstance(order, list) and 1 <= len(order) <= 4 and
                all(type(x) is int and x in SCENARIO_BY_ID for x in order) and len(set(order)) == len(order), 'Choose 1 to 4 distinct scenarios.')
        state.update(teams=teams, profile=profile, copies=integer(data.get('copies'), 1, 2, 'Copies'),
                     incident_count=integer(data.get('incident_count'), 3, 4, 'Incidents'),
                     scenario_order=order, title=text(data.get('title', 'LaunchSafe Live'), 64, 'Session title', 1))
        log(state, 'Room settings saved. All teams follow the same published rules.')
    elif action == 'start':
        require(phase == 'lobby', 'The game has already started.')
        seal_round(state)
    elif action == 'open_auction':
        require(phase == 'brief', 'The auction opens after the briefing.')
        state['phase'] = 'auction'
        stop_timer(state)
        log(state, 'Auction open. All bids are called aloud; only the instructor records them.', 'auction')
    elif action == 'focus':
        require(phase == 'auction', 'Lot selection is available only while the auction is open.')
        mid = data.get('mid')
        require(any(m['id'] == mid for m in sc['mits']), 'Unknown mitigation.')
        require(sum(b['mid'] == mid for b in r['purchases']) < state['copies'], 'All copies of this lot are sold.')
        r.update(focus=mid, bid=None, call='open')
    elif action in ('bid', 'sell'):
        require(phase == 'auction', 'The auction is closed. Purchases are locked.')
        mid = data.get('mid')
        require(mid and mid == r['focus'], 'Select this lot before recording a bid or sale.')
        m = next((m for m in sc['mits'] if m['id'] == mid), None)
        require(m, 'Unknown mitigation.')
        tid = data.get('team_id')
        team = current_team(state, tid)
        price = integer(data.get('price'), m['p'], BUDGET, 'Price')
        require(len(buys_for(state, tid)) < MAX_BUYS, f'{team["name"]} already has {MAX_BUYS} mitigations.')
        require(not any(b['mid'] == mid for b in buys_for(state, tid)), 'A team cannot buy the same mitigation twice.')
        require(sum(b['mid'] == mid for b in r['purchases']) < state['copies'], 'No copies are left.')
        require(price <= balance(state, tid), f'{team["name"]} has only ${balance(state, tid):,} remaining.')
        if action == 'bid':
            r['bid'] = {'team_id': tid, 'price': price}
            r['call'] = 'open'
        else:
            r['purchases'].append({'id': uuid.uuid4().hex, 'team_id': tid, 'mid': mid, 'price': price})
            r['bid'] = {'team_id': tid, 'price': price}
            r['call'] = 'sold'
            if mid in r['passed']:
                r['passed'].remove(mid)
            log(state, f'SOLD: {mid} to {team["name"]} for ${price:,}.', 'sold')
    elif action == 'call':
        require(phase == 'auction' and r['focus'] and r['bid'] and r['call'] != 'sold', 'Publish a live bid before calling the hammer.')
        value = data.get('value')
        require(value in ('open', 'once', 'twice'), 'Unknown hammer call.')
        r['call'] = value
    elif action == 'pass':
        require(phase == 'auction' and r['focus'], 'Select a lot to pass.')
        if r['focus'] not in r['passed']:
            r['passed'].append(r['focus'])
        r['call'] = 'passed'
        r['bid'] = None
        log(state, f'{r["focus"]} passed for now. Unsold copies can be reopened before the auction closes.')
    elif action == 'refund':
        require(phase == 'auction', 'Corrections are allowed only before the auction closes.')
        purchase = next((b for b in r['purchases'] if b['id'] == data.get('purchase_id')), None)
        require(purchase, 'That purchase was not found.')
        r['purchases'].remove(purchase)
        r.update(bid=None, call='open')
        log(state, f'Correction: refunded {purchase["mid"]} (${purchase["price"]:,}) to {current_team(state, purchase["team_id"])["name"]}.', 'correction')
    elif action == 'close_auction':
        require(phase == 'auction', 'The auction is not open.')
        state['phase'] = 'simulation'
        r.update(focus=None, bid=None, call='open')
        stop_timer(state)
        log(state, 'Auction locked. No purchases or refunds can change the sealed incident outcomes.', 'lock')
    elif action == 'reveal':
        require(phase == 'simulation', 'Incidents can be revealed only after the auction is locked.')
        require(len(r['revealed']) < len(r['_deck']), 'All incidents are already revealed.')
        risk_id = r['_deck'][len(r['revealed'])]
        r['revealed'].append(risk_id)
        log(state, f'INCIDENT {len(r["revealed"])}: {risk_id} - {HEADLINES[sc["id"]][int(risk_id[1:]) - 1]}.', 'incident')
        if len(r['revealed']) == len(r['_deck']):
            state['phase'] = 'debrief'
            state['timer'] = {'running': False, 'seconds': 45, 'deadline': None}
    elif action == 'pitch':
        require(phase == 'debrief', 'Board pitches open after all incidents are revealed.')
        tid = data.get('team_id')
        current_team(state, tid)
        state['pitch_team'] = tid
        seconds = integer(data.get('seconds', 45), 10, 300, 'Pitch seconds')
        state['timer'] = {'running': True, 'seconds': seconds, 'deadline': time.time() + seconds}
    elif action == 'bonus':
        require(phase == 'debrief', 'Strategy bonuses can be changed only during the debrief.')
        tid = data.get('team_id')
        team = current_team(state, tid)
        enabled = data.get('enabled')
        require(type(enabled) is bool, 'Bonus choice must be true or false.')
        if enabled:
            r['bonuses'][tid] = text(data.get('reason'), 240, 'Bonus reason', 8)
        else:
            r['bonuses'].pop(tid, None)
        log(state, f'{team["name"]}: strategy bonus {"awarded" if enabled else "removed"}.', 'bonus')
    elif action == 'bank':
        require(phase == 'debrief', 'Finish the incidents and debrief before banking this round.')
        require(not any(a['round_id'] == r['id'] for a in state['archive']), 'This round is already banked.')
        rows = [score_team(state, t['id']) for t in state['teams']]
        state['archive'].append({'round_id': r['id'], 'scenario_id': sc['id'], 'name': sc['name'], 'rows': rows,
                                 'revealed': r['revealed'][:], 'commitment': r['commitment']})
        state['phase'] = 'round_end'
        state['pitch_team'] = None
        stop_timer(state)
        log(state, f'Round {state["round_index"] + 1} banked. Its score cannot be counted twice.', 'round')
    elif action == 'next':
        require(phase == 'round_end', 'Bank the current round before continuing.')
        if state['round_index'] + 1 >= len(state['scenario_order']):
            state['phase'] = 'finished'
            log(state, 'Tournament complete. Equal point totals share the winning position.', 'finish')
        else:
            state['round_index'] += 1
            seal_round(state)
    elif action == 'timer':
        require(phase not in ('lobby', 'finished'), 'Timers are available during an active game.')
        operation = data.get('operation')
        if operation == 'set':
            seconds = integer(data.get('seconds'), 0, 3600, 'Timer seconds')
            state['timer'] = {'running': False, 'seconds': seconds, 'deadline': None}
        elif operation == 'start':
            stop_timer(state)
            require(state['timer']['seconds'] > 0, 'Set a timer greater than zero.')
            state['timer'].update(running=True, deadline=time.time() + state['timer']['seconds'])
        elif operation == 'pause':
            stop_timer(state)
        else:
            raise RuleError('Unknown timer action.')
    elif action == 'announce':
        state['announcement'] = text(data.get('message', ''), 220, 'Announcement')
    elif action == 'reset':
        require(data.get('confirmation') == 'NEW GAME', 'Type NEW GAME to reset. Export a backup first.')
        version = state['version']
        state.clear()
        state.update(fresh_state())
        state['version'] = version
        log(state, 'New game created. Previous state is retained in the local recovery journal.')
    else:
        raise RuleError('Unknown action.')


def validate_state(s: dict) -> None:
    """Validate persisted/imported native backups. Reject corrupt totals and hidden-deck edits."""
    require(isinstance(s, dict) and s.get('schema') == 1, 'Use a LaunchSafe Live v1 backup, not the older single-page game file.')
    require(s.get('phase') in PHASES, 'Invalid game phase.')
    require(s.get('profile') in PROFILES, 'Invalid scoring profile.')
    integer(s.get('version'), 0, 10**12, 'Version')
    text(s.get('game_id'), 64, 'Game ID', 16)
    text(s.get('title'), 64, 'Session title', 1)
    order = s.get('scenario_order')
    require(isinstance(order, list) and 1 <= len(order) <= 4 and all(type(i) is int and i in SCENARIO_BY_ID for i in order) and len(set(order)) == len(order), 'Invalid scenario list.')
    integer(s.get('round_index'), 0, len(order) - 1, 'Round index')
    integer(s.get('copies'), 1, 2, 'Copies')
    integer(s.get('incident_count'), 3, 4, 'Incident count')
    teams = s.get('teams')
    require(isinstance(teams, list) and 2 <= len(teams) <= 12, 'Invalid teams.')
    require(all(isinstance(t, dict) for t in teams), 'Invalid team records.')
    tids = [t.get('id') for t in teams]
    require(tids == [f't{i}' for i in range(1, len(teams) + 1)], 'Invalid stable team IDs.')
    for t in teams:
        text(t.get('name'), 32, 'Team name', 1)
        text(t.get('members'), 180, 'Members')
    require(len({t['name'].casefold() for t in teams}) == len(teams), 'Duplicate team names.')
    require(s.get('pitch_team') is None or s['pitch_team'] in tids, 'Invalid pitch team.')
    text(s.get('announcement'), 220, 'Announcement')
    tm = s.get('timer')
    require(isinstance(tm, dict) and type(tm.get('running')) is bool, 'Invalid timer.')
    integer(tm.get('seconds'), 0, 3600, 'Timer')
    require(tm.get('deadline') is None or isinstance(tm['deadline'], (int, float)) and math.isfinite(tm['deadline']), 'Invalid timer deadline.')
    require(not tm['running'] or tm['deadline'] is not None, 'Running timer needs a deadline.')
    require(isinstance(s.get('audit'), list) and len(s['audit']) <= 160, 'Invalid audit log.')
    for entry in s['audit']:
        require(isinstance(entry, dict), 'Invalid log entry.')
        text(entry.get('message'), 1000, 'Log message')
        text(entry.get('id'), 64, 'Log ID', 1)
        text(entry.get('kind'), 30, 'Log kind', 1)
        require(isinstance(entry.get('time'), (float, int)) and math.isfinite(entry['time']), 'Invalid log timestamp.')
    r = s.get('round')
    if s['phase'] == 'lobby':
        require(r is None and s['round_index'] == 0 and s.get('archive') == [], 'Lobby must not contain previous rounds.')
    else:
        require(isinstance(r, dict) and r.get('scenario_id') == scenario(s)['id'], 'Round scenario does not match.')
        text(r.get('id'), 64, 'Round ID', 16)
        text(r.get('_salt'), 96, 'Seal salt', 16)
        risks = {x['id'] for x in scenario(s)['risks']}
        deck, revealed = r.get('_deck'), r.get('revealed')
        require(isinstance(deck, list) and len(deck) == s['incident_count'] and all(type(x) is str and x in risks for x in deck) and len(set(deck)) == len(deck), 'Invalid incident deck.')
        require(isinstance(revealed, list) and revealed == deck[:len(revealed)], 'Revealed incidents must follow the sealed order.')
        commitment = hashlib.sha256(f'{r["id"]}|{r["_salt"]}|{",".join(deck)}'.encode()).hexdigest()
        require(r.get('commitment') == commitment, 'Incident commitment does not match.')
        if s['phase'] in ('brief', 'auction'):
            require(not revealed, 'Incidents cannot be visible while bidding is open.')
        if s['phase'] == 'simulation':
            require(len(revealed) < len(deck), 'Completed simulation must be in debrief.')
        if s['phase'] in ('debrief', 'round_end', 'finished'):
            require(len(revealed) == len(deck), 'All incidents must be revealed first.')
        mitigations = {m['id']: m for m in scenario(s)['mits']}
        purchases = r.get('purchases')
        require(isinstance(purchases, list) and len(purchases) <= len(teams) * MAX_BUYS, 'Invalid purchase list.')
        purchase_ids = set()
        for p in purchases:
            require(isinstance(p, dict) and p.get('team_id') in tids and p.get('mid') in mitigations, 'Invalid purchase.')
            text(p.get('id'), 64, 'Purchase ID', 16)
            require(p['id'] not in purchase_ids, 'Duplicate purchase ID.')
            purchase_ids.add(p['id'])
            integer(p.get('price'), mitigations[p['mid']]['p'], BUDGET, 'Purchase price')
        for tid in tids:
            buys = buys_for(s, tid)
            require(len(buys) <= MAX_BUYS and len({p['mid'] for p in buys}) == len(buys), 'Duplicate item or too many purchases.')
            require(balance(s, tid) >= 0, 'A team is over budget.')
        for mid in mitigations:
            require(sum(p['mid'] == mid for p in purchases) <= s['copies'], 'Too many mitigation copies sold.')
        require(r.get('focus') is None or r['focus'] in mitigations, 'Invalid focused lot.')
        require(r.get('call') in ('open', 'once', 'twice', 'sold', 'passed'), 'Invalid auction call.')
        require(isinstance(r.get('passed'), list) and all(x in mitigations for x in r['passed']), 'Invalid passed lots.')
        bid = r.get('bid')
        if bid is not None:
            require(isinstance(bid, dict) and bid.get('team_id') in tids and r['focus'] in mitigations, 'Invalid live bid.')
            integer(bid.get('price'), mitigations[r['focus']]['p'], BUDGET, 'Bid price')
        bonuses = r.get('bonuses')
        require(isinstance(bonuses, dict) and all(t in tids for t in bonuses), 'Invalid bonus allocation.')
        for reason in bonuses.values():
            text(reason, 240, 'Bonus reason', 8)
        require(not bonuses or s['phase'] in ('debrief', 'round_end', 'finished'), 'Bonuses cannot precede the debrief.')
    archive = s.get('archive')
    require(isinstance(archive, list) and len(archive) <= len(order), 'Invalid archived rounds.')
    expected_length = 0 if s['phase'] == 'lobby' else s['round_index'] + (s['phase'] in ('round_end', 'finished'))
    require(len(archive) == expected_length, 'Archived rounds do not match game progress.')
    archive_ids = []
    for i, a in enumerate(archive):
        require(isinstance(a, dict) and a.get('scenario_id') == order[i], 'Invalid archived scenario.')
        text(a.get('round_id'), 64, 'Archived round ID', 16)
        archive_ids.append(a['round_id'])
        text(a.get('name'), 100, 'Archived scenario name', 1)
        text(a.get('commitment'), 64, 'Archived commitment', 64)
        require(isinstance(a.get('revealed'), list) and len(a['revealed']) == s['incident_count'], 'Invalid archived risks.')
        ar_sc = SCENARIO_BY_ID[a['scenario_id']]
        require(all(x in ar_sc['map'] for x in a['revealed']) and len(set(a['revealed'])) == len(a['revealed']), 'Invalid archived risk IDs.')
        rows = a.get('rows')
        require(isinstance(rows, list) and [x.get('team_id') for x in rows] == tids, 'Invalid archived scores.')
        p = PROFILES[s['profile']]
        for row in rows:
            require(type(row.get('complete')) is bool and row['complete'], 'Archived score is incomplete.')
            lines = row.get('lines')
            require(isinstance(lines, list) and [l.get('rid') for l in lines] == a['revealed'], 'Invalid risk scoring lines.')
            for line in lines:
                kind = line.get('kind')
                require(kind in ('high', 'partial', 'none') and line.get('points') == p[kind], 'Invalid risk points.')
                require(line.get('mid') == ar_sc['map'][line['rid']].get(kind), 'Invalid risk mapping.')
                text(line.get('description'), 300, 'Risk description', 1)
            remaining = integer(row.get('remaining'), 0, BUDGET, 'Archived balance')
            text(row.get('reason'), 240, 'Bonus reason')
            expected = {'risk': sum(l['points'] for l in lines), 'spent': BUDGET - remaining,
                'budget': min(remaining // 1000 * p['per_1000'], p['budget_cap']),
                'sweep': p['sweep'] if all(l['kind'] == 'high' for l in lines) else 0,
                'all_missed': p['all_missed'] if all(l['kind'] == 'none' for l in lines) else 0,
                'creative': p['creative'] if row['reason'] else 0}
            expected['total'] = sum(expected[k] for k in ('risk', 'budget', 'sweep', 'all_missed', 'creative'))
            require(all(row.get(k) == v for k, v in expected.items()), 'Archived score arithmetic is inconsistent.')
    require(len(set(archive_ids)) == len(archive_ids), 'Duplicate archived round.')
    if s['phase'] in ('round_end', 'finished'):
        require(archive[-1]['round_id'] == r['id'], 'Current round archive is inconsistent.')
        require(archive[-1]['rows'] == [score_team(s, t) for t in tids], 'Current archived scores do not match purchases.')
    if s['phase'] == 'finished':
        require(len(archive) == len(order), 'Tournament is not complete.')


class Store:
    """One serialized transaction per mutation; state, journal and request receipts persist."""
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS game (id INTEGER PRIMARY KEY, payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, action TEXT, payload TEXT); CREATE TABLE IF NOT EXISTS receipts (request_id TEXT PRIMARY KEY, version INTEGER);')
            if db.execute('SELECT 1 FROM game WHERE id=1').fetchone() is None:
                db.execute('INSERT INTO game VALUES (1,?)', (json.dumps(fresh_state()),))
        validate_state(self.get())

    @contextmanager
    def connect(self):
        # sqlite3's own context manager commits but does NOT close the connection.
        # Close explicitly so continuous polling never accumulates file handles.
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self) -> dict:
        with self.lock, self.connect() as db:
            return json.loads(db.execute('SELECT payload FROM game WHERE id=1').fetchone()[0])

    def mutate(self, action: str, data: dict, version: int, request_id: str) -> dict:
        text(request_id, 80, 'Request ID', 12)
        integer(version, 0, 10**12, 'Version')
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = json.loads(db.execute('SELECT payload FROM game WHERE id=1').fetchone()[0])
            if db.execute('SELECT 1 FROM receipts WHERE request_id=?', (request_id,)).fetchone():
                return state
            require(version == state['version'], 'Another control changed the game. The dashboard has refreshed; review and try again.', 409)
            before = json.dumps(state)
            if action == 'restore':
                require(data.get('confirmation') == 'RESTORE', 'Type RESTORE to load a native backup.')
                backup = data.get('backup')
                require(isinstance(backup, dict) and backup.get('format') == 'launchsafe-live-v1', 'Not a LaunchSafe Live backup.')
                new_state = copy.deepcopy(backup.get('state'))
                validate_state(new_state)
                new_state['version'] = state['version']
                state = new_state
                stop_timer(state)
                log(state, 'Native backup restored by the instructor; timers paused.', 'correction')
            else:
                apply_action(state, action, data)
            state['version'] += 1
            validate_state(state)
            db.execute('INSERT INTO journal(created,action,payload) VALUES (?,?,?)', (time.time(), action, before))
            db.execute('DELETE FROM journal WHERE id NOT IN (SELECT id FROM journal ORDER BY id DESC LIMIT 200)')
            db.execute('UPDATE game SET payload=? WHERE id=1', (json.dumps(state),))
            db.execute('INSERT INTO receipts VALUES (?,?)', (request_id, state['version']))
            db.execute('DELETE FROM receipts WHERE rowid NOT IN (SELECT rowid FROM receipts ORDER BY rowid DESC LIMIT 1000)')
            return state
