# The Forbidden Forest — Strategic Edition

Standalone Python `discord.py` bot. Do not replace your SS Knowledge Showdown bot with this project; use a separate Railway service or repository.

## Install

1. Upload **the contents of this folder** to the root of a new GitHub repository (so `bot.py` and `requirements.txt` are at the root). Alternatively set Railway Root Directory to the folder containing them.
2. Railway service variables: `DISCORD_TOKEN`, `GUILD_ID`, `EVENT_CHANNEL_ID`, `ROLE_ID=1567982021106602065`, `HOST_IDS=1501587787294703657`, and `DATABASE_PATH=/data/forest.sqlite3`.
3. **Attach a Railway persistent volume mounted at `/data`.** Without it, player data can disappear after deployment. Run **one replica only**; SQLite is not safe for multiple writers in separate containers.
4. Set custom start command to `python bot.py`. If a previous project still references `SSKnowledge.py`, remove that old start command and Procfile.
5. In Discord Developer Portal enable **Server Members Intent**. Grant the bot **Manage Roles**, **Add Reactions**, **Read Message History**, **Send Messages**, **Embed Links**, **Attach Files**, **Use Application Commands** and **View Channel**. Put the bot's highest role above the target role.
6. Run `/forest panel` in the event channel. Users react 🍁 for the supplied role.
7. Before the event, use `/forest test` and `/forest testreset` to test a separate host-only adventure. Test progress never counts for prizes.

## Dates

- Main opens: **8 November 2026, 00:00 GMT**.
- Main closes: **11 November 2026, 00:00 GMT** (72 hours).
- Tiebreaker window, if required: **11 November 00:00 – 12 November 00:00 GMT**.
- The scheduler checks every 30 seconds and reconciles missed transitions after restart. Actual Discord announcement delivery depends on the bot being online.

## Gameplay

40 encounters with identical encounter-type quotas for every player, shuffled per-player. All choice costs/outcomes are disclosed; there are no random hidden success rolls. Each player has one official run, plus host-only separate test mode. Adventures can be resumed using `/forest resume` after a button expires or the bot restarts.

Resources: health 100, energy 100, supplies 5, one potion. At encounter 11 choose one talent: Scout (next encounter preview), Guardian (5 less damage), Collector (+10 relic points). Rest at camps, use potions, forage, or use `/forest recover` up to twice (1 supply for 20 energy). **There is no time-based regeneration.**

Score caps: artefacts 1,000, objectives 300 (explore four times; take four demanding routes; collect three distinct artefact types), strategic challenges 200, escape 150, remaining health/energy 100. Maximum 1,750. Escape at 20, 30 or 35 encounters or complete all 40 alive. Defeat or not finishing by deadline forfeits 25% of artefact points and loses escape/resource bonuses.

Ties: final score, artefact points, completed objectives, remaining health + energy. If prize-position ties remain, eligible players complete the same five strategic questions during the following 24 hours; highest correct answers wins. If still tied, a **published deterministic hash of user ID and event name** provides a final non-speed-based fallback. This final fallback is deterministic, not a random audited draw.

Prizes: first 125c + HC Box; second 75c + HC Box; third 50c + HC Box.

## Commands

Player: `/forest help`, `/forest play`, `/forest resume`, `/forest status`, `/forest inventory`, `/forest recover`, `/forest leaderboard`, `/forest tiebreaker` (eligible players only).

Host: `/forest panel`, `/forest dashboard`, `/forest logs`, `/forest audit`, `/forest test`, `/forest testreset`.

## Important limitations

- The code has been syntax checked but **not tested against a live Discord server or Railway**. Test with your own server before advertising the event.
- The role panel graphic is `panel.png`; encounter images are in `encounter_art/` and must be uploaded with `bot.py`.
- The database schema is **different from the earlier V2 bot**. Use a **fresh database path** for this version; do not point it at the previous `forest.sqlite3` or overwrite live competition data. If you need to migrate prior runs, plan a separate migration.
- A Discord ID is not a unique human identity; alt accounts and outside assistance cannot be reliably prevented. Manual moderation may be required.
- All players receive the same encounter-type counts, but random order and talent/strategy effects can still produce unequal difficulty. This is not a mathematically proven fair competition.
- `/forest recover` has a limited number of uses; manage supplies and campsite recovery carefully.
