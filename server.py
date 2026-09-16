#!/usr/bin/env python3
"""LaunchSafe LAN classroom server. Python 3.10+, no pip install needed.

This intentionally small HTTP server is for a trusted local classroom network,
not an Internet-facing production deployment. Host controls use a random bearer
secret. All static paths and public JSON fields are explicitly allowlisted.
"""
from __future__ import annotations
import argparse
import csv
import hmac
import io
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
import qrcode
from qrcode.image.svg import SvgPathImage
from engine import Store, RuleError, public_state, require

MAX_BODY = 1_000_000
STATIC = {
    '/static/app.js': ('static/app.js', 'text/javascript; charset=utf-8'),
    '/static/style.css': ('static/style.css', 'text/css; charset=utf-8'),
    '/static/icon.svg': ('static/icon.svg', 'image/svg+xml'),
}


def lan_ip() -> str:
    """Ask the OS which interface it would route through; no packet is sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1', 80))
            ip = sock.getsockname()[0]
            if not ip.startswith('127.'):
                return ip
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith('127.'):
                return ip
    except OSError:
        pass
    return '127.0.0.1'


class GameServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, store, token, public_url):
        self.store = store
        self.token = token
        self.public_url = public_url.rstrip('/')
        self.presence = {}
        self.presence_lock = threading.Lock()
        self.qr_cache = {}
        super().__init__(address, Handler)

    def viewers(self, params):
        now = time.time()
        with self.presence_lock:
            viewer = params.get('viewer', [''])[0]
            team = params.get('team', [''])[0]
            if re.fullmatch(r'[a-zA-Z0-9_-]{12,80}', viewer) and (re.fullmatch(r't\d{1,2}', team) or team == 'screen'):
                self.presence[viewer] = {'team': team, 'seen': now}
            self.presence = {k: v for k, v in self.presence.items() if now - v['seen'] < 20}
            counts = {}
            for v in self.presence.values():
                counts[v['team']] = counts.get(v['team'], 0) + 1
            return counts


class Handler(BaseHTTPRequestHandler):
    server_version = 'LaunchSafe/1.0'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(12)

    def log_message(self, format, *args):
        # Never log URL secrets or flood the terminal with polling requests.
        pass

    def send(self, body=b'', status=200, mime='application/json; charset=utf-8', headers=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('Connection', 'close')
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        self.close_connection = True

    def json(self, value, status=200, headers=None):
        self.send(json.dumps(value, ensure_ascii=True, allow_nan=False), status, headers=headers)

    def auth(self):
        header = self.headers.get('Authorization', '')
        require(hmac.compare_digest(header, 'Bearer ' + self.server.token), 'Instructor authorization required.', 401)

    def route(self):
        u = urlsplit(self.path)
        return u.path, parse_qs(u.query)

    def snapshot(self, state, admin=False):
        out = public_state(state, admin=admin)
        out['network'] = {'join': self.server.public_url + '/join', 'screen': self.server.public_url + '/screen',
                          'base': self.server.public_url}
        out['presence'] = self.server.viewers({})
        return out

    def do_GET(self):
        try:
            path, params = self.route()
            if path in ('/', '/join', '/host', '/screen') or re.fullmatch(r'/team/t\d{1,2}', path):
                self.send((ROOT / 'templates/index.html').read_bytes(), mime='text/html; charset=utf-8')
            elif path in STATIC:
                file, mime = STATIC[path]
                self.send((ROOT / file).read_bytes(), mime=mime)
            elif path in ('/api/state', '/api/host'):
                admin = path == '/api/host'
                if admin:
                    self.auth()
                counts = self.server.viewers(params)
                state = self.server.store.get()
                if params.get('since', [None])[0] == str(state['version']):
                    self.json({'unchanged': True, 'version': state['version'], 'server_now': time.time(), 'presence': counts})
                else:
                    self.json(self.snapshot(state, admin))
            elif path == '/qr.svg':
                team = params.get('team', [''])[0]
                if team:
                    require(team in [t['id'] for t in self.server.store.get()['teams']], 'Unknown team QR.')
                target = self.server.public_url + ('/team/' + team if team else '/join')
                if target not in self.server.qr_cache:
                    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
                    qr.add_data(target)
                    qr.make(fit=True)
                    self.server.qr_cache[target] = qr.make_image(image_factory=SvgPathImage).to_string()
                self.send(self.server.qr_cache[target], mime='image/svg+xml')
            elif path == '/api/export':
                self.auth()
                self.json({'format': 'launchsafe-live-v1', 'exported_at': time.time(), 'state': self.server.store.get()},
                          headers={'Content-Disposition': 'attachment; filename="launchsafe-backup.json"'})
            elif path == '/api/scores.csv':
                self.auth()
                state = self.server.store.get()
                view = public_state(state)
                buf = io.StringIO(newline='')
                writer = csv.writer(buf)
                writer.writerow(['Team', *[a['name'] for a in state['archive']], 'Banked total', 'Live unbanked', 'Overall', 'Rank'])
                for row in view['leaderboard']:
                    name = next(t['name'] for t in state['teams'] if t['id'] == row['team_id'])
                    # Avoid formula injection when a team name is opened in a spreadsheet.
                    safe_name = "'" + name if name.startswith(('=', '+', '-', '@', '\t', '\r')) else name
                    writer.writerow([safe_name, *[next(x['total'] for x in a['rows'] if x['team_id'] == row['team_id']) for a in state['archive']],
                                     row['banked'], row['live'], row['total'], row['rank']])
                self.send('\ufeff' + buf.getvalue(), mime='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="launchsafe-scores.csv"'})
            elif path == '/health':
                self.json({'ok': True, 'app': 'LaunchSafe Live'})
            elif path == '/favicon.ico':
                self.send(b'', status=204)
            else:
                self.json({'error': 'Not found.'}, 404)
        except RuleError as exc:
            self.json({'error': str(exc)}, exc.status)
        except (KeyError, TypeError, ValueError) as exc:
            self.json({'error': 'Invalid request.'}, 400)
        except Exception as exc:
            print(f'Server error: {type(exc).__name__}: {exc}', file=sys.stderr)
            self.json({'error': 'Server error. Check the instructor terminal; the saved state has not been discarded.'}, 500)

    def do_POST(self):
        try:
            path, _ = self.route()
            require(path == '/api/action', 'Not found.', 404)
            self.auth()
            require(self.headers.get('Content-Type', '').split(';')[0] == 'application/json', 'Use JSON.', 415)
            # No CORS or cookie authentication: a third-party page cannot use a host session.
            length = int(self.headers.get('Content-Length', '0'))
            require(0 < length <= MAX_BODY, 'Request is empty or exceeds 1 MB.', 413)
            raw = self.rfile.read(length)
            require(len(raw) == length, 'Incomplete request body.')
            data = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
            require(isinstance(data, dict), 'Expected a JSON object.')
            action = data.get('action')
            require(isinstance(action, str) and len(action) < 40, 'Invalid action.')
            payload = data.get('data', {})
            require(isinstance(payload, dict), 'Invalid action data.')
            state = self.server.store.mutate(action, payload, data.get('version'), data.get('request_id'))
            self.json(self.snapshot(state, admin=True))
        except RuleError as exc:
            self.json({'error': str(exc)}, exc.status)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError, IndexError) as exc:
            self.json({'error': 'Invalid request or backup structure.'}, 400)
        except Exception as exc:
            print(f'Server error: {type(exc).__name__}: {exc}', file=sys.stderr)
            self.json({'error': 'Action failed. Refresh to check state before trying again.'}, 500)

    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        self.json({'error': 'Cross-origin access is not enabled.'}, 405)

    def do_PUT(self):
        self.json({'error': 'Method not allowed.'}, 405)

    do_DELETE = do_PUT
    do_PATCH = do_PUT


def main():
    parser = argparse.ArgumentParser(description='LaunchSafe instructor-controlled LAN game')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8000')))
    parser.add_argument('--bind', default='0.0.0.0', help='Listen address; 0.0.0.0 allows phones on the local network')
    parser.add_argument('--public-url', help='Override the QR base, e.g. http://192.168.1.25:8000')
    parser.add_argument('--data-dir', default=str(ROOT / 'data'))
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port from 1024 to 65535.')
    data_dir = Path(args.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / 'host.key'
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(36), encoding='utf-8')
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
    token = key_file.read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{32,100}', token):
        raise SystemExit('Invalid data/host.key. Back up data, delete only host.key, then restart.')
    public_url = args.public_url or os.environ.get('RENDER_EXTERNAL_URL') or f'http://{lan_ip()}:{args.port}'
    u = urlsplit(public_url)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
        parser.error('--public-url must be a plain http(s) origin, without a path, credentials or query.')
    try:
        store = Store(data_dir / 'launchsafe.sqlite3')
        server = GameServer((args.bind, args.port), store, token, public_url)
    except OSError as exc:
        raise SystemExit(f'Cannot start server: {exc}. Try --port 8001.') from exc
    print('\n' + '=' * 70)
    print('  LAUNCHSAFE LIVE - INSTRUCTOR CONTROL ROOM')
    print('=' * 70)
    print(f'  PRIVATE HOST: http://localhost:{args.port}/host#{token}')
    print(f'  PROJECTOR:    http://localhost:{args.port}/screen')
    print(f'  TEAM JOIN:    {public_url}/join')
    print(f'  SAVED GAME:   {data_dir / "launchsafe.sqlite3"}')
    print('\n  Keep the private host link off the projector. Share the QR on /screen.')
    print('  Phones must be on a network that can reach this computer.')
    print('  No Internet is needed after downloading. Leave this terminal running.')
    print('  Trusted classroom LAN only; do not expose this HTTP server publicly.')
    print('  Ctrl+C stops the server. Your game is saved automatically.\n', flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print('\nStopped. Game saved. Run the same command to resume.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
