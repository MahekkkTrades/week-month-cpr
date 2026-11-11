# CPR Atlas — Yahoo Finance Weekly / Monthly CPR Screener

## Windows setup
1. Extract the ZIP.
2. Double-click `RUN_WINDOWS.bat`. The first launch installs `yfinance` and `pandas`.
3. Open http://127.0.0.1:8000 and click **Run Confluence Scan**.

Alternatively: `python -m pip install -r requirements.txt` then `python server.py`.

## Rules
- Universe: NASDAQ + NYSE + NYSE American ordinary listed equities from Nasdaq Trader symbol directory, excluding ETFs and test issues. Some other instruments may remain in the directory; this is not a verified common-stock-only feed.
- ADV20: arithmetic mean of daily share volume over 20 most recent **completed** trading sessions. Strictly >1,000,000 shares/day.
- Weekly CPR uses previous **completed calendar week**; monthly CPR uses previous **completed calendar month**. Periods are not rolling 5/20-day windows.
- Pivot P=(H+L+C)/3; BC=(H+L)/2; TC=2P-BC; CPR lower=min(BC,TC), upper=max(BC,TC).
- Confluence if max(weekly.lower,monthly.lower) <= min(weekly.upper,monthly.upper). Strength = overlap width / union envelope width, expressed as percentage.
- Price OHLC is **unadjusted** (`auto_adjust=False`) so the displayed CPR uses quoted levels; historical splits can affect older ranges.
- Sector classification uses Yahoo `Ticker.info['sector']`; metadata is cached for 30 days. Sector metadata is fetched only for liquid CPR matches and cached for 30 days. Sector selection filters the final matching results; the scan still checks the full selected symbol scope.
- Quick Test and Pilot scopes take the alphabetically first N listings, **not** a random or representative sample. Use Full Universe for complete discovery.

## Reliability and constraints
- Batched Yahoo downloads; failures are counted and skipped rather than terminating the entire scan.
- `.cache/` stores listing/sector metadata. Results remain in server memory until the next scan or restart.
- Yahoo can throttle high-volume requests. The UI displays progress and errors; a full-universe scan may take considerable time. The application does not guarantee completeness if Yahoo rate limits or omits symbols.
- No API key is needed. Yahoo Finance/yfinance is an unofficial research interface; check Yahoo's usage terms before commercial deployment.
- Data is not real-time and this is not trading advice.

## Testing
Run `python -m unittest discover -s tests -v`.


## Automatic refresh (new)

- Frontend polls `/api/status` every 2 seconds. This is **status polling**, not a Yahoo download.
- Backend automatically starts a new Yahoo scan every 60 minutes while the server runs.
- Set `CPR_REFRESH_MINUTES=60` (minimum 15), `CPR_AUTO_REFRESH=1`, and `CPR_SCAN_LIMIT=100` in your Windows terminal before launching to change the defaults. `CPR_SCAN_LIMIT=0` scans the full exchange universe.
- Full-universe Yahoo Finance scans can be slow, rate-limited, and incomplete. The default automatic scan is deliberately capped at 100 symbols.
- Sector filters are applied to the completed results instantly; a new sector selection does not require re-downloading.
- Weekly and monthly CPR always use the **previous completed** calendar week/month, so those levels do not change intraday. ADV is refreshed when a new scan completes.
- Scans run in the background; `/api/status` reports progress and failures.
- If Yahoo blocks requests, unavailable symbols are counted as errors rather than silently shown as nonmatches.


## Multi-week score (0–100)

The **active monthly CPR** is calculated from the previous completed calendar month's H/L/C. The current month's weekly CPRs are calculated from each **fully completed Monday–Sunday week whose Monday is in the current month**. A partial week is never used. On the first week of a month there may be no qualifying completed weeks, so no matches will be shown until one finishes. A week crossing the month boundary belongs to the month of its Monday.

- 35 points: fraction of observed weekly CPRs entirely inside the active monthly CPR.
- 30 points: fraction of consecutive weekly pairs with an intersection also overlapping monthly CPR. No pair yet = 0 points.
- 25 points: latest CPR narrowness compared with median of previous completed weeks **before this month** (requires four prior nonzero widths). A zero-width current CPR earns all 25 points when history is sufficient.
- 10 points: latest weekly pivot proximity to monthly pivot, normalized by max(monthly width, historical median weekly width).

Only stocks with latest weekly CPR overlapping the monthly CPR are included. `scoreBreakdown` is included per row and CSV includes component metadata. This is a descriptive ranking, **not a statistically verified predictor of a breakout**. The 100-point maximum is not generally achievable with only one observed week because consecutive-week points require at least two weeks.


## ADV and price filters (v2.1.0)

- The results panel has independent ADV20 and last-close price filters.
- ADV presets: above 1M, 2M, 5M, 10M, and 20M shares/day, plus a custom minimum and optional maximum.
- Price presets include common price bands (for example $1–$5, $5–$20, $20–$50), above $50, above $100, and a custom minimum / optional maximum.
- Filters are applied to the already-qualified weekly/monthly CPR confluence results; they do not create new CPR matches or trigger a rescan.

## Team update notifications

The **Publish update** button sends a version announcement to the hosted Render instance. Team members using the hosted app see a red notification dot and an update banner. Each browser can dismiss the current announcement. This is an announcement system only: it does **not** transfer source code or automatically redeploy Render. Push your code to the deployment source / redeploy Render separately so teammates receive the actual code changes.

### Render configuration (one-time)

1. In the Render service, add environment variable `CPR_UPDATE_TOKEN` with a long random secret value.
2. Add a persistent disk to the service mounted at `/var/data`.
3. Add environment variable `CPR_DATA_DIR=/var/data`.
4. Redeploy. The version announcement is stored in `version.json` on that disk and survives service restarts.

### Local Windows configuration

In PowerShell, before launching `RUN_WINDOWS.bat`, set these variables (use your actual Render service URL and the same token configured on Render):

```powershell
$env:CPR_UPDATE_URL = "https://YOUR-SERVICE.onrender.com"
$env:CPR_UPDATE_TOKEN = "paste-the-same-long-random-secret"
.\RUN_WINDOWS.bat
```

Then open the local app, make your code changes, and click **Publish update**. Enter a short message such as `v2.1.1 – Added ADV and price filters`. The local server securely forwards the announcement to Render; the secret is not sent to the browser. If `CPR_UPDATE_URL` is not configured locally, the button cannot notify the deployed team app.

Do not commit the update token to GitHub or put it in frontend JavaScript. Keep the same token configured as a Render environment variable and a local machine environment variable. The app returns an authorization/configuration error if the token is missing or incorrect.
