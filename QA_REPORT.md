# LaunchSafe Live: verification report

## Runtime and rule/API tests

**59 automated tests passed** with Python 3.13 in the build environment.
Run them again locally with:

```bash
python3 -m unittest discover -s tests -v
```

The tests exercise the four original catalogues; high/partial mapping validity;
three- and four-incident draws; public/private response separation; commitment
verification; bid-versus-sale behavior; reserve prices; negative, fractional,
string and boolean price rejection; budgets; three-purchase limit; duplicate
items; copy limits; refunds; auction locks; reveal ordering; provisional scoring;
both scoring profiles; full-thousand savings; clean sweep and all-missed logic;
reasoned bonuses; banking exactly once; fresh-round wallets; shared winners;
a complete four-round tournament; locked setup; timers; corrupt backup rejection;
reset confirmation; SQLite restart persistence; stale revision rejection;
request-id deduplication; atomic rollback; simultaneous mutations; and restore.

A real local HTTP server was exercised through HTTP requests. Tests confirmed
public page access, rejection of unauthenticated mutations/private reads,
allowlisted static serving, local SVG QR generation, invalid-request handling,
JSON-only writes, presence polling, secret-free exports, and **23 simultaneous
viewer requests**, all returning successfully.

The runtime and local SVG QR generation were also imported and run with Python's
`-S` option, excluding installed site-packages. This checks that the packaged
server does not rely on an unshipped Flask, Pillow or other pip dependency.

## Browser interface and layout checks

Chromium rendered and exercised the actual interface code at desktop and mobile
sizes. Interaction checks included setup/start, public-view updates, published
bids, hammer calls, exact wallet changes, second-copy sales, refund controls,
three-purchase portfolio, three incident reveals, timed pitch spotlight, a
justified bonus, banking, all four rounds, final results, the QR-code sheet,
private answer-key tab and backup views. No JavaScript page errors were observed
across the instructor, projector and mobile roles in these checks.

All four mobile tabs were checked at **320, 360, 390, 430 and 768 CSS pixels**.
The checked layouts had no horizontal page overflow. Wide score-history tables
scroll within their own container. The projector auction layout was visually
reviewed and tightened to keep the main auction and five-team totals together.

A simulated loss of connection displayed a stale-state/reconnecting banner and
recovered through the normal polling logic.

**Important scope distinction:** this environment's browser policy blocks URL
navigation, so browser interaction tests used a local in-memory transport bridge
to the real game engine. The real HTTP server and access controls were tested
separately, as described above. This was not a physical-phone or full browser-to-
HTTP-network end-to-end test. No browser security policy was disabled.

Screenshots show test sessions and example network addresses; their QR codes are
not the QR for your classroom. Start your server to generate the correct code.

## Not verified in this environment

Physical iPhones/Android phones, Safari, Windows or macOS runtime behavior,
classroom Wi-Fi/firewall/VPN rules, guest-network client isolation, real QR camera
scanning, the user's projector resolution, real device sleep/wake behavior,
and audible playback on the user's hardware were not tested here.

The implementation uses standard-library Python and a bundled pure-Python QR
library, and the pages use responsive browser interfaces. That is not a substitute
for checking the actual room.

## Required pre-class smoke test

Start the server. Open the private host and separate projector. Scan the runtime
QR with a real phone on the classroom network. Select a team. Publish an
announcement and a test bid; verify both appear. Record a sample sale; verify
cash changes. Refresh the phone; verify the same state returns. Export a backup,
then start a clean game for the learners.

Check that typing the team join address directly also works. When that fails,
fix the network before troubleshooting the QR code itself.

## Operational boundary

This is for a trusted classroom LAN. It uses HTTP and a private bearer token,
not encrypted public-service authentication. The Python HTTP server is not being
represented as a hardened Internet-facing deployment. Never expose the host
secret, database, backups or service to an untrusted public network.
