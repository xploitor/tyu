import logging
import asyncio
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import gspread
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.errors import HttpError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

# --- CONFIGURATION ---
SERVICE_ACCOUNT_FILE = 'service-account.json'
SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID_HERE'
SHEET_NAME = 'Sheet1'
MAX_WORKERS = 10  # Adjust based on your API quota limits

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GSCManager:
    def __init__(self, credentials_path):
        self.scopes = [
            'https://www.googleapis.com/auth/webmasters.readonly',
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        self.creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=self.scopes
        )
        self.service = build('searchconsole', 'v1', credentials=self.creds)
        self.gc = gspread.authorize(self.creds)

    def get_sheet(self, spreadsheet_id, sheet_name):
        sh = self.gc.open_by_key(spreadsheet_id)
        return sh.worksheet(sheet_name)

    @retry(
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(HttpError)
    )
    def fetch_all_sites(self):
        """Fetches all sites verified in GSC."""
        logger.info("Fetching site list...")
        site_list = self.service.sites().list().execute()
        return [s['siteUrl'] for s in site_list.get('siteEntry', [])]

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(HttpError)
    )
    def query_gsc(self, site_url, days):
        """Fetches aggregate clicks and impressions for a specific date range."""
        end_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days + 3)).strftime('%Y-%m-%d')
        
        request = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': [] # Aggregate data only
        }
        
        response = self.service.searchanalytics().query(
            siteUrl=site_url, body=request).execute()
        
        rows = response.get('rows', [])
        if not rows:
            return 0, 0
        
        return rows[0].get('clicks', 0), rows[0].get('impressions', 0)

async def process_site(gsc, site_url, executor):
    """Handles the 3 time-range fetches for a single site."""
    loop = asyncio.get_event_loop()
    ranges = [7, 30, 90]
    results = []
    
    try:
        for days in ranges:
            # Wrap the blocking API call in the executor
            clicks, impressions = await loop.run_in_executor(
                executor, gsc.query_gsc, site_url, days
            )
            results.append([site_url, f"Last {days} Days", clicks, impressions])
        return results
    except Exception as e:
        logger.error(f"Failed to process {site_url}: {e}")
        return []

async def main():
    gsc = GSCManager(SERVICE_ACCOUNT_FILE)
    sites = gsc.fetch_all_sites()
    
    if not sites:
        logger.warning("No sites found in Search Console.")
        return

    logger.info(f"Processing {len(sites)} sites...")
    
    all_rows = []
    # Using a ThreadPool to handle blocking I/O (Google Discovery API is not natively async)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        tasks = [process_site(gsc, site, executor) for site in sites]
        
        # Gather results with basic rate limit protection by chunking if necessary
        # For 10k domains, we process in chunks to avoid memory bloat
        chunk_size = 100 
        for i in range(0, len(tasks), chunk_size):
            batch_results = await asyncio.gather(*tasks[i:i+chunk_size])
            for site_result in batch_results:
                all_rows.extend(site_result)
            logger.info(f"Progress: {min(i + chunk_size, len(sites))}/{len(sites)} sites fetched.")

    # Write to Google Sheets
    if all_rows:
        try:
            worksheet = gsc.get_sheet(SPREADSHEET_ID, SHEET_NAME)
            logger.info("Clearing old data and writing new results...")
            
            header = ["domain", "range", "clicks", "impressions"]
            # Batch update for performance
            worksheet.clear()
            worksheet.update('A1', [header] + all_rows)
            logger.info(f"Successfully wrote {len(all_rows)} rows to Google Sheets.")
        except Exception as e:
            logger.error(f"Error writing to Sheets: {e}")

if __name__ == "__main__":
    asyncio.run(main())
