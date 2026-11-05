# The Forbidden Forest — Discord event bot

A standalone Python `discord.py` bot for a 72-hour, 40-encounter autumn adventure competition.

## Dates (UTC/GMT)
- Opens automatically: **8 November 2026 at 00:00 GMT**
- Closes automatically: **11 November 2026 at 00:00 GMT**
- If a prize-position tie survives the published secondary criteria, a five-encounter tiebreaker opens automatically, closing **12 November 2026 at 00:00 GMT**.

The bot must be running to post announcements; if it was offline, it catches up when restarted. Game action deadlines are always checked against UTC time, not just the background scheduler.

## Prizes
- First: **125c + HC Box**
- Second: **75c + HC Box**
- Third: **50c + HC Box**

## Setup
1. Create a new Discord application and bot at the Discord Developer Portal. Copy its token.
2. Enable **Server Members Intent** in the Developer Portal.
3. Invite the bot with `bot` and `applications.commands` scopes. Grant **View Channel, Send Messages, Embed Links, Attach Files, Add Reactions, Read Message History, Manage Roles, Mention @everyone/@here/All Roles** (where you intend to use it).
4. In the server's role hierarchy, place the bot's highest role **above** SS Quiz (`1567982021106602065`).
5. Copy `.env.example` to `.env`, fill `DISCORD_TOKEN`, `GUILD_ID`, and `EVENT_CHANNEL_ID` (the event announcements channel). `HOST_IDS` includes `1501587787294703657` by default.
6. Install dependencies: `pip install -r requirements.txt`. Start with `python bot.py`.
7. In Discord, run `/forest panel` in the signup channel. This posts the graphic and a real `@everyone` message and adds the 🍁 reaction.
8. **No manual start command needed.** At the scheduled opening, the bot posts a `Begin / Resume Adventure` button in `EVENT_CHANNEL_ID`, and players can also use `/forest play`.

## Railway
Connect a GitHub repository with these files. Set the variables from `.env.example` in Railway's Variables section. Use a **persistent Railway volume** mounted at `/data`, with `DATABASE_PATH=/data/forest.sqlite3`. The supplied `railway.json` starts the worker. **Run exactly one instance**; multiple instances using separate SQLite files will corrupt the fairness of the competition. Keep the bot online for the full event and tiebreaker. Do not commit `.env` or the database.

## Commands

Player commands:
- `/forest help`: full rules, scoring, prizes, tiebreaker and command guide
- `/forest play`: start or resume an adventure
- `/forest resume`: reopen your saved adventure
- `/forest status`: current health, energy, supplies, step and status
- `/forest inventory`: current artefact count and points
- `/forest escape`: end early and secure all collected points
- `/forest leaderboard`: published standings once the event and any bonus expedition finish

Host-only (only `HOST_IDS`, including `1501587787294703657`):
- `/forest panel`: post the graphic, `@everyone` call and 🍁 reaction role signup
- `/forest dashboard`: live participation totals
- `/forest logs`: recent recorded actions
- `/forest player`: inspect an individual participant
- `/forest audit`: basic data-integrity checks and draw commitment

## Gameplay and fairness
- One official adventure per Discord user ID, stored persistently. Players must have the SS Quiz role when **starting**.
- Every main run has exactly five encounters from each of eight categories, shuffled per player; event descriptions and risk outcomes are seeded individually.
- Each encounter offers the same three choices: Careful (guaranteed 1x reward), Explore (75% chance for 2x), Gamble (45% chance for 4x). Each costs energy; failures damage health. Energy recovers by 12 per encounter. A player with insufficient energy automatically rests, using one supply if available.
- Reward size increases at fixed encounter milestones for **every** player. A success also awards an artefact. The inventory lists collected artefact names and counts. Score is calculated from rewards, not a separately editable inventory field.
- Players may escape at any time before the deadline to bank their points. At 40 encounters, a living player banks automatically. Reaching 0 health banks half the accumulated points. An unfinished living run at the 72-hour deadline is automatically banked.
- Public scores are hidden until final results. The host dashboard and logs are private/ephemeral.
- Ranking: secured points, artefact count, remaining health, remaining energy. Only ties affecting the top three positions trigger the automatic five-encounter bonus expedition. Bonus ranking: bonus score, bonus objectives, bonus health, least energy spent. Remaining exact ties are decided by a deterministic, precommitted draw; the commitment is visible in `/forest audit` and the secret is revealed at finalisation.
- Every button checks user ID, current step, stage and event deadline. Actions use a database transaction under an application lock, preventing duplicate reward claims from repeated button clicks.

## Limitations / security
- This is an implementation for testing before a prize event, **not a guarantee of zero exploits**. No bot can prevent Discord alt accounts, collusion or outside strategy assistance. Server admins should check eligibility manually for prize winners.
- Discord ephemeral messages expire and Discord outages can interrupt gameplay; `/forest resume` restores the current step. Game actions do not require the old ephemeral message to remain available.
- For a larger production deployment, consider PostgreSQL, migrations, operational backups, independent tests and a staging server. This SQLite version is designed for one running bot instance.
- The forest is a **turn-based risk/reward game**, not a real-time animated RPG. Players' individual adventures differ in ordering and outcomes, but not in available action mechanics.
- The `@everyone` mention requires both Discord server/channel permissions and the bot's role permission; the signup embed's `@everyone` text alone does not ping users.

## Suggested prelaunch tests
1. Verify `/forest panel` tags everyone and adds/removes the role on reaction changes.
2. Test `/forest help`, host access denial, and a normal run in a staging server.
3. Test duplicate clicks, old-button clicks, disconnect/restart, a player reaching 0 health, escaping early, and a run ending at 40.
4. Simulate deadlines and tied standings with a test database before running the live event.
