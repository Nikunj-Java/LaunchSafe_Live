# What changed from the uploaded game

## Preserved from `launchsafe (2).html`

The four scenarios retain their descriptions, risks, mitigation wording in the
source data, opening prices, and high/partial mappings:

| Scenario | Risks | Mitigation lots |
|---|---:|---:|
| Mobile payment app launch | 5 | 7 |
| GenAI resume screening pilot | 5 | 7 |
| CRM migration after a merger | 6 | 7 |
| Retail checkout before peak weekend | 6 | 8 |

Each new round still provides $10,000. Maximum purchases remain three different
mitigations per team. The default remains two copies of each mitigation, with a
one-copy setting available.

Original scoring retains +10 high, +5 partial, -10 unmanaged, +5 all-high sweep,
+5 strategy bonus, and +5 per complete $1,000 saved with a +30 cap. The original
HTML used a floor operation; this edition does not silently turn that into a
fractional savings formula.

## Explicit additions and rule changes

**Optional Arena scoring (default):** savings cap reduced from +30 to +15; an
extra -5 applies if every incident is unmanaged. All other scoring components
are unchanged. Original is selectable before play.

**Structured phases:** lobby, briefing, auction, incidents, board pitches, round
results, final champions. Once the auction closes, purchases and refunds lock.
A round cannot be banked before all incidents are revealed or counted twice.

**Sealed incident order:** three incidents by default, or four if configured,
chosen before the auction. No instructor reroll or selective post-auction risk
picking. The next incident is disclosed only on the instructor's Reveal action.
A salted commitment can be checked when the whole deck opens.

**Separate screen roles:** private instructor controls; read-only projector;
public, mobile team viewers. The server, not browser controls, authorizes actions
and computes scores. Future mappings and incidents are omitted from public JSON.

**Live auction display:** selecting a lot, publishing a price, calling the hammer
and recording a sale are distinct actions. Teams continue to bid aloud. Each
copy is auctioned independently. Prices must meet the original opening price;
zero-price or below-reserve purchases are rejected.

**Participation and drama:** rotating team roles, fictional incident headlines,
a timed board spotlight, one reasoned strategy bonus per team, optional generated
gavel/incident/winner tones, live wallets and provisional totals, round podiums,
progressive leaders and final champions. Tied points share the position.

**Public text spoiler removal:** the literal "(partial)" suffix on scenario 1's
M5 is hidden in the public catalogue, but preserved in `scenarios.json`. The
scoring mapping itself is unchanged.

**Recovery:** automatic SQLite saving, receipt corrections before lock, private
native JSON backups, validated restore, CSV score export and explicit reset.
Stable team IDs, rather than names, identify scores. Team setup locks once play
starts. The old single-page JSON format is not silently imported.

## Original weaknesses addressed

The uploaded page shipped answer maps directly in JavaScript and kept active
state in browser memory unless manually exported. Teams could not independently
follow a synchronized session. UI-only restrictions were not an authorization
boundary. Its narrative claim that doing nothing "never wins" was not guaranteed
by the scoring formula.

The new edition makes those distinctions explicit. Arena reduces the incentive
to remain passive, but still does not claim that any purchase is better than a
badly chosen expensive one. The server also enforces copies, duplicate-item
limits, budgets, reserve prices and phase locks even for directly crafted API
requests.

## Deliberately not added

No digital team bidding, learner score editing, student-submitted purchases,
private accounts, chat, forced music, hidden mid-round scoring changes,
post-reveal purchases, random score multipliers, pay-to-win bonuses, or externally
hosted cloud dependency. One running server hosts one active game; use separate
ports and data directories for separate concurrent classrooms.
