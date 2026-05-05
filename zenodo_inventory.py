import requests
import pandas as pd
import re
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os

# Configuration
# Replace with your Zenodo Access Token
# You can get one from: https://zenodo.org/account/settings/applications/tokens/new/
ACCESS_TOKEN = 'YOUR_ZENODO_ACCESS_TOKEN'
EXCEL_OUTPUT = 'Dataset_Inventory_Zenodo.xlsx'
JSON_OUTPUT = 'data.json'

# Criteria lists for search
TAXA_LIST = ['Angiosperms', 'Birds', 'Benthos', 'Macroalgae', 'Mammals', 'Phytoplankton', 'Reptiles', 'Zooplankton', 'Virus']
GEO_LIST = ['Arctic', 'Atlantic', 'Baltic Sea', 'Black Sea', 'Mediterranean Sea', 'North Sea']

def get_robust_session():
    """Returns a requests Session with retry logic for handling server timeouts/errors."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[502, 503, 504, 429],
        raise_on_status=False
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def extract_years(text, title="", keywords=[], publication_date=""):
    """Extracts the temporal range (years) from text, title, keywords, and publication date."""
    # Use publication date as a secondary source
    pub_year = publication_date[:4] if publication_date and re.match(r'^\d{4}', publication_date) else ""
    
    search_text = f"{title} {text} {' '.join(keywords) if isinstance(keywords, list) else ''}"
    if not search_text:
        return pub_year if pub_year else "N/A"
    
    # Find all years in the range 1800-2099
    years = re.findall(r'\b(18\d{2}|19\d{2}|20\d{2})\b', search_text)
    
    # Search for range patterns: "2010-2015", "2010 to 2015", "2010/2015"
    ranges = re.findall(r'\b(1[89]\d{2}|20\d{2})[-\s/]+(?:to|until|and|thru|through)[-\s/]+(1[89]\d{2}|20\d{2})\b', search_text, re.IGNORECASE)
    ranges += re.findall(r'\b(1[89]\d{2}|20\d{2})[-\s/]+(1[89]\d{2}|20\d{2})\b', search_text)
    
    all_years = set(years)
    for r in ranges:
        all_years.add(r[0])
        all_years.add(r[1])
    
    if pub_year:
        all_years.add(pub_year)
        
    if all_years:
        sorted_years = sorted(list(all_years))
        # Keep it flexible but can filter unrealistic future years if needed
        if len(sorted_years) > 1:
            return f"{sorted_years[0]} - {sorted_years[-1]}"
        return sorted_years[0]
    return "N/A"

def extract_email(text):
    """Extracts the first email address found in the text."""
    if not text:
        return "N/A"
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return emails[0] if emails else "N/A"

def categorize_type_of_data(text):
    """Categorizes the type of data based on keywords in the abstract/description."""
    if not text:
        return "N/A"
    text_lower = text.lower()
    categories = []
    
    # human observation
    if any(k in text_lower for k in ['human observation', 'observation', 'visual survey', 'sampling', 'abundance', 'count', 'survey']):
        categories.append('human observation')
    
    # imaging
    if any(k in text_lower for k in ['imaging', 'image', 'photo', 'video', 'camera', 'photography', 'loki', 'microscopy']):
        categories.append('imaging')
    
    # tracking
    if any(k in text_lower for k in ['tracking', 'telemetry', 'tagging', 'acoustic', 'displacement', 'movement', 'gps', 'sensor']):
        categories.append('tracking')
    
    # eDNA
    if any(k in text_lower for k in ['edna', 'environmental dna', 'metabarcoding', 'sequencing', 'genomic', 'dna', 'pcr']):
        categories.append('eDNA')
    
    return ", ".join(categories) if categories else "N/A"

def fetch_zenodo_datasets(taxa, geo):
    """Fetches records from Zenodo based on taxa and geographic region."""
    query = f'("{taxa}") AND ("{geo}")'
    print(f"Searching Zenodo for: {query}")
    
    session = get_robust_session()
    all_records = []
    page = 1
    size = 100
    
    while True:
        try:
            response = session.get(
                'https://zenodo.org/api/records',
                params={
                    'q': query,
                    'type': 'dataset',
                    'size': size,
                    'page': page,
                    'access_token': ACCESS_TOKEN if ACCESS_TOKEN != 'YOUR_ZENODO_ACCESS_TOKEN' else None
                },
                timeout=30
            )
            
            if response.status_code == 429:
                print("Rate limit reached. Sleeping...")
                time.sleep(10)
                continue

            if response.status_code != 200:
                print(f"Error {response.status_code}: {response.text}")
                break
                
            data = response.json()
            hits = data.get('hits', {}).get('hits', [])
            if not hits:
                break
                
            all_records.extend(hits)
            
            links = data.get('links', {})
            if 'next' not in links or page >= 10: # Safety limit per query
                break
            page += 1
            time.sleep(1)
        except Exception as e:
            print(f"Connection error: {e}")
            break
        
    return all_records

def process_records(records, taxa, geo):
    """Processes Zenodo records and extracts relevant metadata."""
    processed_data = []
    
    for record in records:
        metadata = record.get('metadata', {})
        description = metadata.get('description', '')
        # Clean HTML tags from description
        clean_desc = re.sub('<[^<]+?>', '', description)
        
        creators = metadata.get('creators', [])
        provider = "N/A"
        owner = "N/A"
        if creators:
            # Provider: contact person/organisation (first creator)
            first_creator = creators[0]
            provider = first_creator.get('name', 'N/A')
            if first_creator.get('affiliation'):
                provider += f" ({first_creator.get('affiliation')})"
            
            # Data owner: organisation + person
            owner_list = []
            for c in creators:
                c_info = c.get('name', 'N/A')
                if c.get('affiliation'):
                    c_info += f" [{c.get('affiliation')}]"
                owner_list.append(c_info)
            owner = "; ".join(owner_list)

        title = metadata.get('title', 'N/A')
        keywords = metadata.get('keywords', [])
        pub_date = metadata.get('publication_date', '')
        
        # Temporal coverage: year range
        temporal = extract_years(clean_desc, title=title, keywords=keywords, publication_date=pub_date)
        
        # Type of data: extracted from abstract
        data_type = categorize_type_of_data(clean_desc)
        
        # Open repositories?
        access_right = metadata.get('access_right', 'open')
        is_open = "Yes" if access_right == 'open' else "No"
        
        # URL/DOI
        doi = metadata.get('doi', 'N/A')
        url = record.get('links', {}).get('html', f"https://zenodo.org/record/{record.get('id')}")
        
        # Metadata URL
        metadata_url = record.get('links', {}).get('self', 'N/A')
        
        # Email
        email = extract_email(clean_desc)
        
        # License
        license_info = metadata.get('license', {}).get('id', 'N/A')
        
        # File types
        files = record.get('files', [])
        extensions = set()
        for f in files:
            key = f.get('key', '')
            if '.' in key:
                ext = key.split('.')[-1].lower()
                extensions.add(f".{ext}")
        file_types = ", ".join(sorted(list(extensions))) if extensions else "N/A"
        
        processed_data.append({
            'Provider': provider,
            'Data owner': owner,
            'Data title': title,
            'Taxa covered': taxa,
            'Type of data': data_type,
            'Temporal coverage': temporal,
            'Geographic coverage': geo,
            'Available in open repositories?': is_open,
            'Data URL/DOI': doi if doi != "N/A" else url,
            'Metadata URL': metadata_url,
            'Email of data provider': email,
            'Data license': license_info,
            'Access conditions': access_right.capitalize(),
            'File type': file_types
        })
        
    return processed_data

def main():
    all_results = {} # Use dictionary for deduplication by Title + Provider
    
    for taxa in TAXA_LIST:
        for geo in GEO_LIST:
            records = fetch_zenodo_datasets(taxa, geo)
            print(f"Found {len(records)} records for {taxa} in {geo}.")
            
            results = process_records(records, taxa, geo)
            
            for res in results:
                # Unique key based on title and provider
                key = f"{res['Data title']}_{res['Provider']}"
                if key not in all_results:
                    all_results[key] = res
                else:
                    # If record exists, merge taxa and geographic coverage
                    if res['Taxa covered'] not in all_results[key]['Taxa covered']:
                        all_results[key]['Taxa covered'] += f", {res['Taxa covered']}"
                    if res['Geographic coverage'] not in all_results[key]['Geographic coverage']:
                        all_results[key]['Geographic coverage'] += f", {res['Geographic coverage']}"
                    # Merge File types
                    if res['File type'] != "N/A":
                        existing_types = set(all_results[key]['File type'].split(", "))
                        new_types = set(res['File type'].split(", "))
                        combined_types = existing_types.union(new_types)
                        if "N/A" in combined_types: combined_types.remove("N/A")
                        all_results[key]['File type'] = ", ".join(sorted(list(combined_types))) if combined_types else "N/A"

    final_list = list(all_results.values())
    print(f"Total unique records collected: {len(final_list)}")
    
    if final_list:
        df = pd.DataFrame(final_list)
        # Save to Excel
        df.to_excel(EXCEL_OUTPUT, index=False)
        print(f"Results saved to {EXCEL_OUTPUT}")
        
        # Save to JSON for web dashboard
        try:
            df.to_json(JSON_OUTPUT, orient='records', indent=4)
            print(f"Results saved to {JSON_OUTPUT}")
        except Exception as e:
            print(f"Could not save JSON: {e}")
    else:
        print("No results found across all criteria.")

if __name__ == "__main__":
    main()
