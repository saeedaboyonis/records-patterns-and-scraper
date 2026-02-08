# Dono Data Engineer Assessment Solution

A production-quality, scalable Python system for property records analysis, web scraping, and document classification.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Installation](#installation)
4. [Usage](#usage)
5. [Task Details](#task-details)
6. [Test Results](#test-results)
7. [Scalability](#scalability)
8. [Assumptions](#assumptions)

---

## Overview

This solution implements three main tasks:

1. **County Pattern Analysis** - Streaming analysis of JSONL property records to detect patterns in instrument numbers, book/page values, dates, and document types.

2. **Seminole County Scraper** - Robust web scraper for the Seminole County Clerk's public property records system.

3. **LLM Document Classification** - Uses local Ollama LLM (free, no API keys) or rule-based fallback to classify 338 unique messy document types into 9 standardized categories.

### Key Features

- ✅ **Streaming Processing** - Memory-efficient processing of large files
- ✅ **OOP Architecture** - Clean separation of concerns with single-responsibility classes
- ✅ **Type Hints & Docstrings** - Full PEP-8 compliance
- ✅ **Structured Logging** - Comprehensive logging with configurable levels
- ✅ **Rate Limiting** - Respectful scraping with configurable delays
- ✅ **Retry Logic** - Automatic retries with exponential backoff
- ✅ **Docker Support** - Containerized execution
- ✅ **Dry-Run Mode** - LLM classification works without API key

---

## Architecture

```
assessment_solution/
├── src/
│   ├── pattern_analyzer.py      # Task 1: County pattern analysis
│   ├── seminole_scraper.py      # Task 2: Web scraper
│   ├── llm_classifier.py        # Bonus: LLM document classification
│   │
│   ├── domain/                  # Domain models & business logic
│   │   ├── models.py            # Data classes (Record, CountyStats, etc.)
│   │   └── normalizers.py       # Data normalization (names, dates)
│   │
│   ├── io/                      # Input/Output handling
│   │   ├── jsonl_reader.py      # Streaming JSONL reader
│   │   └── json_writer.py       # JSON writer with atomic writes
│   │
│   └── infra/                   # Infrastructure components
│       └── logging.py           # Structured logging setup
│
└── outputs/                     # Generated output files
    ├── county_patterns.json
    ├── seminole_test_results.json
    └── doc_type_mapping.json
```

### Design Principles

1. **Single Responsibility** - Each class has one clear purpose
2. **Dependency Injection** - Components accept dependencies via constructors
3. **Immutable Data** - Record objects are frozen dataclasses
4. **Streaming First** - Files are processed line-by-line, never fully loaded
5. **Fail-Safe** - Graceful error handling with detailed logging

### Core Components

| Component | Responsibility |
|-----------|---------------|
| `JsonlReader` | Stream JSONL files without loading into memory |
| `JsonWriter` | Write JSON with atomic operations |
| `Record` | Immutable property record data class |
| `CountyStatsAggregator` | Aggregate statistics during streaming |
| `PatternDetector` | Detect regex patterns in values |
| `SeminoleScraper` | Seminole County website scraper |
| `OllamaMapper` | Local LLM-based document classification |

---

## Installation

### Option 1: Virtual Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# For LLM classification, install Ollama: https://ollama.ai/download
# Then pull the model:
ollama pull llama3.1:8b
```

### Option 2: Docker Compose (Recommended for LLM)

Docker Compose runs both the app and Ollama LLM service together.

```bash
# Start Ollama service and pull the model (first time only)
docker compose up -d ollama
./scripts/pull_ollama_model.sh

# Run any task via Docker Compose
docker compose run --rm app python -m src.llm_classifier \
    --input inputs/nc_records_assessment.jsonl \
    --output outputs/doc_type_mapping.json
```

**Model persistence:** The `ollama_data` volume stores downloaded models, so they persist across container restarts.

### Option 3: Docker (App Only)

```bash
# Build image
docker build -t dono-assessment .

# Verify build
docker run --rm dono-assessment python --version
```

---

## Usage

### Task 1: County Pattern Analysis

Analyze patterns in property records JSONL file.

**Virtual Environment:**
```bash
python -m src.pattern_analyzer \
    --input inputs/nc_records_assessment.jsonl \
    --output outputs/county_patterns.json
```

**Docker:**
```bash
docker run --rm \
    -v "$PWD:/app" \
    dono-assessment \
    python -m src.pattern_analyzer \
    --input /app/inputs/nc_records_assessment.jsonl \
    --output /app/outputs_test/county_patterns.json
```

**Options:**
```
--input, -i     Path to input JSONL file (required)
--output, -o    Path for output JSON file (default: outputs/county_patterns.json)
--log-level     Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)
--log-file      Optional log file path
```

### Task 2: Seminole County Scraper

Search Seminole County property records by name.

**Virtual Environment:**
```bash
# Single name search
python -m src.seminole_scraper \
    --name "John Smith" \
    --output outputs/seminole_results.json

# Search with custom date range
python -m src.seminole_scraper \
    --name "Smith" \
    --date-start "1/1/2020" \
    --date-end "12/31/2024" \
    --output outputs/smith_results.json

# Run test suite with multiple names (uses default date range: 1/1/2020 to today)
python -m src.seminole_scraper \
    --test \
    --output outputs/seminole_test_results.json

# Disable chunking (single request, max 2000 rows)
python -m src.seminole_scraper \
    --name "Smith" \
    --no-chunked \
    --output outputs/smith_capped.json
```

**Docker:**
```bash
docker run --rm \
    -v "$PWD:/app" \
    dono-assessment \
    python -m src.seminole_scraper \
    --name "John Smith" \
    --output /app/outputs/seminole_results.json
```

**Options:**
```
--name, -n      Name to search for (required unless --test)
--output, -o    Path for output JSON file (default: outputs/seminole_test_results.json)
--max-results   Maximum number of results to return (default: unlimited)
--test          Run test searches with predefined names: Smith, Johnson Michael, Xyzabc
--chunked       Use adaptive sliding window search (default: enabled)
--no-chunked    Disable chunking - single request, max 2000 rows
--date-start    Start date for search (default: 1/1/2020 for method, 1/1/1913 for CLI)
--date-end      End date for search (default: today)
--timeout       Request timeout in seconds (default: 120)
--log-level     Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)
```

### Bonus: LLM Document Classification

Classify document types using a **local Ollama LLM** (completely free, no API keys needed).

#### Prerequisites: Install Ollama

1. **Install Ollama** from [ollama.ai/download](https://ollama.ai/download)
   - Linux: `curl -fsSL https://ollama.ai/install.sh | sh`
   - macOS: Download from website or `brew install ollama`
   - Windows: Download installer from website

2. **Pull the model**:
   ```bash
   ollama pull llama3.1:8b
   ```

3. **Start Ollama** (usually auto-starts after install):
   ```bash
   ollama serve
   ```

#### Usage

**Option A: Docker Compose (Recommended)**

Docker Compose runs both Ollama and the app together - no local Ollama install needed:

```bash
# First time: start Ollama and pull the model
docker compose up -d ollama
./scripts/pull_ollama_model.sh

# Run classification
docker compose run --rm app python -m src.llm_classifier \
    --input inputs/nc_records_assessment.jsonl \
    --output outputs/doc_type_mapping.json

# Model weights are stored in the ollama_data volume and persist across restarts
```

**Option B: Virtual Environment (Local Ollama)**

```bash
# Run classification with local LLM
python -m src.llm_classifier \
    --input inputs/nc_records_assessment.jsonl \
    --output outputs/doc_type_mapping.json

# Use a different model
python -m src.llm_classifier \
    --input inputs/nc_records_assessment.jsonl \
    --model llama3.1:8b

# Dry-run mode (no LLM needed, uses rule-based classification)
python -m src.llm_classifier \
    --input inputs/nc_records_assessment.jsonl \
    --output outputs/doc_type_mapping.json \
    --dry-run
```

**Option C: Docker with Host Ollama**

If you have Ollama running on your host machine:

```bash
docker run --rm \
    --network host \
    -v "$PWD:/app" \
    dono-assessment \
    python -m src.llm_classifier \
    --input /app/inputs/nc_records_assessment.jsonl \
    --output /app/outputs/doc_type_mapping.json
```

**Options:**
```
--input, -i     Path to input JSONL file (required)
--output, -o    Path for output JSON file
--model         Ollama model (default: llama3.1:8b)
--batch-size    Number of doc_types per batch (default: 20)
--dry-run       Use rule-based classification (no LLM calls)
--max-types     Maximum doc_types to classify
--log-level     Logging level (default: INFO)
```

> **Benefits of Local LLM:**
> - ✅ **Completely free** - no API costs
> - ✅ **No rate limits** - process as fast as your hardware allows
> - ✅ **Data stays local** - no external API calls
> - ✅ **Works offline** - once model is downloaded


---

## Task 1 — County Pattern Analysis (Results)

This section documents the findings from analyzing the NC property records JSONL file. **For each county in the dataset**, we extract and document answers to the four required questions. Full per-county breakdown is available in [outputs/county_patterns.json](outputs/county_patterns.json).

### Per-County Summary Table

| County | Records | Instrument Formats | Book Format | Date Range | Anomalies | Unique Doc Types | Top Doc Type |
|--------|---------|-------------------|-------------|------------|-----------|------------------|--------------|
| Alamance | 89 | 10 formats | numeric | 1973-01-25 to 2025-10-20 | 1 | 33 | DEED |
| Buncombe | 130 | 8 formats | numeric | 1973-05-17 to 2025-11-12 | 0 | 29 | DEED |
| Cabarrus | 409 | 17 formats | numeric | 1970-08-30 to 2025-08-19 | 1 | 72 | D-TR |
| Cumberland | 2,479 | 19 formats | numeric | 1970-06-07 to 2025-10-27 | 7 | 100 | DEED |
| Davidson | 23 | 2 formats | numeric | 2000-05-18 to 2025-06-18 | 0 | 10 | DEED |
| Durham | 491 | 7 formats | numeric | 1971-03-07 to 2025-11-11 | 0 | 38 | DEED |
| Forsyth | 966 | 5 formats | numeric | 1972-11-30 to 2025-12-18 | 1 | 63 | DEED |
| Guilford | 14 | 2 formats | numeric | 1999-07-11 to 2024-02-04 | 0 | 5 | R |
| Johnston | 2,493 | 8 formats | numeric | 1873-05-06 to 2025-09-30 | 0 | 41 | DEED OF TRUST |
| Mecklenburg | 2,490 | 11 formats | numeric | 1972-04-05 to 2025-12-03 | 0 | 115 | DEED |
| Onslow | 1,677 | 7 formats | numeric | 1976-04-16 to 2025-12-01 | 0 | 49 | DEED |
| Union | 152 | 2 formats | numeric | 1975-07-22 to 2018-10-11 | 0 | 3 | DEED |
| Wake | 2,473 | 19 formats | numeric | 1970-04-30 to 2025-11-13 | 4 | 71 | DEED |

---

### 1. Instrument Number Patterns (Per County)

> **Question:** What format(s) do instrument numbers follow? Write regex pattern(s) that match. Note any anomalies or multiple formats.

**Answer:** Each county has multiple instrument number formats. Below are the top patterns for each county with their regex and coverage percentage:

**Alamance** (89 records, 10 formats):
- `^[a-z]{2}\d{7}$` — 42.7% (e.g., `bp4712143`)
- `^\d{1,5}$` — 24.7% (e.g., `12796`)
- `^[a-z]{2}\d{6}$` — 13.5% (e.g., `bp509826`)
- ... and 7 more rare patterns

**Buncombe** (130 records, 8 formats):
- `^[a-z]{2}\d{7}$` — 52.3% (e.g., `bp6206902`)
- `^[a-z]{2}\d{8}$` — 27.7% (e.g., `bp60071122`)
- `^[a-z]{2}\d{6}$` — 9.2% (e.g., `bp790583`)
- ... and 5 more rare patterns

**Cabarrus** (409 records, 17 formats):
- `^\d{4}-\d{5,7}$` — 68.9% (e.g., `1983-02828`)
- `^\d{1,5}$` — 12.7% (e.g., `20938`)
- `^[a-z]{2}\d{6}$` — 5.6% (e.g., `bp490575`)
- ... and 14 more rare patterns

**Cumberland** (2,479 records, 19 formats):
- `^\d{4}-\d{5,7}$` — 94.2% (e.g., `2007-06494`)
- `^[a-z]{2}\d{7}$` — 2.1% (e.g., `bp2868165`)
- `^\d{1,5}$` — 1.2% (e.g., `39919`)
- ... and 16 more rare patterns

**Davidson** (23 records, 2 formats):
- `^\d{10,}$` — 95.7% (e.g., `2022019327`)
- `^[a-z]{2}\d{3}$` — 4.3% (e.g., `bp512`)

**Durham** (491 records, 7 formats):
- `^\d{10,}$` — 94.1% (e.g., `2010005608`)
- `^\d{6,9}$` — 3.5% (e.g., `99015437`)
- `^[a-z]{2}\d{6}$` — 1.4% (e.g., `bp136165`)
- ... and 4 more rare patterns

**Forsyth** (966 records, 5 formats):
- `^\d{10,}$` — 99.3% (e.g., `1985013199`)
- `^[a-z]{2}\d{5}$` — 0.3% (e.g., `bp34177`)
- `^[a-z]{2}\d{6}$` — 0.2% (e.g., `bp156480`)
- ... and 2 more rare patterns

**Guilford** (14 records, 2 formats):
- `^\d{10,}$` — 92.9% (e.g., `2003147307`)
- `^[a-z]{2}\d{5}$` — 7.1% (e.g., `bp17840`)

**Johnston** (2,493 records, 8 formats):
- `^\d{10,}$` — 88.5% (e.g., `2022806081`)
- `^\d{6,9}$` — 11.0% (e.g., `1692218`)
- `^[a-z]{2}\d{7}$` — 0.2% (e.g., `bp1962317`)
- ... and 5 more rare patterns

**Mecklenburg** (2,490 records, 11 formats):
- `^\d{10,}$` — 89.3% (e.g., `2023067542`)
- `^\d{6,9}$` — 7.2% (e.g., `96140024`)
- `^[a-z]{2}\d{8}$` — 1.2% (e.g., `bp19923785`)
- ... and 8 more rare patterns

**Onslow** (1,677 records, 7 formats):
- `^[a-z]{2}\d{7}$` — 86.2% (e.g., `bp5399793`)
- `^[a-z]{2}\d{6}$` — 8.5% (e.g., `bp345952`)
- `^[a-z]{2}\d{5}$` — 2.9% (e.g., `bp55798`)
- ... and 4 more rare patterns

**Union** (152 records, 2 formats):
- `^\d{4}-\d{5,7}$` — 99.3% (e.g., `2001-42520`)
- `^[a-z]{2}\d{7}$` — 0.7% (e.g., `bp8765541`)

**Wake** (2,473 records, 19 formats):
- `^\d{6}\-\d{5}$` — 89.4% (e.g., `010905-02162`)
- `^[A-Z]{2}\d{4}-\d+$` — 5.0% (e.g., `BM2001-02017`)
- `^\d{10,}$` — 2.7% (e.g., `2025010010`)
- ... and 16 more rare patterns

**Anomalies Noted:**
- `bp` prefix indicates synthetic IDs (common across all counties)
- Some records have embedded `BK/PG` strings (e.g., `BK7242PG572`)
- Alphanumeric suffixes exist (e.g., `20220173191K`)
- Wake has a unique `BM` prefix format for certain books

---

### 2. Book/Page Number Patterns (Per County)

> **Question:** How are book and page numbers formatted? Are they always numeric? Do they include letters? What are the ranges (min/max)?

**Answer:** Book and page numbers are analyzed per county:

| County | Book Format | Includes Letters? | Book Range (Min-Max) | Page Range (Min-Max) |
|--------|-------------|-------------------|----------------------|----------------------|
| Alamance | numeric | No | 18 - 4,779 | 11 - 917 |
| Buncombe | numeric (99.1%), alpha-numeric (0.9%) | Yes (rare) | 18 - 6,542 | 1 - 1,966 |
| Cabarrus | numeric | No | 1 - 17,476 | 1 - 847 |
| Cumberland | numeric | No | 9 - 14,186 | 1 - 60,352 |
| Davidson | numeric | No | 5 - 2,706 | 12 - 2,289 |
| Durham | numeric | No | 4 - 10,423 | 1 - 999 |
| Forsyth | numeric | No | 2 - 3,901 | 1 - 4,871 |
| Guilford | numeric | No | 82 - 8,798 | 40 - 2,580 |
| Johnston | numeric | No | 41 - 6,970 | 1 - 1,000 |
| Mecklenburg | numeric | No | 1 - 40,047 | 1 - 914,914 |
| Onslow | numeric | No | 11 - 6,485 | 1 - 980 |
| Union | numeric | No | 276 - 7,251 | 1 - 932 |
| Wake | numeric (94.3%), alpha-prefix (5.7%) | Yes (rare) | 32 - 20,068 | 1 - 8,629 |

**Key Findings:**
- **Almost universally numeric**: 12 of 13 counties use purely numeric book identifiers
- **Exceptions with letters**: 
  - Buncombe has rare alphanumeric books (e.g., `K5551`) at 0.9%
  - Wake has `BM`-prefixed books (e.g., `BM2001`) at 5.7%
- **Page numbers**: Always numeric across all counties (regex: `^\d+$`)
- **Notable outliers**: 
  - Mecklenburg has page numbers up to 914,914 (likely data anomaly)
  - Cumberland has page numbers up to 60,352

---

### 3. Date Ranges (Per County)

> **Question:** What is the earliest and latest record date for each county? Are there any suspicious dates?

**Answer:** Date ranges and anomalies are extracted per county:

| County | Earliest Date | Latest Date | Suspicious Dates | Anomaly Details |
|--------|---------------|-------------|------------------|-----------------|
| Alamance | 1973-01-25 | 2025-10-20 | 1 | Future date: `2065-10-28` |
| Buncombe | 1973-05-17 | 2025-11-12 | 0 | None |
| Cabarrus | 1970-08-30 | 2025-08-19 | 1 | Future date detected |
| Cumberland | 1970-06-07 | 2025-10-27 | 7 | Multiple future dates |
| Davidson | 2000-05-18 | 2025-06-18 | 0 | None |
| Durham | 1971-03-07 | 2025-11-11 | 0 | None |
| Forsyth | 1972-11-30 | 2025-12-18 | 1 | Future date detected |
| Guilford | 1999-07-11 | 2024-02-04 | 0 | None |
| Johnston | 1873-05-06 | 2025-09-30 | 0 | None (1873 is valid historical) |
| Mecklenburg | 1972-04-05 | 2025-12-03 | 0 | None |
| Onslow | 1976-04-16 | 2025-12-01 | 0 | None |
| Union | 1975-07-22 | 2018-10-11 | 0 | None |
| Wake | 1970-04-30 | 2025-11-13 | 4 | Multiple future dates |

**Anomaly Detection Rules:**
1. **Future dates** (date > today): Flagged as suspicious (e.g., `2065-10-28`)
2. **Very old dates** (year < 1800): Flagged as likely parse errors
3. **Parse failures**: Dates that cannot be interpreted

**Note:** Anomalies are listed in `date_range.anomalies` array (up to 10 per county). Johnston's 1873 date appears valid (historical records).

---

### 4. Document Type Distribution (Per County)

> **Question:** What are the top 10 most common doc_type values? How many unique doc_type values exist? How do doc_type and doc_category relate?

**Answer:** Below are the **top 10 doc_types for each county**, along with unique doc_type counts:

**Alamance** (33 unique doc_types):
1. `DEED` (17)
2. `Deed of Trust` (11)
3. `D T` (6)
4. `Assignment of Deed of Trust` (4)
5. `Easement` (4)
6. `Plat` (4)
7. `ASGM DT` (3)
8. `CANCEL` (3)
9. `General Warranty Deed` (3)
10. `Special Warranty Deed` (3)

**Buncombe** (29 unique doc_types):
1. `DEED` (25)
2. `DEED OF TRUST` (23)
3. `UCC Financing Statement` (10)
4. `DEED OF TRUST SATISFACTION` (9)
5. `POWER OF ATTORNEY` (7)
6. `Plat` (7)
7. `Deed of Trust` (6)
8. `Satisfaction` (5)
9. `Covenants and Restrictions` (4)
10. `Doing Business As Certificate` (3)

**Cabarrus** (72 unique doc_types):
1. `D-TR` (45)
2. `DEED` (45)
3. `REST` (37)
4. `SAT` (27)
5. `MTGE` (21)
6. `PLAT` (16)
7. `ASIGN` (15)
8. `Deed of Trust` (15)
9. `General Warranty Deed` (14)
10. `Deed` (12)

**Cumberland** (100 unique doc_types):
1. `DEED` (1192)
2. `DT` (250)
3. `SAT` (102)
4. `D T` (95)
5. `SUB TR` (76)
6. `CAN` (67)
7. `REL D` (65)
8. `PLAT` (54)
9. `ESMT` (52)
10. `TRS D` (37)

**Davidson** (10 unique doc_types):
1. `DEED` (6)
2. `DE` (5)
3. `D/T` (3)
4. `SAT` (3)
5. `CAN/LIEN` (1)
6. `DEED OF TRUST` (1)
7. `LIEN` (1)
8. `PLAT` (1)
9. `Plat` (1)
10. `SATISFACTION` (1)

**Durham** (38 unique doc_types):
1. `DEED` (253)
2. `DEED OF TRUST` (44)
3. `PLAT` (36)
4. `Plat` (26)
5. `SATISFACTION` (25)
6. `RIGHT OF WAY` (9)
7. `DECLARATION` (8)
8. `Easement` (8)
9. `ASSIGNMENT` (7)
10. `SEE INSTRUMENT` (6)

**Forsyth** (63 unique doc_types):
1. `DEED` (306)
2. `REL DEED` (223)
3. `D OF T` (78)
4. `PLAT` (51)
5. `ASGMT` (27)
6. `DEED OF TRUST` (25)
7. `DEED ACEPT` (22)
8. `SATISFACTION` (19)
9. `DEDICATION` (16)
10. `RESTR COV` (16)

**Guilford** (5 unique doc_types):
1. `R` (7)
2. `DEED` (3)
3. `DT` (2)
4. `PLAT` (1)
5. `Plat` (1)

**Johnston** (41 unique doc_types):
1. `DEED OF TRUST` (636)
2. `SATISFACTION` (539)
3. `DEED` (532)
4. `SEE INSTRUMENT` (139)
5. `RELEASE` (96)
6. `SUBSTITUTION TRUSTEE` (91)
7. `PARTIAL RELEASE` (85)
8. `ASSIGNMENT` (79)
9. `Historical` (41)
10. `EASEMENT` (32)

**Mecklenburg** (115 unique doc_types):
1. `DEED` (437)
2. `DEED OF TRUST` (397)
3. `MAP` (250)
4. `MAP/R` (205)
5. `SATISFACTION - CERTIFICATE OF` (119)
6. `COMMISSIONERS DEED` (101)
7. `FORECLOSURE` (94)
8. `SUBSTITUTION TRUSTEE` (74)
9. `CAN` (71)
10. `TRUSTEES DEED` (62)

**Onslow** (49 unique doc_types):
1. `DEED` (648)
2. `RELEASE` (312)
3. `DEED OF TRUST` (252)
4. `CANCELLATION` (114)
5. `MISCELLANEOUS` (75)
6. `ASSIGNMENT` (32)
7. `MAP` (27)
8. `Deed of Trust` (26)
9. `AFFIDAVIT` (20)
10. `RESTRICTIVE COVENANT` (19)

**Union** (3 unique doc_types):
1. `DEED` (148)
2. `QCD` (3)
3. `Agreement` (1)

**Wake** (71 unique doc_types):
1. `DEED` (940)
2. `DEED OF TRUST` (394)
3. `SATISFACTION` (148)
4. `RELEASE` (143)
5. `MAP PLAT` (124)
6. `PARTIAL RELEASE` (91)
7. `CANCELLATION` (89)
8. `CERTIFICATE OF SATISFACTION` (68)
9. `REQUEST NOTICE` (42)
10. `POWER OF ATTORNEY` (40)

---

**doc_type vs doc_category Relationship:**
- `doc_type` = original, granular classification (300+ unique values across dataset)
- `doc_category` = normalized grouping (~10-15 categories)
- **Mapping is many-to-one**: Multiple `doc_type` values → same `doc_category`
  - Example: `DEED`, `WARRANTY DEED`, `QUIT CLAIM DEED` → `doc_category: "deed"`
  - Example: `DEED OF TRUST`, `D T`, `D-TR`, `DT`, `D/T` → `doc_category: "mortgage"` or `"deed_of_trust"`
- **Inconsistencies exist**: Same document type may have different casing (e.g., `Plat` vs `PLAT`) or abbreviations (e.g., `SAT` vs `SATISFACTION`)

---

### Common Regex Patterns Across All Counties

| Pattern (Regex Template) | Description | Example Counties |
|--------------------------|-------------|------------------|
| `\d{4}-\d{5,7}` | Year-hyphen-sequence (YYYY-NNNNN) | Cabarrus, Cumberland, Union |
| `[a-z]{2}\d{6,8}` | Two-letter prefix + digits (bp/synthetic) | Alamance, Buncombe, Onslow |
| `\d{10,}` | Long numeric sequences (10+ digits) | Davidson, Durham, Forsyth, Guilford, Johnston, Mecklenburg |
| `\d{6}-\d{5}` | Six-digit book - five-digit page | Wake |
| `\d{1,5}` | Short numeric only | Alamance, Cabarrus, Cumberland |

---

### Sample JSON Output Structure

```json
{
  "wake": {
    "record_count": 2473,
    "instrument_patterns": [
      {
        "pattern": "\\d{6}\\-\\d{5}",
        "regex": "^\\d{6}\\-\\d{5}$",
        "example": "010905-02162",
        "count": 2211,
        "percentage": 89.4
      }
    ],
    "book_patterns": [
      {
        "pattern": "numeric",
        "regex": "^\\d+$",
        "example": "10905",
        "count": 2473,
        "percentage": 100.0
      }
    ],
    "date_range": {
      "earliest": "1970-04-30",
      "latest": "2025-11-13",
      "anomalies": ["2026-01-15T..."]
    },
    "doc_type_distribution": {
      "DEED": 580,
      "D T": 453,
      "SUB TR": 143,
      ...
    },
    "unique_doc_types": 71
  }
}
```

---

### Running the Analysis

```bash
# Generate county_patterns.json
python -m src.pattern_analyzer \
    --input inputs/nc_records_assessment.jsonl \
    --output outputs/county_patterns.json

# With debug logging
python -m src.pattern_analyzer \
    --input inputs/nc_records_assessment.jsonl \
    --output outputs/county_patterns.json \
    --log-level DEBUG
```

---

## Task Details

### Task 1: County Pattern Analysis

#### Streaming Design

The pattern analyzer processes records without loading the entire file:

```python
for record in JsonlReader(input_file):
    county = record.get("county")
    aggregators[county].add_record(record)
```

Memory usage is O(number of counties × sample size), not O(file size).

#### Pattern Detection Logic

1. **Instrument Numbers**
   - Pre-defined patterns (YYYY-NNNNN, bp-prefix, etc.)
   - Dynamic pattern inference for unknown formats
   - Anomaly flagging for rare patterns (<1%)

2. **Book/Page Values**
   - Numeric vs alphanumeric detection
   - Min/max value tracking for numeric fields
   - Structural pattern analysis

3. **Date Analysis**
   - Parse multiple date formats using dateutil
   - Track earliest/latest valid dates
   - Flag anomalies: future dates, extremely old (<1800), invalid formats

4. **Document Types**
   - Top 10 frequency distribution
   - doc_type to doc_category mapping
   - Inconsistency detection (same type → multiple categories)

### Task 2: Seminole County Scraper

#### Target Website
https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html

#### How the Scraper Works

The Seminole County Clerk's website uses a Vue.js SPA with a JSON API backend. The scraper:

1. **Session Warmup** - Fetches `index.html` to acquire session cookies
2. **CriteriaSearch API** - Sends GET requests to `/Home/CriteriaSearch` with JSON criteria
3. **Adaptive Sliding Window** - Uses dynamic date windowing to bypass API limits
4. **Deduplication** - Uses `gin` (global identifier) to remove duplicates
5. **Normalization** - Converts results to NC dataset format

#### The 2000-Row Limit Challenge

**Problem:** The CriteriaSearch API returns a **maximum of 2000 rows per request**. The website's "Pg 1 of 67" pagination is purely client-side over this capped dataset. There is **no server-side pagination parameter**.

For common names like "Smith" with 7,000+ records, a single API call would miss ~5,000 records.

**Solution: Adaptive Sliding Window Search**

Instead of fixed buckets, we use a dynamic sliding window that adjusts based on result density:

```
Algorithm:
1. Start from end_dt, work backwards toward start_dt
2. Initial window span: 160 days
3. For each window:
   - If result_count >= 2000 (capped): SHRINK span by half, retry
   - If result_count < 1000 (sparse): EXPAND span by 2x for next window
   - If 1000-1999 (good): Accept results, move window back
4. Handle single-day caps with warnings (data may be incomplete)
```

**Why this works:**
- **Adaptive**: Dense periods (more recordings) get smaller windows automatically
- **Efficient**: Sparse periods (fewer recordings) use larger windows, fewer API calls
- **Optimal packing**: Targets 1000-1999 rows per call (vs 2000 cap)
- **No gaps**: Windows slide contiguously, ensuring complete coverage

#### Performance Results

| Search Name | Records | API Calls | Avg Rows/Call | Time | Records/Min |
|-------------|---------|-----------|---------------|------|-------------|
| Smith | 7,667 | 8 | 1,322 | 115.7s | **3,977** |
| Johnson Michael | 135 | 4 | 36 | 7.9s | **1,023** |
| Xyzabc | 0 | 4 | 0 | 7.7s | N/A |

**Key metrics for "Smith" (common name):**
- Window sizes ranged from 160-320 days
- Zero capped single days (complete data retrieval)
- Average 1,322 rows per API call (66% of cap = efficient)

#### Edge Cases Handled

| Edge Case | How Handled |
|-----------|-------------|
| **No results** | API returns empty string `""`, parsed as empty list |
| **2000-row cap** | Window automatically shrinks by half |
| **Single-day still capped** | Warning logged, results accepted (may be incomplete) |
| **Sparse results** | Window expands up to 10 years for efficiency |
| **Name formats** | Converts to uppercase, searches both directions (From/To) |
| **Duplicate records** | Deduplicated by `gin` or composite key |
| **Session timeout** | Auto-warmup on first request per search |
| **Network errors** | 3 retries with exponential backoff |

#### Rate Limiting

- **Chunked mode**: 1-2 second delay between API calls
- **Standard mode**: 2-5 second delay with jitter
- Respects server by not hammering with rapid requests

#### Challenges Encountered

1. **No Server-Side Pagination**: The website's API returns max 2000 rows with no pagination parameters. Solved with adaptive sliding window algorithm.

2. **Session Management**: The site requires valid session cookies. Solved by fetching `index.html` first to acquire session.

3. **Inconsistent Empty Responses**: API returns empty string `""` for no results instead of `[]`. Handled in response parsing.

4. **Date Format Requirements**: API expects `MM/DD/YYYY` format specifically. Converted dates appropriately.

5. **Name Direction Ambiguity**: Names can appear in either "From" or "To" party. Search both directions and deduplicate.

#### Output Format

Output is a **JSON array** of records (valid JSON that can be parsed with `json.load()`). Each record matches the NC dataset schema exactly:
```json
[
  {
    "instrument_number": "2023012345",
    "parcel_number": null,
    "county": "seminole",
    "state": "FL",
    "book": "1234",
    "page": "567",
    "doc_type": "WARRANTY DEED",
    "doc_category": "deed",
    "original_doc_type": "WARRANTY DEED",
    "book_type": "OR",
    "grantors": ["SMITH JOHN"],
    "grantees": ["DOE ROBERT"],
    "date": "2023-05-15T14:30:00-04:00",
    "consideration": 350000.0
  },
  ...
]
```

**Validation:**
```bash
python -c "import json; json.load(open('outputs/seminole_test_results.json')); print('OK')"
```

### Bonus: LLM Classification

#### Strategy

1. **Strategic Sampling**
   - Collect all unique doc_types with frequencies
   - Include both frequent (coverage) and rare (edge cases) types
   - Default: all unique types, configurable with `--max-types`

2. **Batch Processing** (LLM Mode)
   - Group doc_types into batches of 20
   - Single API call per batch
   - Reduces cost while maintaining context

3. **Classification**
   - System prompt defines 9 standard categories with examples
   - Temperature 0.1 for consistency
   - JSON response format for reliable parsing

4. **Validation**
   - Confidence scoring (0.0-1.0)
   - Uncertain flagging (confidence < 0.7)
   - Category validation against allowed values

#### Standard Categories

| Category | Description |
|----------|-------------|
| `SALE_DEED` | Property transfer documents (warranty deed, quitclaim, grant deed) |
| `DEED_OF_TRUST` | Trust-based security instruments |
| `MORTGAGE` | Loan security documents, assignments |
| `RELEASE` | Satisfaction, discharge, cancellation documents |
| `LIEN` | Claims against property (judgment, mechanic's lien, UCC) |
| `PLAT` | Maps, surveys, subdivisions |
| `EASEMENT` | Right-of-way, utility easements |
| `LEASE` | Rental/lease agreements |
| `MISC` | Documents not fitting other categories |

#### Cost (Local Ollama)

| Model | Cost | Notes |
|-------|------|-------|
| llama3.1:8b | **$0** | Local, no API costs, no rate limits |
| llama3.1:70b | **$0** | Larger model, requires more VRAM |
| mistral:7b | **$0** | Alternative lightweight model |

#### Dry-Run / Rule-Based Mode

When Ollama is not available, an enhanced rule-based classifier is used:
- **Priority-ordered regex patterns** - DEED_OF_TRUST checked before SALE_DEED
- **Comprehensive abbreviation support** - 50+ abbreviations mapped
- **High coverage** - 82% of doc_types classified with confidence ≥ 0.7
- Zero API cost

#### LLM Classification Approach — Detailed Documentation

##### 1. How did you decide which records to sample?

**Answer: We classify ALL unique doc_types, not a sample.**

Rather than sampling records, we extract all **338 unique `doc_type` values** from the dataset and classify each one. This approach ensures:

- **100% coverage**: Every record gets a standardized category
- **Frequency-aware**: Each doc_type carries its frequency count, so the LLM understands which types are most important
- **Efficiency**: 338 unique types is manageable (vs. 13,877 individual records)

The `DocTypeSampler` class collects frequencies:
```python
# Collect all unique doc_types with their frequencies
sampler = DocTypeSampler()
for record in reader:
    doc_type = record.get("doc_type")
    sampler.doc_type_counts[doc_type] += 1

# Returns: [("DEED", 3500), ("DEED OF TRUST", 1772), ...]
```

If needed, `--max-types N` can limit to the top N most frequent types for faster processing.

##### 2. What prompt did you use with the LLM?

**System Prompt** (defines categories and examples):
```
You are an expert in real estate and property records documentation.
Your task is to classify document types from property records into standardized categories.

Standard Categories:
- SALE_DEED: Documents transferring property ownership (warranty deed, quitclaim deed, deed, grant deed)
- MORTGAGE: Documents securing a loan with property (mortgage)
- DEED_OF_TRUST: Trust-based security instruments (deed of trust, trust deed, assignment of deed of trust)
- RELEASE: Documents releasing liens, mortgages, or claims (satisfaction, release, discharge, cancellation)
- LIEN: Documents creating claims against property (lis pendens, mechanic's lien, tax lien, judgment lien)
- PLAT: Maps and surveys of property (plat, subdivision, survey, map)
- EASEMENT: Rights to use another's property (easement, right of way, utility easement)
- LEASE: Rental/lease agreements (lease, ground lease, rental agreement)
- MISC: Any document that doesn't clearly fit the above categories

EXAMPLES:
- "DEED" => SALE_DEED
- "WARRANTY DEED" => SALE_DEED
- "DT" => DEED_OF_TRUST (abbreviation)
- "SATISFACTION" => RELEASE
- "LIS PENDENS" => LIEN
...

CRITICAL INSTRUCTIONS:
1. Respond with ONLY a valid JSON array
2. Each item must have: original_type, category, confidence, reasoning
3. category must be exactly one of the 9 standard categories
4. confidence must be 0.0-1.0
5. reasoning should be brief (<50 chars)
```

**User Prompt** (batch of doc_types):
```
Classify the following document types into standard categories.

- DEED (frequency: 3500)
- DEED OF TRUST (frequency: 1772)
- DT (frequency: 250)
- SAT (frequency: 102)
...

Respond with a JSON array only.
```

##### 3. How did you validate the LLM's classifications?

**Multi-layer validation approach:**

| Validation Layer | Method | Action on Failure |
|------------------|--------|-------------------|
| **Category validation** | Check against allowed list | Default to MISC |
| **Confidence scoring** | LLM provides 0.0-1.0 score | Flag if < 0.7 |
| **JSON parsing** | Extract JSON from response | Retry or fail batch |
| **Frequency weighting** | High-frequency errors are critical | Manual review flagged |

**Code validation:**
```python
# Validate category is in allowed list
if category not in STANDARD_CATEGORIES:
    logger.warning(f"Invalid category '{category}' for '{original_type}'")
    category = "MISC"
    confidence = min(confidence, 0.5)

# Flag uncertain mappings
mapping.is_uncertain = confidence < 0.7
```

**Results validation:**
- **45 uncertain mappings** (13.3%) flagged for review
- Category distribution matches expected real estate patterns
- Spot-checked abbreviations: DT→DEED_OF_TRUST ✓, SAT→RELEASE ✓, QCD→SALE_DEED ✓

##### 4. What was the cost (API calls, tokens)?

| Metric | Value |
|--------|-------|
| **Total API calls** | 17 |
| **Batch size** | 20 types per call |
| **Types processed** | 338 |
| **Records covered** | 13,877 |
| **Token usage** | N/A (local LLM) |
| **Total cost** | **$0.00** |

**Cost breakdown:**
- Using **local Ollama** with `llama3.1:8b` model
- No API fees, no rate limits, no token billing
- One-time model download (~4.7GB for 8B model)
- Processing time: ~2-3 minutes total

**Comparison to cloud APIs:**
| Provider | Est. Cost (338 types) | Rate Limits |
|----------|----------------------|-------------|
| OpenAI GPT-4o-mini | ~$0.05 | 500 RPM |
| Google Gemini | ~$0.02 | 15 RPM (free tier) |
| **Ollama (local)** | **$0.00** | **None** |

##### 5. What trade-offs did you make between accuracy and cost?

| Trade-off | Decision | Rationale |
|-----------|----------|-----------|
| **Model size** | 8B params (not 70B) | Good accuracy, runs on consumer hardware |
| **Temperature** | 0 (deterministic) | Consistency over creativity |
| **Batch size** | 20 types/call | Balance context quality vs. throughput |
| **All types vs sample** | All 338 types | 100% coverage worth the extra calls |
| **Local vs cloud** | Local Ollama | Zero cost, no rate limits, data privacy |

**Accuracy vs. Cost Analysis:**

```
Cloud API approach:
- GPT-4o: Higher accuracy, ~$0.50 for 338 types
- Rate limits cause delays (429 errors experienced with Gemini)

Local LLM approach (chosen):
- llama3.1:8b: Very good accuracy for classification tasks
- $0 cost, unlimited calls, no rate limits
- Trade-off: Requires local GPU/CPU resources
```

**Why local LLM won:**
1. **Classification is a "solved" task** - 8B models excel at categorization
2. **Structured output** - JSON format is well-supported
3. **Domain-specific prompting** - Examples in prompt guide the model
4. **Validation layer** - Catches and corrects errors regardless of model

**Result: 86.7% confident classifications (293/338 types) at zero cost.**

---

## Test Results

### Task 1: Pattern Analysis

Sample output structure:
```json
{
  "alamance": {
    "record_count": 89,
    "instrument_patterns": [
      {
        "pattern": "A{2}N{7}",
        "regex": "^[a-z]{2}\\d{7}$",
        "example": "bp4712143",
        "count": 38,
        "percentage": 42.7
      },
      {
        "pattern": "N-NNNNN",
        "regex": "^\\d{1,5}$",
        "example": "12796",
        "count": 22,
        "percentage": 24.7
      }
    ],
    "book_patterns": [
      {
        "pattern": "numeric",
        "regex": "^\\d+$",
        "example": "83",
        "count": 82,
        "percentage": 100.0
      }
    ],
    "date_range": {
      "earliest": "1973-01-25",
      "latest": "2025-10-20",
      "anomalies": ["2065-10-28T21:00:00"]
    },
    "doc_type_distribution": {
      "DEED": 17,
      "Deed of Trust": 11,
      "D T": 6,
      "Assignment of Deed of Trust": 4,
      "Easement": 4,
      "...": "..."
    }
  },
  "wake": { "..." },
  "mecklenburg": { "..." }
}
```

### Task 2: Scraper Results

Test searches performed with sliding window algorithm.

**Test Configuration (defaults):**
- Date range: `1/1/2020` to `today` (Jan 30, 2026)
- Chunked mode: enabled
- No max_results limit

| Test Name | Purpose | Records | API Calls | Time | Status |
|-----------|---------|---------|-----------|------|--------|
| **Smith** | Common name, tests cap handling | 7,667 | 8 | 115.7s | ✅ Pass |
| **Johnson Michael** | Full name, moderate results | 135 | 4 | 7.9s | ✅ Pass |
| **Xyzabc** | Nonexistent name, no results | 0 | 4 | 7.7s | ✅ Pass |

**Performance Summary:**
- **Peak throughput**: 3,977 records/minute (Smith search)
- **Average rows per API call**: 1,322 (66% utilization of 2000 cap)
- **Total unique records retrieved**: 7,802 across all tests
- **Zero data loss**: No capped single days (complete retrieval)

### Bonus: LLM Document Type Classification Results

The classifier successfully mapped **338 unique doc_types** into 9 standardized categories using **local Ollama LLM** (llama3.1:8b), covering **13,877 records** with only **45 uncertain mappings** (13.3%). **17 LLM calls** were made at **zero cost**.

#### Category Distribution (LLM Results)

| Category | Records | % of Total |
|----------|---------|------------|
| **SALE_DEED** | 5,272 | 38.0% |
| **DEED_OF_TRUST** | 3,114 | 22.4% |
| **RELEASE** | 2,303 | 16.6% |
| **MISC** | 1,817 | 13.1% |
| **PLAT** | 919 | 6.6% |
| **EASEMENT** | 212 | 1.5% |
| **LEASE** | 107 | 0.8% |
| **MORTGAGE** | 73 | 0.5% |
| **LIEN** | 60 | 0.4% |

#### Key Insights from LLM Classification

- **SALE_DEED dominates** at 38%, reflecting typical property transaction patterns
- **DEED_OF_TRUST + MORTGAGE** combined represent 22.9% of security instruments
- **RELEASE** documents (16.6%) indicate high volume of paid-off mortgages/liens
- **MISC** (13.1%) captures administrative documents (POA, affidavits, agreements)
- **LEASE** exists but is rare (0.8%) - most records are ownership transfers, not rentals
- **LIEN** (0.4%) is the smallest category - most filings are routine transactions

#### Sample Mappings

| Original Type | → Category | Confidence |
|---------------|------------|------------|
| `DEED` | SALE_DEED | 0.85 |
| `DEED OF TRUST` | DEED_OF_TRUST | 0.90 |
| `DT` | DEED_OF_TRUST | 0.90 |
| `SATISFACTION` | RELEASE | 0.85 |
| `REL DEED` | RELEASE | 0.85 |
| `MAP` | PLAT | 0.90 |
| `ASSIGNMENT` | MORTGAGE | 0.70 |
| `SUBSTITUTION TRUSTEE` | DEED_OF_TRUST | 0.75 |
| `CAN` | RELEASE | 0.85 |
| `ESMT` | EASEMENT | 0.85 |

#### Key Abbreviation Handling

The rule-based classifier handles common abbreviations:
- **DEED_OF_TRUST**: `DT`, `D T`, `D/T`, `D-TR`, `DOT`, `TRS D`, `SUB TR`, `PRE D/T`
- **RELEASE**: `SAT`, `CAN`, `REL`, `D & REL`
- **SALE_DEED**: `QCD`, `Q C D`, `CORR D`, `TIM D`, `CMS D`
- **EASEMENT**: `ESMT`, `EASE`, `R-WAY`, `RW`
- **MORTGAGE**: `MTG`, `MTGE`, `ASGN`, `ASGMT`, `ASIGN`
- **LIEN**: `FC`, `UCC`, `F S`
- **PLAT**: `SUB D`, `DE`, `MAP/R`

#### Output Files

Two files are generated:

1. **`doc_type_mapping.json`** - Simple mapping dictionary (per PDF spec):
```json
{
  "DEED": "SALE_DEED",
  "DEED OF TRUST": "DEED_OF_TRUST",
  "DT": "DEED_OF_TRUST",
  "SATISFACTION": "RELEASE",
  "MAP": "PLAT",
  ...
}
```

2. **`doc_type_mapping_details.json`** - Detailed report with confidence scores:
```json
{
  "summary": {
    "total_types_processed": 338,
    "total_records_covered": 13877,
    "uncertain_mappings": 45,
    "api_calls_made": 17,
    "total_tokens_used": 0,
    "estimated_cost_usd": 0.0,
    "dry_run": false
  },
  "mappings": [
    {
      "original_type": "DEED OF TRUST",
      "standard_category": "DEED_OF_TRUST",
      "confidence": 0.9,
      "frequency": 1772,
      "is_uncertain": false,
      "reasoning": "Trust-based security instrument"
    }
  ]
}
```

---

## Scalability

### Memory Efficiency

- **JSONL Reader**: Processes line-by-line using generators
- **Aggregators**: Sample-based statistics (max 1000 examples per pattern)
- **No full file loading**: O(counties × samples) memory usage

### Performance Optimizations

1. **Streaming I/O**: Files are never fully loaded
2. **Counter-based Stats**: O(1) updates for frequency tracking
3. **Lazy Evaluation**: Patterns computed only when building output
4. **Connection Pooling**: HTTP sessions reused for scraping

### Horizontal Scaling

The architecture supports:
- **Partition by county**: Each county can be processed independently
- **Batch processing**: LLM calls can be parallelized
- **Distributed scraping**: Multiple scrapers with coordinated rate limiting

### Estimated Processing Times

| File Size | Records | Est. Time (Task 1) |
|-----------|---------|-------------------|
| 10 MB | 50,000 | ~30 seconds |
| 100 MB | 500,000 | ~5 minutes |
| 1 GB | 5,000,000 | ~50 minutes |

---

## Assumptions

### Data Assumptions

1. **JSONL Format**: Each line is valid JSON
2. **UTF-8 Encoding**: All text files use UTF-8
3. **Field Presence**: Fields may be null or missing
4. **Instrument Numbers**: `bp-` prefix indicates synthetic IDs
5. **Dates**: Can be parsed by dateutil in various formats

### Scraper Assumptions

1. **Public Access**: Website is publicly accessible
2. **Vue.js SPA**: Website uses a Vue.js frontend with a JSON API backend
3. **CriteriaSearch API**: Results returned as JSON via `/Home/CriteriaSearch` endpoint
4. **Rate Limiting**: 1-2 second delay between API calls is respectful for the server

### LLM Assumptions

1. **Ollama Availability**: Ollama server running locally or via Docker Compose
2. **Model Availability**: `llama3.1:8b` model pulled (`ollama pull llama3.1:8b`)
3. **Cost Model**: $0 - all processing is local
4. **Batch Size**: 20 types per call balances throughput and context quality
5. **Temperature**: 0 for deterministic, consistent classifications

---

## Error Handling

### JSONL Reader
- Skips malformed lines (configurable)
- Logs errors with line numbers
- Returns partial results on file errors

### Scraper
- Retries with exponential backoff (3 attempts)
- Handles network timeouts gracefully
- Returns partial results on pagination failures

### LLM Classifier
- Uses local Ollama LLM (no cloud API dependencies)
- Falls back to rule-based classification if Ollama unavailable
- Validates category names against allowed values
- Flags uncertain mappings (confidence < 0.7)

---

## License

This solution is provided for assessment purposes only.

---

## Author

Data Engineer Candidate  
Assessment Date: 2026-01-30
