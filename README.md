# LoL Champion Data Scraper

Automated daily scraping system to fetch champion data from the Riot API, build statistics from Lolalytics, and ability data from the League of Legends Wiki. Data is compiled into a single JSON structure and persisted in a serverless Turso Database for external usage.

## Architecture

* **Riot API**: Detects the current patch being used in game.
* **League Wiki**: Fetches deep champion ability datasets (Name, text, cooldowns, stats).
* **Lolalytics**: Pulls meta winrates and role pick-rate distributions.

## Configuration

To run the scraper locally or in GitHub Actions, you need a [Turso](https://turso.tech) database.

Create a `.env` file based on the `.env.example` structure:
```bash
TURSO_DB_URL="libsql://your-database.turso.io"
TURSO_AUTH_TOKEN="your-secret-token"
```

## Running the Scraper

### Local Setup
```bash
pip install -r requirements.txt
python manual_scraper.py
```

### GitHub Actions
Once pushed to GitHub, the included `.github/workflows/scrape-champions.yml` file will automatically run:
- Once every 24 hours at midnight UTC
- Manually via "Run workflow" dispatch
- Upon push to the `main` branch

The action uses `lambda_function.py`, and requires your repository to have GitHub Action Secrets named `TURSO_DB_URL` and `TURSO_AUTH_TOKEN`.
