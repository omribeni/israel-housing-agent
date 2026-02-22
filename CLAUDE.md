# Israel Housing Agent — Project Notes

## Git & GitHub Setup

- **Git identity (local)**: Omri Ben Ishai <omribenishai015@gmail.com> — set via local `.git/config`, separate from the system/global work identity.
- **GitHub repo**: https://github.com/omribeni/israel-housing-agent under the **personal** account `omribeni`.
- **gh CLI has two accounts**: `omribeni` (personal) and `omri-benishai-cyera` (work). Before pushing, always verify the active account:
  ```
  gh auth status
  ```
  If the work account is active, switch first:
  ```
  gh auth switch -u omribeni
  ```
  If git push still fails with 403 after switching, run `gh auth setup-git` to reconfigure the git credential helper.

## Data Source Gotchas

### Google News RSS
- URLs use `hl=iw` but Google redirects to `hl=he`. The httpx client **must** have `follow_redirects=True` or it gets a 302 with no content.

### Ynet
- The real estate section URL changes periodically. As of Feb 2026 it is `/economy/category/8315`. The old `/economy/realestate` returns 404. If Ynet returns 0 articles, check the category number — inspect https://www.ynet.co.il/economy and look for the real estate link in the nav.

### Globes
- The real estate section is at `/news/home.aspx?fid=607`. Old tag-based URLs (`/news/tag/...`) are all dead (404). Section IDs: Stock Market `fid=585`, Real Estate `fid=607`, Law `fid=829`, Tech `fid=594`.
- Article titles are plain text inside `<a>` tags (no heading elements), so the title extraction fallback to `link_tag.get_text()` is what works.

### Calcalist & TheMarker
- Both working as of Feb 2026. Standard HTML scraping with BeautifulSoup.

### dira.moch.gov.il (Government Housing Lotteries)
- **Do NOT try to scrape this site directly.** It is an Angular SPA with reCAPTCHA-protected API endpoints (`/api/Invoker?method=...`). The HTML pages return empty shells — no server-rendered content.
- **Use data.gov.il instead**: CKAN Datastore API, resource ID `7c8255d0-49ef-49db-8904-4cf917586031` ("Tracking Discounted Housing Lottery Draws"). Updated weekly, 2300+ records, no auth required.
- API: `https://data.gov.il/api/3/action/datastore_search?resource_id=7c8255d0-49ef-49db-8904-4cf917586031&limit=100&sort=LotteryExecutionDate desc`

### land.gov.il (Israel Land Authority)
- **This site no longer exists.** All URLs 301 redirect to `www.gov.il/he/Departments/israel_land_authority/govil-landing-page`.
- **www.gov.il is behind Cloudflare bot protection** — returns 403 for all programmatic requests regardless of headers.
- The Land Gov collector queries data.gov.il for ILA-related data. Currently returns 0 because the "apartments for sale without lottery" resource (`ea93b3c9-15e2-4b74-a632-097ee53737e4`) is empty, and no lottery records match ILA-specific queries.

## Target Areas

Central (Tel Aviv, Ramat Gan, Givatayim, Petah Tikva), Sharon (Netanya, Herzliya, Ra'anana, Kfar Saba, Hod HaSharon), Gezer (regional council settlements + Mazkeret Batya), Ashdod area (Ashdod, Ashkelon, Gan Yavne, Yavne).

## Running Locally

```bash
# Dry-run test (scraping only, no API keys needed)
python test_collectors.py

# Full pipeline (requires .env with ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
python -m src.main
```

## Deployment

Railway with cron `0 5 * * *` (5 AM UTC ~ 7 AM Israel). Dockerfile builds from pyproject.toml. Set env vars in Railway dashboard. Attach a volume at `/app/data` for SQLite persistence.
