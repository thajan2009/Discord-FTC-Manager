# FTCManager — what goes where (Bot-hosting.net + Netlify)

## 1. Discord portal (once)
- https://discord.com/developers/applications → New app → Bot → copy Token.
- Bot → Privileged Intents: enable MESSAGE CONTENT + SERVER MEMBERS.
- OAuth2 → Redirects → add:
  - `https://YOUR-SITE.netlify.app/api/auth/callback`
  - `http://localhost:4321/api/auth/callback`
- OAuth2 → scopes for invite: `bot`, `applications.commands`. Perms: Send Messages, Embed Links, Use Application Commands.

## 2. Bot-hosting.net (bot only)
1. Login → Create Server → Python.
2. On your PC, zip the CONTENTS of `bot/` so zip root has `main.py`, `audioop.py`, `requirements.txt`, `cogs/`, `db/`, `data/`, `utils/` (edit `data/ftchelp.py` first to add your FTC help entries).
   - GOOD zip root: `main.py`, `audioop.py`, `requirements.txt`
   - BAD: `bot/main.py` (extra folder — move files out after Unarchive if this happens).
3. Panel → Files → Upload zip → Unarchive → move to root, delete zip.
4. Panel → Startup → Entry File = `main.py`. Do NOT run pip in console — `requirements.txt` auto-installs.
5. Panel → Environment/Variables → add:
   - `DISCORD_TOKEN`, `MONGO_URI`, `COMMAND_PREFIX=!`, `TEST_GUILD_ID` (optional for instant slash), `PUBLIC_WEB_URL=https://YOUR-SITE.netlify.app` (used by `!manage`).
6. Start. Logs should show `Logged in as ...` + `slash synced`.
7. Free plan: click Renew every ~4 days or bot pauses.
8. Test in server: `!ping`, `!bal`, `/balance`, `!inv`, `/inventory`, `!addcmd hello Hi`, `!ftchelp`.

## 3. Netlify (web only)
1. Push this repo to GitHub. Netlify → Add site → Import → Base dir `web/`, Build `npm run build`, Publish `web/dist/`.
2. Netlify → Env vars → `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `MONGO_URI` (same Atlas link), `PUBLIC_WEB_URL=https://YOUR-SITE.netlify.app`, `SESSION_SECRET` (optional), plus `DISCORD_TOKEN` (lets dashboard list only servers containing the bot; without it, falls back to Mongo).
3. Deploy → open site → Login with Discord → Dashboard → open server → Add Team (max 3, name+aliases) → test `!bal teamalias`.
4. Settings toggles: Finance/Inventory `everyone|admins` enforced by bot instantly (reads Mongo per command).

## 4. Mongo shape (wilsodc.wilsodc)
- `{_type:"guild", guild_id, teams[], settings{finance_mode,inventory_mode}, finance{teams}, inventory{teams}, commands[]}`
- `{_type:"global_commands", entries:{trigger:response}}` — edit via Mongo Compass to add global responses.

## 5. Command map (final)
- Hybrid (both): `!bal|!balance|!finance` ↔ `/balance [team]`, `!inv|!inventory` ↔ `/inventory [team]`, `!outreach|!out|!outreachlist` ↔ `/outreach [team]`, `!ping`↔`/ping`, `!help`↔`/help`, `!status`↔`/status`, `!manage`↔`/manage` (posts `{PUBLIC_WEB_URL}/guild/<server id>`), plus `!findel <exact name>`, `!invdel <exact name>`, `!outdel <exact name>`.
- Prefix-only (no slash): `!addcmd`, `!delcmd`, `!cmds`, `!ftchelp [page]`, FTC directory triggers (e.g. `!axon`), and all custom `!triggers`.
- No IDs anywhere: embeds show plain names; removal matches names exactly (case-insensitive).
- FTC directory lives in `bot/data/ftchelp.py` — one `"trigger": "response"` line per entry, restart bot to apply. Server `!addcmd` overrides it per server.

## 6. Troubleshooting (Bot-hosting.net)
- `ModuleNotFoundError: No module named 'audioop'` → the host runs Python 3.14+, where that stdlib module was removed but discord.py still imports it. Fixed in-repo: `bot/audioop.py` is a fallback stub (voice is unused) — make sure it is included at the ROOT of your uploaded zip, next to `main.py`, then Restart.
  If the panel's Startup tab offers a Python version choice, 3.12 or 3.13 also works (with or without the stub).
