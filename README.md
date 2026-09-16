# LaunchSafe Live
## The instructor-controlled risk negotiation game

**One Python server. A private instructor dashboard. A separate projector screen.
Read-only team viewers with QR-code joining.**

Built from the uploaded `launchsafe (2).html`. The four scenario descriptions,
risks, auction catalogues, opening prices, and high/partial mitigation mappings
are retained. Read `CHANGES.md` for the explicit gameplay changes.

## Start in under a minute

Requires **Python 3.10 or newer**. No pip installation, Node.js, account, CDN,
cloud database, or Internet connection is required to run the downloaded game.
The small QR-code library is included with its BSD license.

1. Extract the ZIP. Keep the entire `LaunchSafe_Live` folder together.
2. Open a terminal in that folder.
3. On macOS or Linux, run:

```bash
python3 server.py
```

On Windows:

```bat
py -3 server.py
```

The terminal prints three addresses:

```text
PRIVATE HOST: http://localhost:8000/host#<your-random-secret>
PROJECTOR:    http://localhost:8000/screen
TEAM JOIN:    http://<your-computer-LAN-address>:8000/join
```

**Open the complete PRIVATE HOST link on your laptop. Keep it private.**
Open PROJECTOR in a separate window and put only that window on the projector.
Show the QR code from the projector or the instructor's Team QR codes tab.
Learners scan it, select their team, and see that team's live viewer.

Do not double-click `templates/index.html` or use a generic static-file server.
The game needs `server.py` to synchronize devices and enforce the rules.

Optional launchers are included: `start-mac.command` and `start-windows.bat`.
Using the terminal command is the most predictable approach.

## Classroom network checklist

The phones must be able to reach the laptop's address. A QR code only opens a
URL; it does not create a network connection or make an unreachable server public.

- Put the laptop and phones on the same reachable Wi-Fi or router/hotspot network.
- Keep the server terminal open and prevent the laptop from sleeping.
- Allow Python through the computer's firewall when prompted for local access.
- Open the TEAM JOIN address on one actual phone before the class starts.

Some guest, hotel, or corporate networks isolate devices. In that case, ask IT
for a classroom network that allows device-to-device connections, or use a router
or hotspot configuration that permits them. Do not assume every hotspot permits
clients to reach one another.

The displayed LAN address is detected automatically. With a VPN or multiple
network adapters, it may be the wrong address. Restart with the correct reachable
address to change every generated QR code:

```bash
python3 server.py --public-url http://192.168.1.25:8000
```

Replace the example IP with your laptop's actual LAN IP. For a different port:

```bash
python3 server.py --port 8001 --public-url http://192.168.1.25:8001
```

Changing the join address does not change the saved game. Phones must rescan the
new QR or open the new link. `localhost` and `127.0.0.1` on a phone refer to the
phone itself, not the instructor's laptop.

## What each screen does

### Instructor: `/host`

Name 2-12 teams, select scenarios, choose the scoring profile and scarcity, and
run the entire game. Default: five teams, two copies per lot, three incidents,
and all four scenarios.

The instructor alone can publish live bids, call the hammer, record SOLD,
refund a mistaken purchase before auction lock, open/close phases, reveal
incidents, run timers, spotlight team pitches, award reasoned bonuses, bank
rounds, start the next round, publish announcements, export, restore, and reset.

For 23 learners, three teams of five plus two teams of four is a balanced split.
Optional member names appear in the team viewer; omit surnames or personal
information you do not want visible to the room.

### Projector: `/screen`

A public, automatic view of the current phase. The auction shows the current
mitigation, price, leading/winning team and hammer call. Incident reveals show
team impacts. Results show round winners and progressive/final standings.

The local Full screen and Sound controls affect only that screen. Sound uses
short generated tones, not downloaded or copyrighted music. Audio must be
enabled by clicking Sound on. Browser restrictions may limit full screen or audio.

### Teams: `/join` and `/team/t1` etc.

Teams select a viewer, not an account. Any number of teammates can use the same
team link. The viewer has four mobile-friendly tabs:

- **Live room:** follows the instructor's phase, price, incident and pitch.
- **My protection:** the team's purchases, prices, slots and remaining cash.
- **Risk brief:** scenario, exposed risks, rules and rotating team roles.
- **Standings:** cumulative banked points plus the current live score.

Teams cannot bid, buy, submit prices, change scores, reveal incidents, or
advance phases. Tab navigation does not change shared state. Team views are
public, not private confidential accounts; people can switch teams.

## Run a round

### 1. Brief the mission

Each team receives a fresh $10,000 and may buy at most three different
mitigations. Give them 2-3 minutes to choose priority risks, assign roles, and
agree walk-away prices. Their catalogue is visible, but answer mappings are not.

The server secretly chooses three (or four) distinct incidents when the round
starts. It publishes a salted SHA-256 commitment before the auction. Nobody can
reroll or choose incidents through the game controls.

### 2. Auction protection aloud

Click a lot. Its description and opening price appear on the projector and
phones. Ask for bids. Select the leading team and enter the called price; click
**Publish live bid**. This changes the display but does not deduct cash.

Use Going once and Going twice for drama. Click **SOLD - record purchase**, check
the confirmation, and the winning team is charged. Each copy is auctioned
separately; the second copy need not sell at the first copy's price.

Prices may be any whole-dollar amount at or above the opening price. The +$100,
+$250 and +$500 buttons are shortcuts, not a mandatory bid increment. The
instructor may correct a displayed bid downward; only a completed sale spends
money. No duplicate item per team, over-budget sale, extra copy, or fourth
purchase is accepted by the server.

Use **Pass this lot** when nobody bids. Unsold copies can be reopened before the
auction closes. **Receipts & corrections** lets you refund a mistake and
re-auction that copy while the auction remains open.

### 3. Lock the market and reveal incidents

Close the auction only when satisfied with all receipts. This permanently locks
purchases and refunds for that round. There is no reopening after seeing risks.

Reveal one incident at a time. The order was fixed before bidding. Each reveal
shows a short fictional headline, the original risk description, and each team's
highly correlated / partially correlated / unmanaged result.

Pause between incidents. Ask a team whether the exposed risk was a conscious
trade-off. Scores are provisional; cash and round bonuses wait for all reveals.

### 4. Put teams before the board

After the final incident, every team gets a chance to explain its choices. Click
**Spotlight & start 45s** for that team. The prompt appears on every viewer.

Award +5 only for a defensible trade-off, an explicit limitation, and a credible
fallback. Enter a reason of at least eight characters; it appears in the team's
score breakdown. Confidence or volume alone is not a strategy. The instructor
can update or remove the bonus before banking.

### 5. Bank and celebrate

Bank the round once every team has had a fair chance to pitch. This freezes its
bonuses and adds its score exactly once. The podium declares the round winner;
the standings show the progressive tournament leader.

Next round: purchases reset, wallets return to $10,000, points remain, and team
roles rotate. After the last banked round, click **Crown the final champions**.
Equal point totals share their rank and winning position; there is no secret
tie-breaker.

## Scoring: published before play, locked after start

| Component | Original | Arena (default) |
|---|---:|---:|
| Highly correlated mitigation | +10 | +10 |
| Partially correlated mitigation | +5 | +5 |
| Unmanaged incident | -10 | -10 |
| Every incident highly covered | +5 | +5 |
| Each complete $1,000 remaining | +5 | +5 |
| Maximum cash bonus | +30 | +15 |
| Every incident unmanaged | 0 extra | -5 extra |
| Reasoned strategy pitch, approved by instructor | +5 | +5 |

Arena deliberately reduces the reward for holding cash while leaving risks
unmanaged. It does not guarantee that spending money is better than doing
nothing: an expensive, poorly chosen purchase can still be a bad decision.

Example: a team facing three unmanaged incidents with no purchases scores 0 in
Original (-30 + 30), or -20 in Arena (-30 + 15 - 5), before any pitch bonus.

Cash bonus uses **complete** $1,000 blocks, not a fractional formula: $2,999 earns
+10, before the cap. A risk scores once; high and partial coverage do not stack.
One mitigation can serve several risk mappings. Unused purchases have no separate
penalty. Partial coverage never qualifies for the all-high clean sweep.

Cash bonus, sweep and all-missed adjustment apply only when all incidents are
revealed. Pitch bonus follows in the debrief. Leaderboard totals avoid adding a
banked round a second time.

The source mappings are classroom conventions preserved from your file. They
are not universal assessments of real security, compliance or operational risk.

## Timers and pacing

The instructor can set 0-3,600 seconds, start/pause, or use 30s / 45s / 3m / 5m
presets. An expired timer is only a cue; it never bids, sells, reveals a risk, or
changes the phase. Countdown displays use the server's clock and deadline.

A suggested round is 3 minutes briefing, 6-8 minutes auction, 2 minutes incidents,
then about 4 minutes for five pitches. Adjust it to your class. Select fewer
scenarios for a shorter session rather than rushing every decision.

## Save, recover and reset

Every accepted action is stored in `data/launchsafe.sqlite3`. Restarting the same
folder resumes that game. Refreshing or reconnecting a phone does not reset it.
The browser polls about every 1.2 seconds and requests only a small unchanged
response when no game action has occurred.

**Native JSON backup:** use Save / restore to export an instructor checkpoint.
It includes still-hidden incidents, so never give it to learners. It does not
contain the authentication secret. Restore accepts only this edition's validated
`launchsafe-live-v1` JSON, not the older single-page game's export.

**Scores CSV:** exports one column per banked round, banked total, live unbanked
points, overall total and rank. A provisional export is labeled accordingly.

**Reset:** requires typing `NEW GAME`. Export a backup before resetting. A local
SQLite recovery journal retains the previous 200 states for technical recovery,
but there is no learner-facing rewind or general Undo button.

Restoring an exported checkpoint requires typing `RESTORE`, replaces the current
session and pauses its timer. The app remains a tool controlled by the instructor:
the hash commitment is an audit aid, not proof against someone who controls the
server computer or deliberately restores an old backup.

The private secret is stored separately in `data/host.key`. Keep it private.
To invalidate an exposed host secret, stop the server, delete only `host.key`,
then restart. The saved game remains; a new secret is printed.

## Security boundary

This is a **trusted classroom LAN app**, not a publicly hosted production service.
It uses ordinary HTTP; the bearer secret is not encrypted in transit. Do not
port-forward it, expose it to the public Internet, or assume an untrusted network
is safe. Public deployment would require HTTPS and a hardened deployment/auth
configuration beyond this classroom package.

Authoritative state and validation live on the server. Public JSON is an explicit
whitelist. Unrevealed mappings/decks are absent from viewer responses. Host reads,
exports and all state mutations require a random bearer secret. The server only
serves allowlisted static files, not the project directory, database or host key.

Sources for underlying runtime behavior:
- Python HTTP server documentation: https://docs.python.org/3/library/http.server.html
- QR library documentation: https://pypi.org/project/qrcode/

## Test the rules and routes

```bash
python3 -m unittest discover -s tests -v
```

The included tests require no extra packages. See `QA_REPORT.md` for what was
actually tested and what still needs checking on your local phones and Wi-Fi.

## Files

```text
LaunchSafe_Live/
  server.py                 Local HTTP server, authentication, QR, HTTP exports
  engine.py                 Rules, phases, scoring, validation, persistence
  scenarios.json            Original four scenario catalogues and mappings
  static/app.js             Instructor, projector and team interfaces
  static/style.css          Responsive styles
  templates/index.html      App shell (serve through server.py)
  vendor/qrcode/            Included pure-Python QR library
  vendor/QRCODE-LICENSE.txt  Required third-party license
  tests/test_game.py         Rule, persistence and real HTTP tests
  README.md                 This guide
  FACILITATOR_GUIDE.md       Quick run-of-show
  CHANGES.md                 Original vs new behavior
  QA_REPORT.md              Test scope and limitations
```

No pre-populated game database or private host key is shipped. Both are created
locally on first launch.
