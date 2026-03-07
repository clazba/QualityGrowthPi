import requests
import json
import time
from getpass import getpass

# --- 1. Ingestion: SEC EDGAR ---
def fetch_sec_tickers(user_agent):
    """Fetches active US equities from the SEC."""
    print("\n[+] Fetching active tickers from SEC EDGAR...")
    url = "https://www.sec.gov/files/company_tickers_exchange.json"
    headers = {"User-Agent": user_agent}
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    data = response.json()
    # The SEC returns a dict with 'fields' and 'data'. 
    # 'data' is a list of lists: [CIK, Name, Ticker, Exchange]
    tickers = []
    for item in data.get("data", []):
        tickers.append({
            "cik": str(item[0]).zfill(10), # Standardize CIK to 10 digits
            "name": item[1],
            "ticker": item[2],
            "exchange": item[3]
        })
    
    print(f"[+] Retrieved {len(tickers)} active tickers from SEC.")
    return tickers

# --- 2. Mapping: OpenFIGI ---
def map_tickers_to_figi(tickers, api_key):
    """Maps tickers to permanent FIGIs using batch processing."""
    print("[+] Mapping tickers to OpenFIGI...")
    url = "https://api.openfigi.com/v3/mapping"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
        
    mapped_data = []
    
    # OpenFIGI requires chunking requests (max 100 per POST)
    chunk_size = 100
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        
        # Build the payload for this chunk
        payload = [{"idType": "TICKER", "idValue": t["ticker"], "exchCode": "US"} for t in chunk]
        
        response = requests.post(url, headers=headers, json=payload)
        
        # Handle Rate Limits (HTTP 429)
        if response.status_code == 429:
            print("[-] Rate limit hit. Sleeping for 60 seconds...")
            time.sleep(60)
            # A production script would retry the failed chunk here
            continue 
            
        response.raise_for_status()
        results = response.json()
        
        # Merge the SEC data with the OpenFIGI response
        for sec_record, figi_result in zip(chunk, results):
            if "data" in figi_result and len(figi_result["data"]) > 0:
                # Take the primary match
                match = figi_result["data"][0]
                sec_record["composite_figi"] = match.get("compositeFIGI")
                sec_record["security_type"] = match.get("securityType")
            else:
                sec_record["composite_figi"] = None
                
            mapped_data.append(sec_record)
            
        # Be polite to the API if running without a key
        if not api_key:
            time.sleep(1)
            
    return mapped_data

# --- 3. Validation: Regression Testing ---
def validate_mappings(mapped_data):
    """Runs basic regression tests to catch upstream anomalies."""
    print("\n[+] Running regression validation on mappings...")
    
    missing_figis = [record for record in mapped_data if not record.get("composite_figi")]
    duplicates = {}
    
    for record in mapped_data:
        figi = record.get("composite_figi")
        if figi:
            duplicates[figi] = duplicates.get(figi, 0) + 1
            
    duplicate_figis = {k: v for k, v in duplicates.items() if v > 1}

    print(f"    -> Total records processed: {len(mapped_data)}")
    print(f"    -> Records failing FIGI mapping: {len(missing_figis)}")
    if duplicate_figis:
        print(f"    -> WARNING: Found {len(duplicate_figis)} FIGIs mapped to multiple active tickers.")
    else:
        print("    -> PASS: No duplicate FIGI collisions detected.")
        
    return missing_figis

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Security Master Builder ---")
    
    # Securely prompt user for credentials
    user_agent = input("Enter your SEC User-Agent (Format: 'AppName YourEmail@domain.com'): ").strip()
    if not user_agent:
        raise ValueError("SEC User-Agent is strictly required to avoid IP bans.")
        
    api_key = getpass("Enter your OpenFIGI API Key (or press Enter to run without one): ").strip()
    
    try:
        sec_tickers = fetch_sec_tickers(user_agent)
        
        # To test quickly, slice the list: sec_tickers[:250]
        mapped_results = map_tickers_to_figi(sec_tickers, api_key)
        
        unmapped = validate_mappings(mapped_results)
        
        # Save output to a local JSON file
        output_file = "security_master_snapshot.json"
        with open(output_file, "w") as f:
            json.dump(mapped_results, f, indent=4)
            
        print(f"\n[+] Success. Data saved to {output_file}")
        
    except requests.exceptions.RequestException as e:
        print(f"\n[-] HTTP Error occurred: {e}")
    except Exception as e:
        print(f"\n[-] Pipeline failed: {e}")
