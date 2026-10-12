# Zenodo Marine Inventory — Task 1

Automated inventory of **marine biology datasets on Zenodo** (species occurrence / distribution
data and habitat / biotope data) that could be mobilised into EMODnet Biology
(EMODnet Biology WP4, Task 7.2).

This is **Task 1** of the *Zenodo Inventory* project:

| Task | Repository | What it does |
|---|---|---|
| 1. Inventory | **this repo** | Searches Zenodo, filters for marine relevance, writes Excel + JSON |
| 2. Quality Check | [`zenodo_qc`](https://github.com/GeoTuxMan/zenodo_qc) | Checks the discovered datasets against the EMODnet Biology data quality criteria |
| 3. Darwin Core conversion | [`zenodo_dwc_converter`](https://github.com/GeoTuxMan/zenodo_dwc_converter) | Converts the datasets to Darwin Core Archives (Event / Occurrence / eMoF) |

Results dashboard: <https://sdn2.rmri.ro/zenodo_inventory_new/>

---

## 1. Methodology (rev. 3 September 2026)

The full methodology is in [`METHODOLOGY.txt`](METHODOLOGY.txt). Summary:

### 1.1 Why the method was revised
A first run produced 698 raw keyword hits, including trees, Amazonian plants, tundra rodents,
lakes, lab experiments and model output. Causes: ambiguous search terms ("Angiosperms",
"Atlantic" → *Atlantic Forest*, "Arctic" in author affiliations), no mandatory marine context,
no negative keywords, and a typo ("Mediteranean Sea") that dropped the whole Mediterranean.

### 1.2 Search vocabulary
Each canonical category is searched through marine-specific synonyms:

* **Taxa** — Angiosperms (seagrass, *Zostera*, *Posidonia*…), Birds (seabirds…), Benthos,
  Macroalgae, Mammals (cetaceans, pinnipeds…), Phytoplankton, Reptiles (sea turtles…),
  Zooplankton, Virus (marine viruses, virioplankton…).
* **Regions** — Arctic (Arctic Ocean, Barents Sea, Svalbard…), Atlantic (North Atlantic, Bay of
  Biscay…), Baltic Sea, Black Sea, Mediterranean Sea, North Sea.

### 1.3 Query
For each of the 9 × 6 = 54 (taxon, region) pairs the query is a **mandatory three-way
combination**:

```
(taxon synonyms) AND (region synonyms) AND (marine OR sea OR ocean OR coastal OR benthic OR pelagic OR estuarine OR plankton)
```

restricted to `type=dataset`. Zenodo (Elasticsearch) rejects queries above ~1000 boolean
clauses, so synonym lists are chunked automatically (640-clause budget) and partial results are
merged by Zenodo record ID.

### 1.4 Relevance screening
Screening reads **only title, description and keywords — never author affiliations**, with
word-boundary matching. Every record gets one status:

| Status | Rule |
|---|---|
| **Excluded** | hard negative keyword (*Atlantic Forest, Amazonian, rainforest, tree growth, vascular plants, soil DNA, laboratory experiment, transcriptome, model output, simulation, palaeoclimate*), or taxon / region / marine context missing from the text |
| **Manual review** | caution term (*freshwater, lake, river, tundra, forest, terrestrial, phylogenetic, genome, software…*) or no clear evidence of occurrence / habitat data |
| **Included** | taxon + region + marine context + biological evidence (occurrence, abundance, biomass, distribution, habitat, survey, monitoring…) and no caution term |

The triggering terms are written to the `Review notes` column. Excluded records are kept, with
the reason, in a separate sheet (audit trail).

### 1.5 Deduplication
Records are keyed by *Title + Provider*. Duplicates found by several searches are merged
(taxa, regions and file formats concatenated); the most favourable status wins.

### 1.6 Metadata extracted
Provider, Data owner (creators + affiliations), Title, Taxa covered, Type of data (human
observation / imaging / tracking / eDNA), Temporal coverage (regex over text, fallback to
publication year), Geographic coverage, Open repository (Yes/No), DOI, Metadata URL, Email,
License, Access conditions, File types, Status, Review notes.

---

## 2. Installation

Requirements: Python ≥ 3.9.

```bash
git clone https://github.com/GeoTuxMan/zenodo_inventory.git
cd zenodo_inventory
pip install -r requirements.txt
```

## 3. Usage

1. (Recommended) create a personal Zenodo token at
   <https://zenodo.org/account/settings/applications/tokens/new/> (scope: none needed for
   public search) and export it — **never commit the token**:

   ```bash
   # Linux / macOS
   export ZENODO_TOKEN=your_token
   # Windows PowerShell
   $env:ZENODO_TOKEN = "your_token"
   ```

   Without a token the script still runs, with lower rate limits.

2. Run:

   ```bash
   python zenodo_inventory.py
   # or choose the output locations
   python zenodo_inventory.py --excel Dataset_Inventory_Zenodo_Marine.xlsx \
                              --json  C:/xampp/htdocs/zenodo_inventory_new/data/inventory.json
   ```

   A full run sends ~70 sub-queries and takes about 10–15 minutes.

3. Outputs:

   * **`Dataset_Inventory_Zenodo_Marine.xlsx`** — four sheets: `Inventory` (Included),
     `Manual review`, `Excluded` (with reason), `Search log` (queries sent and hit counts per
     taxon/region pair — D4.3.3 requirement to document the search).
   * **`data.json`** — Included + Manual review records (distinguished by `Status`), consumed by
     the web dashboard and by Task 2 (QC).

### Customising the search
Edit the dictionaries at the top of `zenodo_inventory.py`:
`TAXA_LIST`, `GEO_LIST`, `MARINE_TERMS`, `BIO_EVIDENCE_TERMS`, `HARD_NEGATIVES`, `CAUTION_TERMS`.

## 4. Latest run (3 September 2026)

| | Records |
|---|---|
| Unique records kept | **673** |
| Included | 436 |
| Manual review | 237 |
| Excluded (audit trail) | 313 |

## 5. License & credits
Developed at NIMRD "Grigore Antipa", Constanța, Romania, for EMODnet Biology. Data come from the
[Zenodo REST API](https://developers.zenodo.org/); each dataset keeps its own license.
