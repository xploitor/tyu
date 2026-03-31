import asyncio
import logging
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

# --- CONFIG ---
SERVICE_ACCOUNT_FILE = "service-account.json"
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/spreadsheets"
]
SPREADSHEET_NAME = "GSC Metrics"
BATCH_SIZE = 500  # rows per batch write
MAX_RETRIES = 5
BACKOFF_FACTOR = 2
THREADS = 5  # concurrency

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# --- AUTHENTICATION ---
def get_gsc_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def get_gspread_client():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


# --- HELPER: RETRY DECORATOR ---
def retry(func):
    def wrapper(*args, **kwargs):
        delay = 1
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except HttpError as e:
                if e.resp.status in [429, 500, 503]:
                    logging.warning(f"Retryable error {e.resp.status}: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= BACKOFF_FACTOR
                else:
                    logging.error(f"Non-retryable HTTP error: {e}")
                    raise
            except Exception as e:
                logging.error(f"Error: {e}")
                raise
        raise Exception(f"Failed after {MAX_RETRIES} retries")
    return wrapper


# --- FETCH SITES ---
@retry
def fetch_sites(service):
    response = service.sites().list().execute()
    return [site["siteUrl"] for site in response.get("siteEntry", [])]


# --- FETCH METRICS ---
@retry
def fetch_metrics(service, site_url, start_date, end_date):
    request = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": [],  # aggregate metrics
    }
    response = service.searchanalytics().query(siteUrl=site_url, body=request).execute()
    clicks = response.get("rows", [{}])[0].get("clicks", 0) if response.get("rows") else 0
    impressions = response.get("rows", [{}])[0].get("impressions", 0) if response.get("rows") else 0
    return clicks, impressions


# --- DATE RANGES ---
def get_date_ranges():
    today = datetime.utcnow().date()
    return {
        "last_7_days": (today - timedelta(days=7), today),
        "last_30_days": (today - timedelta(days=30), today),
        "last_90_days": (today - timedelta(days=90), today),
    }


# --- WRITE TO SHEET ---
def write_to_sheet(client, data):
    sheet = client.open(SPREADSHEET_NAME).sheet1
    # Clear existing data
    sheet.clear()
    # Prepare header
    header = [["domain", "range", "clicks", "impressions"]]
    sheet.append_rows(header, value_input_option="RAW")

    # Batch writing
    for i in range(0, len(data), BATCH_SIZE):
        batch = data[i:i + BATCH_SIZE]
        sheet.append_rows(batch, value_input_option="RAW")
    logging.info(f"Written {len(data)} rows to sheet.")


# --- MAIN FUNCTION ---
async def main():
    gsc_service = get_gsc_service()
    gs_client = get_gspread_client()

    logging.info("Fetching list of sites...")
    sites = fetch_sites(gsc_service)
    logging.info(f"Found {len(sites)} sites.")

    date_ranges = get_date_ranges()
    results = []

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=THREADS)

    async def process_site(site):
        site_results = []
        for label, (start, end) in date_ranges.items():
            start_str = start.isoformat()
            end_str = end.isoformat()
            clicks, impressions = await loop.run_in_executor(
                executor, fetch_metrics, gsc_service, site, start_str, end_str
            )
            site_results.append([site, label, clicks, impressions])
        return site_results

    tasks = [process_site(site) for site in sites]
    all_results = await asyncio.gather(*tasks)

    # Flatten list
    for r in all_results:
        results.extend(r)

    logging.info("Writing results to Google Sheet...")
    write_to_sheet(gs_client, results)
    logging.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
