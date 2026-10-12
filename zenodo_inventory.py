"""
Zenodo marine-biology dataset inventory (EMODnet Biology WP4, Task 7.2).

Scope, per D4.3.3 running notes: the inventory must contain MARINE BIOLOGY datasets,
i.e. datasets holding species occurrence / distribution data or habitat / biotope data.

Rev. 3 Sep 2026 - precision fix. The previous run produced a raw keyword hit list that
included terrestrial datasets (Amazonian trees, Atlantic Forest, tundra rodents, soil DNA,
lab experiments, model output). Four mechanisms were added:

  1. Marine-specific search vocabulary instead of ambiguous single words
     ("Angiosperms" -> seagrasses/Zostera/Posidonia..., "Atlantic" -> Atlantic Ocean/
      North Atlantic..., "Arctic" -> Arctic Ocean/Barents Sea/Svalbard...).
     Also fixes the "Mediteranean Sea" typo, which returned 0 hits - the whole
     Mediterranean region was missing from the previous inventory.
  2. A mandatory three-way combination in every query: taxon AND region AND marine term.
  3. Negative keywords: hard exclusions (auto) and caution terms (-> Manual review).
  4. Post-filter over title + description + keywords ONLY (never over author affiliation),
     so "Arctic" in an author's affiliation no longer qualifies a record.

Every rejected record is kept in the "Excluded" sheet with the reason, so nothing is
silently lost and the filtering can be audited / appealed.
"""

import argparse
import requests
import pandas as pd
import re
import time
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configurare
# ---------------------------------------------------------------------------
# Tokenul se citeste din variabila de mediu ZENODO_TOKEN (nu se pune in cod / pe GitHub).
ACCESS_TOKEN = os.environ.get('ZENODO_TOKEN', '')
EXCEL_OUTPUT = 'Dataset_Inventory_Zenodo_Marine.xlsx'
JSON_OUTPUT = 'data.json'

# ---------------------------------------------------------------------------
# Criterii de cautare - vocabular marin
# Cheia = eticheta canonica scrisa in raport; valorile = sinonimele trimise la Zenodo.
# ---------------------------------------------------------------------------
TAXA_LIST = {
    'Angiosperms': [
        'marine angiosperms', 'marine angiosperm', 'seagrass', 'seagrasses',
        'seagrass meadow', 'eelgrass', 'Zostera', 'Posidonia', 'Cymodocea',
        'Halophila', 'Ruppia', 'Thalassia', 'saltmarsh', 'salt marsh',
    ],
    'Birds': [
        'seabird', 'seabirds', 'marine birds', 'waterbirds', 'shorebirds',
        'coastal birds', 'Alcidae', 'Laridae', 'Procellariiformes',
    ],
    'Benthos': [
        'benthos', 'benthic', 'macrobenthos', 'meiobenthos', 'zoobenthos',
        'macrofauna', 'infauna', 'epifauna', 'benthic habitat', 'biotope',
    ],
    'Macroalgae': [
        'macroalgae', 'macroalgal', 'seaweed', 'seaweeds', 'kelp',
        'Fucus', 'Laminaria', 'Cystoseira', 'Ulva', 'Rhodophyta', 'Phaeophyceae',
    ],
    'Mammals': [
        'marine mammals', 'marine mammal', 'cetacean', 'cetaceans', 'whale',
        'dolphin', 'porpoise', 'pinniped', 'seal', 'Phocidae', 'Cetacea',
    ],
    'Phytoplankton': [
        'phytoplankton', 'microphytoplankton', 'diatom', 'diatoms',
        'dinoflagellate', 'dinoflagellates', 'coccolithophore', 'microalgae',
        'harmful algal bloom', 'chlorophyll a',
    ],
    'Reptiles': [
        'sea turtle', 'sea turtles', 'marine turtle', 'marine turtles',
        'marine reptiles', 'Caretta', 'Chelonia mydas', 'Dermochelys',
    ],
    'Zooplankton': [
        'zooplankton', 'mesozooplankton', 'copepod', 'copepods',
        'ichthyoplankton', 'jellyfish', 'gelatinous zooplankton',
        'Calanus', 'Noctiluca', 'Mnemiopsis',
    ],
    'Virus': [
        'marine virus', 'marine viruses', 'virioplankton', 'bacteriophage',
        'marine virome', 'viral abundance',
    ],
}

GEO_LIST = {
    'Arctic': [
        'Arctic Ocean', 'Arctic marine waters', 'Arctic seas', 'Barents Sea',
        'Greenland Sea', 'Norwegian Sea', 'Fram Strait', 'Svalbard',
        'Chukchi Sea', 'Kara Sea', 'Beaufort Sea', 'White Sea',
    ],
    'Atlantic': [
        'Atlantic Ocean', 'North Atlantic', 'Northeast Atlantic',
        'North-East Atlantic', 'NE Atlantic', 'Bay of Biscay', 'Celtic Sea',
        'Irish Sea', 'Iberian coast', 'Macaronesia', 'Azores', 'Bay of Bourgneuf',
    ],
    'Baltic Sea': [
        'Baltic Sea', 'Gulf of Bothnia', 'Gulf of Finland', 'Gulf of Riga',
        'Kattegat', 'Skagerrak', 'Bothnian Bay',
    ],
    'Black Sea': [
        'Black Sea', 'Sea of Azov', 'Sea of Marmara', 'Bosphorus',
    ],
    'Mediterranean Sea': [
        # NOTA: rularea anterioara folosea "Mediteranean Sea" (typo) -> 0 rezultate.
        'Mediterranean Sea', 'Adriatic Sea', 'Aegean Sea', 'Ionian Sea',
        'Tyrrhenian Sea', 'Ligurian Sea', 'Alboran Sea', 'Gulf of Lions',
        'Levantine Sea', 'Balearic Sea',
    ],
    'North Sea': [
        'North Sea', 'Wadden Sea', 'German Bight', 'English Channel',
        'Southern Bight', 'Dogger Bank',
    ],
}

# Al treilea grup obligatoriu din query: contextul marin.
# Lista completa se foloseste la filtrarea post-cautare.
MARINE_TERMS = [
    'marine', 'sea', 'ocean', 'oceanic', 'coastal', 'seawater', 'sea water',
    'benthic', 'pelagic', 'estuarine', 'estuary', 'intertidal', 'subtidal',
    'offshore', 'water column', 'continental shelf', 'fjord', 'lagoon',
    'plankton', 'littoral', 'brackish', 'seabed', 'seafloor',
]

# Subset compact trimis in query. Zenodo (Elasticsearch) respinge cu HTTP 500
# interogarile care depasesc ~1000 de clauze booleene, iar numarul de clauze este
# produsul dimensiunilor grupurilor OR. Restul termenilor marini se aplica la
# filtrarea locala, deci nu se pierde nimic.
MARINE_QUERY_TERMS = [
    'marine', 'sea', 'ocean', 'coastal', 'benthic', 'pelagic', 'estuarine', 'plankton',
]

# Buget de clauze per interogare: len(taxa) * len(geo) * len(marine) <= MAX_CLAUSES.
MAX_CLAUSES = 640

# Dovada ca setul contine date biologice: aparitii/distributie specii sau habitate.
BIO_EVIDENCE_TERMS = [
    'occurrence', 'occurrences', 'species distribution', 'distribution',
    'abundance', 'biomass', 'density', 'presence', 'presence-absence',
    'community composition', 'assemblage', 'biodiversity', 'species richness',
    'taxa', 'taxon', 'taxonomic', 'species list', 'checklist', 'inventory',
    'habitat', 'habitats', 'biotope', 'biotopes', 'monitoring', 'survey',
    'census', 'counts', 'sampling', 'observation', 'observations', 'edna',
    'biological', 'population', 'fauna', 'flora', 'benthic community',
    'records', 'sightings', 'specimens', 'species composition', 'diversity',
    'community', 'stranding', 'bycatch', 'trawl',
]

# Excludere automata - termeni clar non-marini / non-observationali.
HARD_NEGATIVES = [
    'atlantic forest', 'amazonian', 'amazon rainforest', 'rainforest',
    'tree growth', 'vascular plants', 'soil dna',
    'laboratory experiment', 'transcriptome',
    'model output', 'simulation', 'palaeoclimate', 'paleoclimate',
]

# Nu se exclud automat - marcheaza recordul pentru "Manual review".
# 'terrestrial', 'phylogenetic' si 'genome' au fost mutate aici din HARD_NEGATIVES
# (3 sep 2026): apar frecvent si in seturi marine legitime ("marine and terrestrial
# transects", studii filogenetice pe specii marine, eDNA / metabarcoding cu genomuri
# de referinta), deci se verifica manual, nu se sterg.
CAUTION_TERMS = [
    'freshwater', 'lake', 'lakes', 'river', 'rivers', 'tundra', 'forest',
    'supplementary material', 'source code', 'code repository', 'software',
    'agriculture', 'agricultural', 'soil', 'greenhouse',
    'terrestrial', 'phylogenetic', 'genome',
]

STATUS_INCLUDED = 'Included'
STATUS_REVIEW = 'Manual review'
STATUS_EXCLUDED = 'Excluded'


# ---------------------------------------------------------------------------
# Utilitare
# ---------------------------------------------------------------------------
def get_robust_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[502, 503, 504, 429],
        raise_on_status=False
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session


def or_group(terms):
    """Construieste un grup OR de fraze exacte pentru query-ul Zenodo."""
    return '(' + ' OR '.join(f'"{t}"' for t in terms) + ')'


def find_terms(text, terms):
    """Returneaza termenii gasiti in text, cu potrivire pe limita de cuvant."""
    found = []
    for t in terms:
        pattern = r'(?<!\w)' + re.escape(t.lower()) + r'(?!\w)'
        if re.search(pattern, text):
            found.append(t)
    return found


def extract_years(text, title="", keywords=[], publication_date=""):
    """Extrage intervalul temporal (ani) din text, titlu, cuvinte cheie si data publicarii."""
    pub_year = publication_date[:4] if publication_date and re.match(r'^\d{4}', publication_date) else ""

    search_text = f"{title} {text} {' '.join(keywords) if isinstance(keywords, list) else ''}"
    if not search_text:
        return pub_year if pub_year else "N/A"

    years = re.findall(r'\b(18\d{2}|19\d{2}|20\d{2})\b', search_text)

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
        if len(sorted_years) > 1:
            return f"{sorted_years[0]} - {sorted_years[-1]}"
        return sorted_years[0]
    return "N/A"


def extract_email(text):
    """Extrage prima adresa de email gasita in text."""
    if not text:
        return "N/A"
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return emails[0] if emails else "N/A"


def categorize_type_of_data(text):
    """Categorizeaza tipul de date pe baza cuvintelor cheie din abstract/descriere."""
    if not text:
        return "N/A"
    text_lower = text.lower()
    categories = []

    if any(k in text_lower for k in ['human observation', 'observation', 'visual survey', 'sampling', 'abundance', 'count', 'survey']):
        categories.append('human observation')

    if any(k in text_lower for k in ['imaging', 'image', 'photo', 'video', 'camera', 'photography', 'loki', 'microscopy']):
        categories.append('imaging')

    if any(k in text_lower for k in ['tracking', 'telemetry', 'tagging', 'acoustic', 'displacement', 'movement', 'gps', 'sensor']):
        categories.append('tracking')

    if any(k in text_lower for k in ['edna', 'environmental dna', 'metabarcoding', 'sequencing', 'genomic', 'dna', 'pcr']):
        categories.append('eDNA')

    return ", ".join(categories) if categories else "N/A"


# ---------------------------------------------------------------------------
# Cautare
# ---------------------------------------------------------------------------
def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def build_queries(taxa_terms, geo_terms):
    """
    Combinatie obligatorie: taxon AND regiune AND context marin.

    Listele de sinonime sunt fragmentate astfel incat produsul dimensiunilor sa
    ramana sub bugetul de clauze booleene al Zenodo; rezultatele fragmentelor se
    reunesc dupa ID-ul recordului.
    """
    marine = or_group(MARINE_QUERY_TERMS)
    budget = MAX_CLAUSES // max(1, len(MARINE_QUERY_TERMS))

    geo_size = min(len(geo_terms), 10)
    taxa_size = max(1, budget // geo_size)

    queries = []
    for t_chunk in chunks(taxa_terms, taxa_size):
        for g_chunk in chunks(geo_terms, geo_size):
            queries.append(f'{or_group(t_chunk)} AND {or_group(g_chunk)} AND {marine}')
    return queries


def fetch_zenodo_datasets(query, session):
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
                    **({'access_token': ACCESS_TOKEN} if ACCESS_TOKEN else {}),
                },
                timeout=60
            )

            if response.status_code == 429:
                print("   Rate limit reached. Sleeping...")
                time.sleep(10)
                continue

            if response.status_code != 200:
                print(f"   Error {response.status_code}: {response.text[:200]}")
                break

            data = response.json()
            hits = data.get('hits', {}).get('hits', [])
            if not hits:
                break

            all_records.extend(hits)

            links = data.get('links', {})
            if 'next' not in links or page >= 10:  # Limita de siguranta per query
                break
            page += 1
            time.sleep(1)
        except Exception as e:
            print(f"   Connection error: {e}")
            break

    return all_records


# ---------------------------------------------------------------------------
# Filtrare relevanta
# ---------------------------------------------------------------------------
def screen_record(title, clean_desc, keywords, taxa_label, geo_label):
    """
    Decide daca recordul intra in inventar.

    IMPORTANT: se analizeaza DOAR titlul, descrierea si cuvintele cheie -
    niciodata afilierea autorilor, care genera fals-pozitive de tip
    "Arctic University of Norway".
    """
    kw_text = ' '.join(keywords) if isinstance(keywords, list) else str(keywords or '')
    strong = f"{title} {kw_text}".lower()          # titlu + keywords = semnal puternic
    full = f"{title} {kw_text} {clean_desc}".lower()

    notes = []

    # 1. Excluderi automate
    hard = find_terms(full, HARD_NEGATIVES)
    if hard:
        return STATUS_EXCLUDED, f"Negative keyword: {', '.join(hard)}"

    # 2. Taxonul cerut trebuie sa apara efectiv in text
    taxa_hits = find_terms(full, TAXA_LIST[taxa_label])
    if not taxa_hits:
        return STATUS_EXCLUDED, f"Taxon '{taxa_label}' absent din titlu/descriere/keywords"

    # 3. Regiunea ceruta trebuie sa apara efectiv in text
    geo_hits = find_terms(full, GEO_LIST[geo_label])
    if not geo_hits:
        return STATUS_EXCLUDED, f"Regiunea '{geo_label}' absenta din titlu/descriere/keywords"

    # 4. Context marin
    marine_hits = find_terms(full, MARINE_TERMS)
    if not marine_hits:
        return STATUS_EXCLUDED, "Fara context marin in titlu/descriere/keywords"

    # 5. Continut biologic (aparitii specii / habitate)
    bio_hits = find_terms(full, BIO_EVIDENCE_TERMS)
    if not bio_hits:
        return STATUS_REVIEW, "Marin, dar fara dovada clara de date de aparitii specii / habitate"

    evidence = (f"taxon: {', '.join(taxa_hits[:3])} | regiune: {', '.join(geo_hits[:3])} | "
                f"marin: {', '.join(marine_hits[:3])} | biologic: {', '.join(bio_hits[:3])}")

    # 6. Semnal mai slab: taxonul sau regiunea apar doar in descriere, nu si in titlu
    #    ori in cuvintele cheie. Titlurile Zenodo sunt adesea scurte ("Data from: ...")
    #    si multe recorduri nu au deloc keywords, deci acesta este doar un indiciu de
    #    provenienta notat in raport - NU un motiv de verificare manuala.
    weak = []
    if not find_terms(strong, TAXA_LIST[taxa_label]):
        weak.append('taxon')
    if not find_terms(strong, GEO_LIST[geo_label]):
        weak.append('regiune')
    if weak:
        evidence += f" | doar in descriere: {', '.join(weak)}"

    # 7. Termeni de precautie -> nu se exclud, se trimit la verificare manuala
    caution = find_terms(full, CAUTION_TERMS)
    if caution:
        notes.append(f"Caution: {', '.join(caution)}")

    if notes:
        return STATUS_REVIEW, '; '.join(notes) + ' || ' + evidence
    return STATUS_INCLUDED, evidence


# ---------------------------------------------------------------------------
# Procesare
# ---------------------------------------------------------------------------
def process_records(records, taxa, geo):
    processed_data = []

    for record in records:
        metadata = record.get('metadata', {})
        description = metadata.get('description', '')
        clean_desc = re.sub('<[^<]+?>', ' ', description)
        clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()

        creators = metadata.get('creators', [])
        provider = "N/A"
        owner = "N/A"
        if creators:
            first_creator = creators[0]
            provider = first_creator.get('name', 'N/A')
            if first_creator.get('affiliation'):
                provider += f" ({first_creator.get('affiliation')})"

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

        status, notes = screen_record(title, clean_desc, keywords, taxa, geo)

        temporal = extract_years(clean_desc, title=title, keywords=keywords, publication_date=pub_date)
        data_type = categorize_type_of_data(clean_desc)

        access_right = metadata.get('access_right', 'open')
        is_open = "Yes" if access_right == 'open' else "No"

        doi = metadata.get('doi', 'N/A')
        url = record.get('links', {}).get('html', f"https://zenodo.org/record/{record.get('id')}")
        metadata_url = record.get('links', {}).get('self', 'N/A')
        email = extract_email(clean_desc)
        license_info = (metadata.get('license') or {}).get('id', 'N/A')

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
            'File type': file_types,
            'Status': status,
            'Review notes': notes,
        })

    return processed_data


def merge_into(all_results, res):
    """Deduplicare dupa titlu + provider, cu consolidarea taxa / regiuni / formate."""
    key = f"{res['Data title']}_{res['Provider']}"
    if key not in all_results:
        all_results[key] = res
        return

    existing = all_results[key]

    if res['Taxa covered'] not in existing['Taxa covered']:
        existing['Taxa covered'] += f", {res['Taxa covered']}"
    if res['Geographic coverage'] not in existing['Geographic coverage']:
        existing['Geographic coverage'] += f", {res['Geographic coverage']}"

    if res['File type'] != "N/A":
        combined = set(existing['File type'].split(", ")) | set(res['File type'].split(", "))
        combined.discard("N/A")
        existing['File type'] = ", ".join(sorted(combined)) if combined else "N/A"

    # Statusul cel mai favorabil castiga: daca recordul se califica pe o combinatie
    # taxon/regiune, el apartine inventarului.
    rank = {STATUS_INCLUDED: 2, STATUS_REVIEW: 1, STATUS_EXCLUDED: 0}
    if rank[res['Status']] > rank[existing['Status']]:
        existing['Status'] = res['Status']
        existing['Review notes'] = res['Review notes']


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    kept = {}       # Included + Manual review
    dropped = {}    # Excluded
    search_log = []

    session = get_robust_session()
    total_queries = len(TAXA_LIST) * len(GEO_LIST)
    n = 0

    for taxa, taxa_terms in TAXA_LIST.items():
        for geo, geo_terms in GEO_LIST.items():
            n += 1
            queries = build_queries(taxa_terms, geo_terms)
            print(f"[{n}/{total_queries}] {taxa} / {geo}  ({len(queries)} sub-queries)")

            # Fragmentele de query se reunesc dupa ID-ul Zenodo al recordului.
            by_id = {}
            for q in queries:
                for rec in fetch_zenodo_datasets(q, session):
                    by_id[rec.get('id')] = rec
                time.sleep(0.5)
            records = list(by_id.values())

            results = process_records(records, taxa, geo)

            counts = {STATUS_INCLUDED: 0, STATUS_REVIEW: 0, STATUS_EXCLUDED: 0}
            for res in results:
                counts[res['Status']] += 1
                if res['Status'] == STATUS_EXCLUDED:
                    merge_into(dropped, res)
                else:
                    merge_into(kept, res)

            print(f"   raw={len(records)}  included={counts[STATUS_INCLUDED]}  "
                  f"review={counts[STATUS_REVIEW]}  excluded={counts[STATUS_EXCLUDED]}")

            search_log.append({
                'Taxa covered': taxa,
                'Geographic coverage': geo,
                'Query': ' ;; '.join(queries),
                'Raw hits': len(records),
                'Included': counts[STATUS_INCLUDED],
                'Manual review': counts[STATUS_REVIEW],
                'Excluded': counts[STATUS_EXCLUDED],
            })
            time.sleep(1)

    # Un record ajuns in "kept" pe o alta combinatie nu mai apare in "Excluded".
    for key in list(dropped):
        if key in kept:
            del dropped[key]

    final_list = list(kept.values())
    included = [r for r in final_list if r['Status'] == STATUS_INCLUDED]
    review = [r for r in final_list if r['Status'] == STATUS_REVIEW]
    excluded = list(dropped.values())

    print()
    print(f"Unique records in inventory : {len(final_list)}")
    print(f"  Included                  : {len(included)}")
    print(f"  Manual review             : {len(review)}")
    print(f"Excluded (audit trail)      : {len(excluded)}")

    if not final_list and not excluded:
        print("No results found across all criteria.")
        return

    cols = ['Provider', 'Data owner', 'Data title', 'Taxa covered', 'Type of data',
            'Temporal coverage', 'Geographic coverage', 'Available in open repositories?',
            'Data URL/DOI', 'Metadata URL', 'Email of data provider', 'Data license',
            'Access conditions', 'File type', 'Status', 'Review notes']

    def frame(rows):
        return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

    with pd.ExcelWriter(EXCEL_OUTPUT, engine='openpyxl') as writer:
        frame(included).to_excel(writer, sheet_name='Inventory', index=False)
        frame(review).to_excel(writer, sheet_name='Manual review', index=False)
        frame(excluded).to_excel(writer, sheet_name='Excluded', index=False)
        pd.DataFrame(search_log).to_excel(writer, sheet_name='Search log', index=False)
    print(f"Results saved to {EXCEL_OUTPUT}")

    # JSON pentru dashboard: inventarul + cazurile de verificat, marcate prin 'Status'.
    try:
        if os.path.dirname(JSON_OUTPUT):
            os.makedirs(os.path.dirname(JSON_OUTPUT), exist_ok=True)
        frame(included + review).to_json(JSON_OUTPUT, orient='records', indent=4)
        print(f"Results saved to {JSON_OUTPUT}")
    except Exception as e:
        print(f"Could not save JSON: {e}")


def parse_args():
    parser = argparse.ArgumentParser(description='Zenodo marine-biology dataset inventory')
    parser.add_argument('--excel', default=EXCEL_OUTPUT, help='output Excel file')
    parser.add_argument('--json', default=JSON_OUTPUT, help='output JSON file (web dashboard)')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    EXCEL_OUTPUT, JSON_OUTPUT = args.excel, args.json
    if not ACCESS_TOKEN:
        print("WARNING: ZENODO_TOKEN not set - running anonymously (lower rate limits).")
    main()
