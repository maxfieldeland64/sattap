# Deploying SatTap (Cloudflare Pages + GitHub Actions)

How it fits together:

```
GitHub Action, daily 17:00 UTC
  fetch last hour of GOES frames -> build 5 rounds -> tools/publish.py
      |- build/kv.json  (answers)  -> Workers KV  "ANSWERS"        (private)
      '- dist/          (site)     -> Cloudflare Pages             (public, static, CDN)
                                        '- functions/api/guess.js  reads KV, scores guesses
```

Players load static files (the web app, `puzzles/<date>.json`, images and loops). The only
dynamic call is `POST /api/guess`, handled by a Pages Function that looks the answer up in KV.
Answers are never in the repo or in `dist/`; `tools/publish.py` refuses to publish if any answer
field shows up in a public file.

A puzzle is "today's" from 18:00 UTC (noon in Denver) until 18:00 UTC the next day, so the
17:00 UTC job has an hour of slack before players roll over. Keep `ROLLOVER_UTC_HOUR` in
`sattap/config.py` and `web/app.js` in sync if you change it.

## One-time setup (about 15 minutes)

You need a free Cloudflare account. All commands run in the repo root.

1. **Install and log in**

   ```bash
   npm install
   npx wrangler login
   ```

2. **Create the Pages project** (direct upload, no Git integration needed)

   ```bash
   npx wrangler pages project create sattap --production-branch main
   ```

   Its address will be `https://sattap.pages.dev` (or `https://sattap-xxx.pages.dev` if the name
   was taken; wrangler prints the real one).

3. **Create the KV namespace for answers**

   ```bash
   npx wrangler kv namespace create ANSWERS
   ```

   Copy the `id` it prints.

4. **Create an API token** for GitHub Actions: Cloudflare dashboard -> My Profile -> API Tokens ->
   Create Token -> Custom token, with two account permissions: **Cloudflare Pages: Edit** and
   **Workers KV Storage: Edit**. Also copy your **Account ID** (dashboard home, right sidebar).

5. **Add settings in GitHub**: repo -> Settings -> Secrets and variables -> Actions.

   | Type | Name | Value |
   |---|---|---|
   | Secret | `CLOUDFLARE_API_TOKEN` | the token from step 4 |
   | Secret | `CLOUDFLARE_ACCOUNT_ID` | your account id |
   | Variable | `CF_KV_NAMESPACE_ID` | the KV id from step 3 |
   | Variable | `CF_PAGES_PROJECT` | `sattap` (the project name from step 2) |
   | Variable | `SITE_URL` | the live address, e.g. `https://sattap.pages.dev` (optional on the very first run) |

6. **First run**: Actions -> "Daily puzzle" -> Run workflow. If it is night over the Americas,
   fill in `at` with a daytime UTC time from earlier today, for example `2026-10-16T17:00`.
   (Leave `date` empty unless you want a specific label.)

7. Open your Pages address. Done. After this the job runs by itself every day.

## Day-to-day

- **Rebuild or fix a day**: re-run the workflow (optionally with `date` / `at`).
- **Nothing showed up one day**: check the Actions tab. If a run fails, the previous puzzle simply
  stays live (the app shows the latest puzzle with a "no puzzle for today yet" note).
- **Late schedule**: GitHub's cron can run late. The 1 hour gap before the 18:00 UTC rollover
  absorbs most of it. GitHub can also pause scheduled workflows on a repo with no activity for a
  while; if the daily run stops, re-enable it from the Actions tab.
- **Carry-over**: each deploy replaces the whole site, so `publish.py` re-downloads the previous 6
  days from `SITE_URL` before deploying. Their answers stay in KV.
- **Custom domain**: Cloudflare dashboard -> Workers & Pages -> sattap -> Custom domains.

## Test the whole thing locally (no Cloudflare account needed)

```bash
python -m sattap.cli fetch --at 17:00 && python -m sattap.cli build --at 17:00
python tools/publish.py                       # writes dist/ and build/kv.json
npm run dev                                   # Pages + Function + local KV on http://127.0.0.1:8788
# in another terminal, seed the local KV with the answers:
npx wrangler kv bulk put build/kv.json --namespace-id ANSWERS --local
```

`python -m sattap.cli build` + `uvicorn sattap.api:app --reload` still works as the quick dev loop;
the FastAPI app serves the same `/puzzles/*.json` and `/api/guess` routes.

## Known gaps

- `/api/guess` has no rate limit. A determined player can probe it for answers. Cloudflare's
  dashboard can add a rate-limiting rule on `/api/guess` without code changes.
- Progress lives in each player's browser (`localStorage`), so there are no accounts, streaks or
  leaderboards yet. Cloudflare D1 is the natural next step.
- Wrangler's `kv bulk put` flags and the token permission names above are from wrangler 4.x and the
  dashboard at the time of writing; if a step errors, `npx wrangler <command> --help` is the source of truth.
