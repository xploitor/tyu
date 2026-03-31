# main.py
"""
Google Search Console → Google Sheets reporter.

For each verified GSC property, fetches aggregate clicks + impressions
over 3 date windows and writes all results to a single Google Sheet.

Auth:   Service account JSON (no interactive OAuth needed)
Output: domain | range | clicks | impressions
"""

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

import config

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("gsc_reporter.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------

SCOPES = [
    "[googleapis.com](https://www.googleapis.com/auth/webmasters.readonly)",
    "[googleapis.com](https://www.googleapis.com/auth/spreadsheets)",
    "[googleapis.com](https://www.googleapis.com/auth/drive)",
]


# ---------------------------------------------------------------------------
# 1. Auth setup
# ---------------------------------------------------------------------------

def build_credentials() -> Credentials:
    """Load service account credentials with the required scopes."""
    return Credentials.from_service_account_file(
        config.SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )


def build_gsc_service(creds: Credentials):
    """Return an authenticated Google Search Console API client."""
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def build_sheets_client(creds: Credentials) -> gspread.Client:
    """Return an authenticated gspread client."""
    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# 2. Fetch all verified sites
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(HttpError),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def fetch_sites(gsc_service) -> list[str]:
    """
    Return a list of all verified site URLs from Search Console.
    Includes both domain properties (sc-domain:...) and URL-prefix properties.
    """
    response = gsc_service.sites().list().execute()
    entries = response.get("siteEntry", [])

    sites = [
        entry["siteUrl"]
        for entry in entries
        if entry.get("permissionLevel") != "siteUnverifiedUser"
    ]

    log.info("Found %d verified site(s).", len(sites))
    return sites


# ---------------------------------------------------------------------------
# 3. Fetch aggregate metrics for one site + one date range
# ---------------------------------------------------------------------------

def _date_range(days: int) -> tuple[str, str]:
    """Return (start_date, end_date) strings for the last N days (excluding today)."""
    end = date.today() - timedelta(days=1)       # yesterday (last full day)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _is_retryable(exc: HttpError) -> bool:
    """Retry on 429 (quota) and 5xx (server errors); not on 4xx auth/not-found."""
    return exc.resp.status in (429, 500, 502, 503, 504)


@retry(
    retry=retry_if_exception_type(HttpError),
    wait=wait_exponential(multiplier=2, min=4, max=120),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _query_gsc(gsc_service, site_url: str, start_date: str, end_date: str) -> dict:
    """
    Single Search Analytics query — no dimensions → one aggregate row.
    Returns the raw API response dict.
    """
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "rowLimit": config.GSC_ROW_LIMIT,
        # No 'dimensions' key → fully aggregated
    }
    return (
        gsc_service
        .searchanalytics()
        .query(siteUrl=site_url, body=body)
        .execute()
    )


def fetch_metrics_for_site(
    gsc_service,
    site_url: str,
) -> list[dict]:
    """
    Fetch clicks + impressions for each configured date range for one site.
    Returns a list of row dicts: {domain, range, clicks, impressions}.
    Skips ranges that return no data (new/inactive properties).
    """
    rows = []
    domain = site_url  # preserve raw property identifier (incl. sc-domain: prefix)

    for dr in config.DATE_RANGES:
        start, end = _date_range(dr["days"])
        try:
            response = _query_gsc(gsc_service, site_url, start, end)
        except HttpError as exc:
            if exc.resp.status == 403:
                log.warning("403 – no access to %s. Skipping.", site_url)
                return []           # skip entire site
            if exc.resp.status == 404:
                log.warning("404 – property not found: %s. Skipping.", site_url)
                return []
            log.error("HttpError %s for %s (%s). Skipping range.",
                      exc.resp.status, site_url, dr["label"])
            continue                # skip this range, try others

        response_rows = response.get("rows", [])
        if not response_rows:
            # Property exists but has no data for this window
            clicks = 0
            impressions = 0
        else:
            agg = response_rows[0]
            clicks = int(agg.get("clicks", 0))
            impressions = int(agg.get("impressions", 0))

        rows.append({
            "domain": domain,
            "range": dr["label"],
            "clicks": clicks,
            "impressions": impressions,
        })

    return rows


# ---------------------------------------------------------------------------
# 4. Concurrent metric fetching across all sites
# ---------------------------------------------------------------------------

def fetch_all_metrics(gsc_service, sites: list[str]) -> list[dict]:
    """
    Fetch metrics for every site concurrently using a thread pool.

    GSC API is I/O-bound, so threading is appropriate here.
    MAX_WORKERS controls parallelism to stay within quota limits.
    """
    all_rows: list[dict] = []
    total = len(sites)

    log.info(
        "Fetching metrics for %d site(s) across %d date range(s) "
        "using %d worker(s)...",
        total, len(config.DATE_RANGES), config.MAX_WORKERS,
    )

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        future_to_site = {
            executor.submit(fetch_metrics_for_site, gsc_service, site): site
            for site in sites
        }

        completed = 0
        for future in as_completed(future_to_site):
            site = future_to_site[future]
            completed += 1

            try:
                rows = future.result()
                all_rows.extend(rows)
            except Exception as exc:
                log.error("Unexpected error fetching %s: %s", site, exc)

            if completed % 100 == 0 or completed == total:
                log.info("Progress: %d / %d sites processed.", completed, total)

    log.info("Total data rows collected: %d", len(all_rows))
    return all_rows


# ---------------------------------------------------------------------------
# 5. Write results to Google Sheets
# ---------------------------------------------------------------------------

SHEET_HEADER = ["domain", "range", "clicks", "impressions"]


def _get_or_create_worksheet(
    client: gspread.Client,
    spreadsheet_name: str,
    worksheet_name: str,
) -> gspread.Worksheet:
    """Open the spreadsheet and return (or create) the target worksheet."""
    spreadsheet = client.open(spreadsheet_name)
    try:
        ws = spreadsheet.worksheet(worksheet_name)
        log.info("Using existing worksheet '%s'.", worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=worksheet_name, rows=1, cols=len(SHEET_HEADER)
        )
        log.info("Created new worksheet '%s'.", worksheet_name)
    return ws


def write_to_sheet(
    client: gspread.Client,
    data_rows: list[dict],
    spreadsheet_name: str = config.SPREADSHEET_NAME,
    worksheet_name: str = config.WORKSHEET_NAME,
) -> None:
    """
    Clear the worksheet, write the header, then batch-write all data rows.
    Uses chunked updates to stay within Sheets API payload limits.
    """
    if not data_rows:
        log.warning("No data to write. Sheet will not be updated.")
        return

    ws = _get_or_create_worksheet(client, spreadsheet_name, worksheet_name)

    log.info("Clearing existing sheet content...")
    ws.clear()

    # Build list-of-lists for batch update
    matrix: list[list] = [SHEET_HEADER]
    for row in data_rows:
        matrix.append([
            row["domain"],
            row["range"],
            row["clicks"],
            row["impressions"],
        ])

    total_rows = len(matrix)
    log.info("Writing %d row(s) (including header) in batches of %d...",
             total_rows, config.SHEETS_BATCH_SIZE)

    # Resize sheet once upfront to avoid repeated auto-expand calls
    ws.resize(rows=total_rows, cols=len(SHEET_HEADER))

    # Chunked batch update
    chunk_size = config.SHEETS_BATCH_SIZE
    for chunk_start in range(0, total_rows, chunk_size):
        chunk = matrix[chunk_start: chunk_start + chunk_size]
        end_row = chunk_start + len(chunk)

        # A1 notation: e.g. A1:D5000
        start_cell = gspread.utils.rowcol_to_a1(chunk_start + 1, 1)
        end_cell = gspread.utils.rowcol_to_a1(end_row, len(SHEET_HEADER))
        cell_range = f"{start_cell}:{end_cell}"

        ws.update(cell_range, chunk, value_input_option="RAW")

        log.info("  Written rows %d–%d.", chunk_start + 1, end_row)
        # Brief pause between large chunks to avoid Sheets quota errors
        if end_row < total_rows:
            time.sleep(1)

    log.info("Sheet write complete.")


# ---------------------------------------------------------------------------
# 6. Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== GSC Reporter starting ===")
    start_time = time.monotonic()

    # Auth
    creds = build_credentials()
    gsc_service = build_gsc_service(creds)
    sheets_client = build_sheets_client(creds)

    # Fetch sites
    sites = fetch_sites(gsc_service)
    if not sites:
        log.warning("No verified sites found. Exiting.")
        return

    # Fetch metrics concurrently
    data_rows = fetch_all_metrics(gsc_service, sites)

    # Write to Sheets
    write_to_sheet(sheets_client, data_rows)

    elapsed = time.monotonic() - start_time
    log.info("=== Done in %.1f seconds ===", elapsed)


if __name__ == "__main__":
    main()
