# Mazha Live — Kerala Dam Water Level Scrapers

Automated scrapers that pull live dam/reservoir water levels for Kerala,
covering **both** major departments, producing simple JSON your map can
consume directly. No AI required — pure regex/HTML/PDF parsing.

## What's in here

| Script | Covers | Source | Needs API keys? |
|---|---|---|---|
| `dam_scraper.py` | 18 KSEB reservoirs (power generation) | dams.kseb.in | No |
| `irrigation_dam_scraper.py` | 20 Irrigation Dept reservoirs (irrigation/drinking water) | KSDMA-hosted PDF | No |

Together these cover Kerala's major dams from both departments — 38
reservoirs total.

Each scraper outputs two files:
- A full `*_state.json` (detailed, for your own backend/history)
- A simple `*_colors.json` (`{name: "red"|"orange"|"blue"|"green"}`) — **this is the one your map should fetch**

Color logic: today's water level is compared against that reservoir's own
Blue/Orange/Red alert thresholds (red = highest severity). No threshold
published for a reservoir (common for barrages/regulators) → defaults to green.

---

## Part 1 — Test everything locally

### 1.1 Set up a clean environment
```bash
mkdir mazha-dam-scrapers && cd mazha-dam-scrapers
# copy dam_scraper.py, irrigation_dam_scraper.py, requirements.txt,
# test_dam_parser.py, test_irrigation_real.py here
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 1.2 Run the test suites first (no network needed)
These validate parsing logic against real government data already baked
into the tests — a good sanity check before touching the live internet:
```bash
python test_dam_parser.py       # KSEB dam table parsing
python test_irrigation_real.py  # irrigation reservoir parsing (barrages + inline remarks)
```
Both should print `✅ ALL ASSERTIONS PASSED` with no errors.

### 1.3 Run the real scrapers against live data
```bash
python dam_scraper.py             # KSEB — 18 reservoirs
python irrigation_dam_scraper.py  # Irrigation Dept — 20 reservoirs
```
No API keys needed for either — watch the printed JSON output and the
`=== ... colors (for map) ===` block at the end of each run.

### 1.4 Check the output files
After running, you should see:
```
dam_state.json                dam_colors.json
irrigation_dam_state.json     irrigation_dam_colors.json
```
Open `dam_colors.json` and `irrigation_dam_colors.json` — each reservoir
should have a name and a color.

---

## Part 2 — Deploy as a new GitHub project

### 2.1 Create the repo
1. **github.com** → **New repository**
2. Name it (e.g. `mazha-dam-alert`)
3. Choose **Private** (recommended — see Part 3 for publishing just the
   JSON output publicly while keeping scraper code private)
4. **Create repository**

### 2.2 Push your local project
```bash
cd mazha-dam-scrapers
git init
git add .
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mazha-dam-alert.git
git commit -m "Initial commit: KSEB + Irrigation Dept dam scrapers"
git push -u origin main
```

### 2.3 Add the GitHub Actions workflow
1. In your repo, create `.github/workflows/scrape.yml`
2. Paste in the contents of `scrape.yml` from this project (2 jobs: KSEB
   dams + Irrigation dams, both running every 6 hours)
3. Commit

No secrets needed — both scrapers are pure regex/HTML/PDF, no AI keys required.

### 2.4 Trigger a manual test run
1. **Actions** tab → select the workflow → **Run workflow**
2. Wait for both jobs to show green checkmarks
3. Check the repo — you should now see 4 output JSON files committed

### 2.5 Confirm the schedule works
Come back in a few hours and check the **Actions** tab shows automatic
(non-manual) runs happening on schedule, and the JSON files' commit
timestamps are updating.

---

## Part 3 — Publish just the JSON output publicly (keep code private)

If you want mazha.live's public map to read this data without exposing
your scraper code:

1. Create a **second, public** repo (e.g. `mazha-dam-data`)
2. Generate a Personal Access Token (`repo` scope) at
   **github.com/settings/tokens**
3. Add it as a secret `DATA_REPO_TOKEN` in your **private** repo
4. Add a step to each job in your workflow that checks out the public
   repo, copies the `*_colors.json` file into it, and pushes:

```yaml
      - name: Checkout public data repo
        uses: actions/checkout@v4
        with:
          repository: YOUR_USERNAME/mazha-dam-data
          token: ${{ secrets.DATA_REPO_TOKEN }}
          path: public-data-repo

      - name: Copy dam_colors.json into public repo
        run: cp dam_colors.json public-data-repo/dam_colors.json

      - name: Commit and push to public repo
        run: |
          cd public-data-repo
          git config user.name "mazha-bot"
          git config user.email "bot@users.noreply.github.com"
          git add dam_colors.json
          git commit -m "Update dam colors $(date -u)" || echo "No changes"
          git push
```
(Add the equivalent for `irrigation_dam_colors.json` in the irrigation job.)

Your map then fetches from the public repo's raw URLs:
```
https://raw.githubusercontent.com/YOUR_USERNAME/mazha-dam-data/main/dam_colors.json
https://raw.githubusercontent.com/YOUR_USERNAME/mazha-dam-data/main/irrigation_dam_colors.json
```

---

## Notes / known limitations

- **KSEB scraper**: uses WordPress's REST API to reliably find the latest
  post on dams.kseb.in (no ID-guessing). If they migrate off WordPress or
  change their table's column order, this will need updating.
- **Irrigation scraper**: parses a PDF whose row layout varies (barrages
  skip Blue/Orange/Red thresholds entirely) — handled generically via
  token-count logic, tested against real government PDF text. If KSDMA
  changes the PDF's column order, re-run `test_irrigation_real.py` to
  check it still parses correctly.
- Dam coordinate lookups: the KSEB ones came from a verified real JSON
  source; the Irrigation Dept ones are geography-based estimates worth
  spot-checking against Google Maps before relying on them for anything
  precision-critical.
- Neither scraper needs AI/API keys — both are pure regex/HTML/PDF parsing,
  which also means no ongoing API costs and nothing to break if a free
  tier's terms change.
