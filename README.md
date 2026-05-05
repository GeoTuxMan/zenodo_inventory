# Zenodo Inventory

Automated tool for creating an inventory of biological and ecological datasets from Zenodo, focusing on European and Arctic marine regions.

## Objective
The primary objective is to create an automated inventory of datasets related to marine biology and ecology, with a focus on European and Arctic regions.

## Search Parameters
The search is performed programmatically for the following categories:
- **Taxa**: Angiosperms, Birds, Benthos, Macroalgae, Mammals, Phytoplankton, Reptiles, Zooplankton, Virus.
- **Geographic Regions**: Arctic, Atlantic, Baltic Sea, Black Sea, Mediterranean Sea, North Sea.

## Technical Process
Data is extracted using the Zenodo REST API.

### API Querying
- An access token is used to ensure connection stability.
- For each combination of Taxon and Region, a GET request is sent.
- Results are filtered to include only "dataset" type items.
- A "retry" logic is implemented to handle network errors or server rate limits.

### Metadata Extraction and Processing
- **Title and Identifiers**: Dataset title, DOI, and link are extracted.
- **Provider and Owner**: Identifies creating individuals and institutions.
- **Temporal Coverage**: Uses regular expressions to scan for years (e.g., 1990-2023).
- **Data Type**: Automatic classification based on keywords (human observation, imaging, tracking, or eDNA).
- **Licensing and Access**: Retrieves license info and access conditions.
- **File Type**: Unique file extensions are collected from attached files.

### Deduplication and Consolidation
Records are uniquely identified by a key (Title + Provider). If a record is found multiple times, the Taxa covered and Geographic coverage fields are concatenated.

## Output
The results are saved in two formats:
- **Excel (`Dataset_Inventory_Zenodo.xlsx`)**: For manual analysis and reporting.
- **JSON (`data.json`)**: To feed the interactive web dashboard available at [https://sdn2.rmri.ro/zenodo_inventory/](https://sdn2.rmri.ro/zenodo_inventory/)

---

## Getting Started

### Prerequisites
- Python 3.7+
- A Zenodo Access Token (Get one at [Zenodo Applications](https://zenodo.org/account/settings/applications/tokens/new/))

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/GeoTuxMan/zenodo_inventory.git
   cd zenodo_inventory
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Usage
1. Open `zenodo_inventory.py` and replace `YOUR_ZENODO_ACCESS_TOKEN` with your actual token.
2. Run the script:
   ```bash
   python zenodo_inventory.py
   ```
3. The results will be generated in `Dataset_Inventory_Zenodo.xlsx` and `data.json`.
