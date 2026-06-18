# SimpleNursing → HubSpot Enrichment Pipeline

> **Welcome, Ms. John.** This README is your complete guide. Read it once top-to-bottom before touching any code. Every decision, every API, every bug we hit — it's all documented here. By the end, you'll be able to run this entire pipeline yourself.

<br>

## Table of Contents

| # | Section |
|---|---|
| 1 | [What This Project Does](#1-what-this-project-does) |
| 2 | [Why We Built It](#2-why-we-built-it) |
| 3 | [Full Architecture](#3-full-architecture) |
| 4 | [Phase 1 Workflow — Step by Step](#4-phase-1-workflow--step-by-step) |
| 5 | [Local Setup](#5-local-setup) |
| 6 | [Understanding the Data File](#6-understanding-the-data-file) |
| 7 | [HubSpot Setup](#7-hubspot-setup) |
| 8 | [Run the Pipeline](#8-run-the-pipeline) |
| 9 | [HubSpot Properties Reference](#9-hubspot-properties-reference) |
| 10 | [CSV → HubSpot Mapping](#10-csv--hubspot-mapping) |
| 11 | [APIs — Full Reference](#11-apis--full-reference) |
| 12 | [Phase 2 — S3 at Scale](#12-phase-2--s3-at-scale) |
| 13 | [Troubleshooting](#13-troubleshooting) |
| 14 | [People & Contacts](#14-people--contacts) |

---

<br>

## 1. What This Project Does

Before this project, HubSpot had basic contact info for nursing customers — name, email, phone. **That's it.**

Marketing could not answer questions like:
- Which nurses have a license expiring in the next 60 days?
- Who has already renewed? (Don't send them a renewal campaign!)
- Who has an active membership? (Don't sell them membership they already have)
- Which nurses are Psychiatric specialists vs. Pediatric?

**After this project**, every nursing contact in HubSpot has **51 enriched custom properties** covering:

```
License data     → number, state, issued date, renewal date
CE status        → credits required, completed, CE period end
Membership       → tier, status, start/end dates, billing cadence
Purchase history → what they bought, order amount, payment status
Direct mail      → what mailers they received, which campaign
LMS engagement   → which courses, completion status, credits earned
Specialty        → Psychiatric, Pediatric, Family, etc. (from web)
NPI number       → National Provider Identifier (their unique nurse ID)
```

This enables the marketing team to build **segmented campaigns** — the right message to the right nurse at the right time.

---

<br>

## 2. Why We Built It

In a meeting between **Sam Chaudhary** (GTM Engineering), **Madhankumar Pillay** (Product), **Prabhu** (Senior Leadership), **Veena Anantharam** (Data Architecture), **Sandesh Segu** (Data Engineering), and **Aliza John** (you), the goal was:

> *"End this quarter with HubSpot having the full view of the SimpleNursing database record so marketing can do proper segmentation and targeted campaigns."*

The customer data lives in **Colibri's Redshift data warehouse**, exported to **AWS S3** as flat CSV files.

**Key architecture decision made in the meeting:**

> Veena: *"My preference would be a file-based integration. It's not going to be performant if you go the individual API route. We're talking about 17 million records."*

So we use **S3 files → Python → HubSpot API**. No direct database connection. File-based only.

---

<br>

## 3. Full Architecture

```mermaid
flowchart TD
    subgraph SOURCE["📦 Data Sources"]
        XLS["Excel / CSV File\n(POC: 20 contacts)"]
        S3["AWS S3 Bucket\n(Full scale: 17M contacts)\ns3://prod-data-warehouse-redshift-\ncdp-data-lake-us-east-1/\nentity_matching/segmentation_flatview/"]
    end

    subgraph ENRICH["🔍 Enrichment APIs"]
        FE["FullEnrich API\nEmail → LinkedIn profile\napp.fullenrich.com"]
        EXA["Exa API\nWeb search → NPI, employer,\nspecialty, Doximity profile\napi.exa.ai"]
    end

    subgraph PIPELINE["⚙️ Pipeline (Python)"]
        P1["enrich.py\nParse Excel/CSV\nCreate HubSpot properties\nBatch upsert contacts"]
        P2["exa_enrich.py\nSearch each nurse online\nExtract NPI + employer"]
        P3["push_all.py\nFull 57-field push\nZero-value safe"]
        P4["verify_all.py\nConfirm all 51 properties\nexist + data matches"]
    end

    subgraph HUBSPOT["🟠 HubSpot CRM"]
        GROUP["Property Group:\nsn_enrichment"]
        PROPS["51 Custom Properties\nsn_license_number\nsn_ce_status\nsn_membership_status\nsn_exa_npi\n...etc"]
        CONTACTS["20 Contacts\n(sandbox portal 51121485)"]
    end

    subgraph PHASE2["🔜 Phase 2 (Pending COT-6043)"]
        AIRFLOW["Apache Airflow\nWeekly schedule\nDelta sync only"]
        S3PIPE["s3_pipeline.py\nChunked reads\n100 contacts/batch\nDelta logic"]
    end

    XLS -->|"CSV_FILE in .env"| P1
    P1 -->|"HubSpot Batch Upsert API"| CONTACTS
    P1 -->|"FullEnrich reverse lookup"| FE
    FE -->|"LinkedIn profiles"| P1
    CONTACTS --> P2
    P2 -->|"Exa neural search"| EXA
    EXA -->|"NPI, employer, specialty"| P2
    P2 -->|"Update contacts"| CONTACTS
    GROUP --> PROPS --> CONTACTS
    S3 -->|"After COT-6043 resolved"| AIRFLOW
    AIRFLOW --> S3PIPE
    S3PIPE -->|"Batch upsert 17M contacts"| CONTACTS

    style SOURCE fill:#e8f4f8,stroke:#2196F3
    style ENRICH fill:#fff3e0,stroke:#FF9800
    style PIPELINE fill:#e8f5e9,stroke:#4CAF50
    style HUBSPOT fill:#fce4ec,stroke:#E91E63
    style PHASE2 fill:#f3e5f5,stroke:#9C27B0
```

<br>

### Data Flow Summary

```mermaid
sequenceDiagram
    participant You
    participant Python
    participant HubSpot
    participant FullEnrich
    participant Exa

    You->>Python: python3 enrich.py
    Python->>Python: Read CSV (57 columns, 20 rows)
    Python->>HubSpot: Create property group 'sn_enrichment'
    Python->>HubSpot: Create 30 custom properties
    Python->>FullEnrich: POST /contact/reverse/email/bulk (20 emails)
    FullEnrich-->>Python: Poll every 10s → FINISHED (0 LinkedIn hits — B2C emails)
    Python->>HubSpot: POST /crm/v3/objects/contacts/batch/upsert (20 contacts)
    HubSpot-->>Python: 200 OK — 19 created, 1 updated

    You->>Python: python3 exa_enrich.py
    loop For each of 20 nurses
        Python->>Exa: POST /search (name + state + nurse)
        Exa-->>Python: NPI registry URL, Doximity profile, employer
        Python->>Python: Extract NPI number, specialty, employer
    end
    Python->>HubSpot: POST /crm/v3/objects/contacts/batch/upsert (20 contacts)
    HubSpot-->>Python: 200 OK — all 20 updated

    You->>Python: python3 verify_all.py
    Python->>HubSpot: GET /crm/v3/properties/contacts (check 51 props exist)
    Python->>HubSpot: GET each contact (verify data matches CSV)
    Python-->>You: ✓ All 51 properties exist. All 20 contacts verified.
```

---

<br>

## 4. Phase 1 Workflow — Step by Step

```mermaid
flowchart LR
    A([🗂️ Start:\nGet CSV file\nfrom Sam]) --> B

    subgraph SETUP["Step 1 — Setup"]
        B["git clone repo"]
        B --> C["uv venv --python 3.11\nsource .venv/bin/activate"]
        C --> D["uv pip install -r requirements.txt"]
        D --> E["cp .env.example .env\nFill in 4 API keys + CSV path"]
    end

    subgraph HUBSPOT_SETUP["Step 2 — HubSpot"]
        F["Create HubSpot Private App\n(Settings → Integrations → Private Apps)"]
        G["Enable required scopes:\ncrm.objects.contacts.write\ncrm.schemas.contacts.write"]
        F --> G
    end

    subgraph RUN["Step 3 — Run Pipeline"]
        H["python3 enrich.py --dry-run\n✓ Validate without writing"]
        H --> I["python3 enrich.py\n✓ Create 30 properties\n✓ Upsert 20 contacts"]
        I --> J["python3 push_all.py\n✓ Push all 57 fields\n✓ Zero-value safe"]
        J --> K["python3 exa_enrich.py\n✓ NPI + employer + specialty\nvia Exa web search"]
    end

    subgraph VERIFY["Step 4 — Verify"]
        L["python3 verify_all.py\n✓ 51 properties in schema\n✓ 20 contacts data matches"]
        M["python3 build_csv.py\n✓ Adds HubSpot property row\n✓ Adds hs_id column"]
    end

    E --> F
    G --> H
    K --> L
    L --> M
    M --> N([✅ Done!\nHubSpot sandbox\nfully enriched])

    style SETUP fill:#e3f2fd,stroke:#1976D2
    style HUBSPOT_SETUP fill:#fff8e1,stroke:#F9A825
    style RUN fill:#e8f5e9,stroke:#388E3C
    style VERIFY fill:#fce4ec,stroke:#C2185B
```

---

<br>

## 5. Local Setup

### Prerequisites

| Tool | Why needed | Install |
|---|---|---|
| Python 3.11+ | Run all pipeline scripts | [python.org](https://python.org) |
| `uv` | Fast Python package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git | Clone the repo | [git-scm.com](https://git-scm.com) |

### Clone and Install

```bash
# 1. Clone
git clone https://github.com/samcolibri/simplenursing-hubspot-enrichment.git
cd simplenursing-hubspot-enrichment

# 2. Create virtual environment (Python 3.11 specifically)
uv venv --python 3.11
source .venv/bin/activate        # Mac / Linux
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
uv pip install -r requirements.txt

# 4. Verify it worked
python3 -c "import openpyxl, requests; print('✓ Dependencies OK')"
```

### Configure Your `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in these 4 values:

```dotenv
HUBSPOT_API_KEY=pat-na1-...          # from HubSpot Private App
FULLENRICH_API_KEY=xxxxxxxx-...      # from app.fullenrich.com
EXA_API_KEY=xxxxxxxx-...             # from exa.ai
CSV_FILE=/Users/yourname/Downloads/HC_CE_Renewal_Nursing_Specialty_3(Nursing_Flat_File).csv
```

> ⚠️ **Never commit `.env`** — it contains secrets. It's already in `.gitignore`. Never remove it.

### Where to get each key

```mermaid
flowchart TD
    A["Need API Keys"] --> B & C & D

    B["HubSpot API Key\npat-na1-..."]
    B --> B1["1. Go to app.hubspot.com"]
    B1 --> B2["2. Settings (gear icon)"]
    B2 --> B3["3. Integrations → Private Apps"]
    B3 --> B4["4. Create / open your app"]
    B4 --> B5["5. Copy Access Token"]

    C["FullEnrich Key"]
    C --> C1["1. Go to app.fullenrich.com"]
    C1 --> C2["2. Dashboard → API Keys"]
    C2 --> C3["3. Copy your key"]

    D["Exa Key"]
    D --> D1["1. Go to exa.ai"]
    D1 --> D2["2. Sign in → Dashboard"]
    D2 --> D3["3. API Keys → Copy"]

    style B fill:#ff7a59,color:#fff,stroke:#ff7a59
    style C fill:#4a9eff,color:#fff,stroke:#4a9eff
    style D fill:#6c5ce7,color:#fff,stroke:#6c5ce7
```

---

<br>

## 6. Understanding the Data File

The source file is: **`HC_CE_Renewal_Nursing_Specialty_3(Nursing_Flat_File).csv`**

> 📌 This file is **not in the repo** — it contains customer PII (personal identifiable information). Ask Sam Chaudhary for a copy.

### File Structure

The file has an unusual **3-row header** (most CSVs have 1):

```
Row 1  →  Section names       PERSON | | | | PERSON SOURCE | | LICENSE | ...
Row 2  →  CSV field names     resolved_person_id | person_name | person_email | ...
Row 3  →  HubSpot prop names  sn_person_id | firstname + lastname | email | ...  ← we added this
Row 4+ →  Actual data         4001877 | Annmarie Shoemaker | ANNMARIE@... | ...
```

### The 9 Data Sections

```mermaid
mindmap
  root((Nursing Flat File\n57 columns\n20 contacts))
    PERSON
      resolved_person_id
      person_name
      person_email
      person_address
      person_phone
      created_at
    PERSON SOURCE
      source_name
      source_platform
      native_person_id
      brand
    LICENSE
      license_number
      state
      profession
      license_issued_date
      est_renewal_date
    LMS ENGAGEMENT
      course_id
      course_title
      completion_status
      credits_earned
      last_activity_date
    PURCHASE HISTORY
      order_id
      product_name
      order_amount
      order_date
      payment_status
    MEMBERSHIP
      membership_tier
      mem_status
      mem_start_date
      mem_end_date
    MARKETING CONSENT
      channel
      consent_status
      consent_timestamp
    CE COMPLETION
      ce_period
      credits_completed
      ce_status
      period_end_date
    DIRECT MAIL
      send_channel
      send_date
      creative_version
      book_title_sent
    SPECIALTY
      speciality
      nurse_professions
```

---

<br>

## 7. HubSpot Setup

### Creating a Private App (one-time setup)

```mermaid
flowchart TD
    A["Go to app.hubspot.com"] --> B["Click Settings ⚙️"]
    B --> C["Integrations → Private Apps"]
    C --> D["Click 'Create a private app'"]
    D --> E["Name it:\nSimpleNursing Enrichment Pipeline"]
    E --> F["Click the Scopes tab"]
    F --> G["Enable these scopes ↓"]

    G --> H["crm.objects.contacts.read\ncrm.objects.contacts.write"]
    G --> I["crm.schemas.contacts.read\ncrm.schemas.contacts.write"]
    G --> J["crm.objects.custom.read\ncrm.objects.custom.write\ncrm.schemas.custom.read\ncrm.schemas.custom.write"]

    H & I & J --> K["Click 'Create app'"]
    K --> L["Copy the Access Token\npat-na1-xxxxxxxx..."]
    L --> M["Paste into .env as\nHUBSPOT_API_KEY"]

    style G fill:#fff3e0,stroke:#FF9800
    style L fill:#e8f5e9,stroke:#4CAF50
```

### Sandbox vs Production

| | Sandbox | Production |
|---|---|---|
| **Portal ID** | `51121485` | Different ID |
| **Used for** | Testing (our POC is here) | Real marketing contacts |
| **Risk** | None — safe to experiment | High — real customers |
| **Status** | ✅ Our 20 contacts are here | ⏳ Next phase |

To check which portal your token connects to:
```bash
curl -s "https://api.hubapi.com/integrations/v1/me" \
  -H "Authorization: Bearer $HUBSPOT_API_KEY" | python3 -m json.tool
# Look for "portalId" and "accountType" in the output
```

### How to See Custom Properties in HubSpot UI

After running the pipeline, custom properties won't show automatically. Here's how to view them:

```mermaid
flowchart LR
    A["Open any contact\nin HubSpot"] --> B["Scroll to\n'About this contact'\nsidebar"]
    B --> C["Click\n'View all properties'\nat bottom"]
    C --> D["Type 'sn_' in\nthe search box"]
    D --> E["All 51 enriched\nproperties appear ✓"]

    E --> F{Want them\npermanently visible?}
    F -->|Yes| G["Click Actions →\nEdit properties"]
    G --> H["Search 'SimpleNursing'"]
    H --> I["Select properties\nyou want pinned"]
    I --> J["Save → they show\non every contact"]

    style E fill:#e8f5e9,stroke:#4CAF50
    style J fill:#e8f5e9,stroke:#4CAF50
```

---

<br>

## 8. Run the Pipeline

### The Scripts and What They Do

```mermaid
flowchart TD
    subgraph SCRIPTS["Scripts (run in this order)"]
        S1["📄 enrich.py\nMain pipeline\nExcel → 30 properties → 20 contacts"]
        S2["📄 push_all.py\nFull push\nAll 57 CSV fields, zero-value safe"]
        S3["📄 exa_enrich.py\nWeb enrichment\nNPI, employer, specialty per nurse"]
        S4["📄 verify_all.py\nVerification\n51 schema check + 20 data check"]
        S5["📄 build_csv.py\nCSV update\nAdd HubSpot prop row + hs_id column"]
        S6["📄 audit.py\nAudit\nCSV field counts vs HubSpot field counts"]
    end

    S1 --> S2 --> S3 --> S4 --> S5

    style S1 fill:#bbdefb,stroke:#1976D2
    style S2 fill:#bbdefb,stroke:#1976D2
    style S3 fill:#c8e6c9,stroke:#388E3C
    style S4 fill:#fff9c4,stroke:#F9A825
    style S5 fill:#f8bbd0,stroke:#C2185B
    style S6 fill:#e1bee7,stroke:#7B1FA2
```

### Step-by-Step Commands

```bash
# ── Step 1: Dry run (validates everything, writes nothing) ──────────────────
python3 enrich.py --dry-run --skip-fullenrich
# Expected: 20 contacts validated, 0 errors

# ── Step 2: Live run — creates properties and upserts contacts ──────────────
python3 enrich.py --skip-fullenrich
# Expected: 30 properties created, 20 contacts upserted ✓

# ── Step 3: Push ALL 57 fields (handles zero values correctly) ──────────────
python3 push_all.py
# Expected: 0 new properties (already exist), 20 contacts updated ✓

# ── Step 4: Exa enrichment — NPI, employer, specialty ──────────────────────
python3 exa_enrich.py
# Expected: 20/20 contacts enriched, 6 new Exa properties added ✓

# ── Step 5: Verify everything landed correctly ──────────────────────────────
python3 verify_all.py
# Expected: ✓ All 51 properties exist. ✓ All 20 contacts verified.

# ── Step 6: Update CSV with HubSpot property names + HubSpot IDs ────────────
python3 build_csv.py
# Expected: CSV updated with row 3 (HubSpot props) + hubspot_id last column ✓
```

### What Good Output Looks Like

```
==========================================================
  SimpleNursing HubSpot Enrichment Pipeline
  Mode: LIVE
==========================================================

[13:38:14] Loaded 20 records
[13:38:14] FullEnrich: skipped (--skip-fullenrich)
[13:38:14] Setting up HubSpot properties...
[13:38:15] Property group 'sn_enrichment' already exists
[13:38:15] Properties: 30 created, 0 already existed
[13:38:15]
Upserting 20 contacts (batch mode)...
[13:38:17]   ✓ annmarieshoemaker@yahoo.com (created)
[13:38:17]   ✓ rghanson58@gmail.com (created)
[13:38:17]   ✓ debdawson@ymail.com (created)
...
==========================================================
  RESULTS
==========================================================
  Total records   : 20
  Upserted ok     : 20    ← must be 20
  Errors          : 0     ← must be 0
  FullEnrich hits : 0     ← OK (personal emails, B2C)
==========================================================
```

---

<br>

## 9. HubSpot Properties Reference

All 51 properties live in a group called `sn_enrichment` (label: **SimpleNursing Enrichment**).

### Property Type Reference

| HubSpot Type | What it means | Example |
|---|---|---|
| `string` | Plain text | `"RN628427"` |
| `number` | Numeric value | `39.0` |
| `date` | Epoch milliseconds at midnight UTC | `1749686400000` |
| `enumeration` | Dropdown with fixed options | `"Active"` / `"Expired"` |

> ⚠️ **Critical gotcha on dates:** HubSpot date fields do NOT accept `"2026-06-12"`. They require epoch milliseconds. Convert like this:
> ```python
> import calendar
> from datetime import datetime
> d = datetime(2026, 6, 12)
> epoch_ms = int(calendar.timegm(d.timetuple()) * 1000)  # → 1749686400000
> ```

### All 51 Properties by Section

```mermaid
flowchart TD
    GROUP["sn_enrichment\nProperty Group"]

    GROUP --> P1 & P2 & P3 & P4 & P5 & P6 & P7 & P8 & P9 & P10

    subgraph P1["👤 PERSON SOURCE (6)"]
        direction LR
        p1a["sn_person_id"] & p1b["sn_native_id"] & p1c["sn_brand"]
        p1d["sn_source_name"] & p1e["sn_source_platform"] & p1f["sn_created_at"]
    end

    subgraph P2["🪪 LICENSE (6)"]
        direction LR
        p2a["sn_license_id"] & p2b["sn_license_number"] & p2c["sn_license_state"]
        p2d["sn_profession"] & p2e["sn_license_issued_date"] & p2f["sn_est_renewal_date"]
    end

    subgraph P3["📚 LMS ENGAGEMENT (6)"]
        direction LR
        p3a["sn_course_id"] & p3b["sn_course_title"] & p3c["sn_lms_completion_status"]
        p3d["sn_credits_earned"] & p3e["sn_last_activity_date"] & p3f["sn_lms_source"]
    end

    subgraph P4["🛒 PURCHASE HISTORY (7)"]
        direction LR
        p4a["sn_order_id"] & p4b["sn_product_name"] & p4c["sn_product_category"]
        p4d["sn_order_amount"] & p4e["sn_order_date"] & p4f["sn_payment_status"] & p4g["sn_purchase_source"]
    end

    subgraph P5["💳 MEMBERSHIP (6)"]
        direction LR
        p5a["sn_membership_status\n(Active/Expired/Cancelled)"] & p5b["sn_membership_tier"] & p5c["sn_membership_cadence"]
        p5d["sn_mem_brand"] & p5e["sn_mem_start_date"] & p5f["sn_mem_end_date"]
    end

    subgraph P6["📬 MARKETING CONSENT (4)"]
        direction LR
        p6a["sn_channel"] & p6b["sn_consent_status\n(Opt-In/Opt-Out)"]
        p6c["sn_consent_brand"] & p6d["sn_consent_timestamp"]
    end

    subgraph P7["🎓 CE COMPLETION (4)"]
        direction LR
        p7a["sn_ce_period"] & p7b["sn_credits_completed"]
        p7c["sn_ce_status\n(Not Started/In Progress/Complete)"] & p7d["sn_ce_period_end_date"]
    end

    subgraph P8["📮 DIRECT MAIL (6)"]
        direction LR
        p8a["sn_send_channel"] & p8b["sn_send_brand"] & p8c["sn_send_date"]
        p8d["sn_creative_version"] & p8e["sn_book_title_sent"] & p8f["sn_book_sent_date"]
    end

    subgraph P9["🔍 EXA ENRICHMENT (6)"]
        direction LR
        p9a["sn_exa_employer"] & p9b["sn_exa_specialty"] & p9c["sn_exa_npi"]
        p9d["sn_exa_profile_url"] & p9e["sn_exa_profile_type"] & p9f["sn_exa_enriched_at"]
    end

    subgraph P10["🕐 META (1)"]
        p10a["sn_enriched_at"]
    end

    style GROUP fill:#E91E63,color:#fff,stroke:#C2185B
    style P1 fill:#e3f2fd,stroke:#1976D2
    style P2 fill:#e8f5e9,stroke:#388E3C
    style P3 fill:#fff8e1,stroke:#F9A825
    style P4 fill:#fce4ec,stroke:#C2185B
    style P5 fill:#f3e5f5,stroke:#7B1FA2
    style P6 fill:#e0f2f1,stroke:#00796B
    style P7 fill:#fff3e0,stroke:#E65100
    style P8 fill:#fafafa,stroke:#616161
    style P9 fill:#e8eaf6,stroke:#3949AB
    style P10 fill:#efebe9,stroke:#5D4037
```

> These properties also cross-map to existing standard HubSpot fields:
> - `sn_license_number` → also writes `license_number`
> - `sn_est_renewal_date` → also writes `education_renewal_date_us_nurses`
> - `sn_mem_end_date` → also writes `membership_end_date`
> - `sn_license_state` → also writes `license_state_abbreviation`

---

<br>

## 10. CSV → HubSpot Mapping

```mermaid
flowchart LR
    subgraph CSV["📄 CSV Columns"]
        c1["resolved_person_id"]
        c2["person_name"]
        c3["person_email"]
        c4["person_address"]
        c5["person_phone"]
        c6["created_at"]
        c7["source_name"]
        c8["native_person_id"]
        c9["brand"]
        c10["license_number"]
        c11["state"]
        c12["est_renewal_date"]
        c13["mem_status"]
        c14["credits_completed"]
        c15["ce_status"]
        c16["order_amount"]
        c17["send_date"]
    end

    subgraph HS["🟠 HubSpot Properties"]
        h1["sn_person_id"]
        h2["firstname + lastname"]
        h3["email"]
        h4["address"]
        h5["phone"]
        h6["sn_created_at"]
        h7["sn_source_name"]
        h8["sn_native_id"]
        h9["sn_brand"]
        h10["sn_license_number"]
        h11["sn_license_state"]
        h12["sn_est_renewal_date"]
        h13["sn_membership_status"]
        h14["sn_credits_completed"]
        h15["sn_ce_status"]
        h16["sn_order_amount"]
        h17["sn_send_date"]
    end

    c1 --> h1
    c2 --> h2
    c3 --> h3
    c4 --> h4
    c5 --> h5
    c6 --> h6
    c7 --> h7
    c8 --> h8
    c9 --> h9
    c10 --> h10
    c11 --> h11
    c12 --> h12
    c13 --> h13
    c14 --> h14
    c15 --> h15
    c16 --> h16
    c17 --> h17
```

### Full Mapping Table

| Section | CSV Column | HubSpot Property | Type | Notes |
|---|---|---|---|---|
| PERSON | `resolved_person_id` | `sn_person_id` | string | |
| PERSON | `person_name` | `firstname` + `lastname` | string | Split on last space |
| PERSON | `person_email` | `email` | string | Lowercased |
| PERSON | `person_address` | `address` | string | |
| PERSON | `person_phone` | `phone` | string | |
| PERSON | `created_at` | `sn_created_at` | date | → epoch ms |
| PERSON SOURCE | `source_name` | `sn_source_name` | string | |
| PERSON SOURCE | `source_platform` | `sn_source_platform` | string | e.g. NetSuite |
| PERSON SOURCE | `native_person_id` | `sn_native_id` | string | e.g. CUS5089562 |
| PERSON SOURCE | `brand` | `sn_brand` | string | e.g. Elite |
| LICENSE | `resolved_license_id` | `sn_license_id` | string | |
| LICENSE | `license_number` | `sn_license_number` + `license_number` | string | dual-write |
| LICENSE | `state` | `sn_license_state` + `license_state_abbreviation` | string | dual-write |
| LICENSE | `profession` | `sn_profession` | string | |
| LICENSE | `license_issued_date` | `sn_license_issued_date` | date | → epoch ms |
| LICENSE | `est_renewal_date` | `sn_est_renewal_date` + `education_renewal_date_us_nurses` | date | dual-write |
| LMS | `course_id` | `sn_course_id` | string | |
| LMS | `course_title` | `sn_course_title` | string | |
| LMS | `completion_status` | `sn_lms_completion_status` | string | |
| LMS | `credits_earned` | `sn_credits_earned` | number | ⚠️ 0 is valid |
| LMS | `last_activity_date` | `sn_last_activity_date` | date | → epoch ms |
| LMS | `lms_source` | `sn_lms_source` | string | |
| PURCHASE | `order_id` | `sn_order_id` | string | |
| PURCHASE | `product_name` | `sn_product_name` | string | |
| PURCHASE | `product_category` | `sn_product_category` | string | |
| PURCHASE | `order_amount` | `sn_order_amount` | number | ⚠️ 0 is valid |
| PURCHASE | `order_date` | `sn_order_date` | date | → epoch ms |
| PURCHASE | `payment_status` | `sn_payment_status` | string | |
| PURCHASE | `purchase_source` | `sn_purchase_source` | string | |
| MEMBERSHIP | `membership_billing_cadence` | `sn_membership_cadence` | string | |
| MEMBERSHIP | `membership_tier` | `sn_membership_tier` | string | |
| MEMBERSHIP | `mem_brand` | `sn_mem_brand` | string | |
| MEMBERSHIP | `mem_start_date` | `sn_mem_start_date` | date | → epoch ms |
| MEMBERSHIP | `mem_end_date` | `sn_mem_end_date` + `membership_end_date` | date | dual-write |
| MEMBERSHIP | `mem_status` | `sn_membership_status` | enum | Active/Expired/Cancelled |
| CONSENT | `channel` | `sn_channel` | string | |
| CONSENT | `consent_status` | `sn_consent_status` | enum | Opt-In/Opt-Out |
| CONSENT | `consent_brand` | `sn_consent_brand` | string | |
| CONSENT | `consent_timestamp` | `sn_consent_timestamp` | date | → epoch ms |
| CE | `ce_period` | `sn_ce_period` | string | |
| CE | `credits_completed` | `sn_credits_completed` | number | ⚠️ 0 is valid |
| CE | `ce_status` | `sn_ce_status` | enum | Not Started/In Progress/Complete |
| CE | `period_end_date` | `sn_ce_period_end_date` | date | → epoch ms |
| DIRECT MAIL | `send_channel` | `sn_send_channel` | string | |
| DIRECT MAIL | `send_brand` | `sn_send_brand` | string | |
| DIRECT MAIL | `send_date` | `sn_send_date` | date | → epoch ms |
| DIRECT MAIL | `creative_version` | `sn_creative_version` | string | |
| DIRECT MAIL | `book_title_sent` | `sn_book_title_sent` | string | |
| DIRECT MAIL | `book_sent_date` | `sn_book_sent_date` | date | → epoch ms |
| SPECIALTY | `speciality` | `sn_specialty` | string | No data in POC |
| SPECIALTY | `nurse_professions` | `sn_nurse_professions` | string | No data in POC |

---

<br>

## 11. APIs — Full Reference

### HubSpot API

```mermaid
flowchart TD
    HS["HubSpot API\nhttps://api.hubapi.com\nAuth: Authorization: Bearer pat-na1-..."]

    HS --> A["Check portal info\nGET /integrations/v1/me"]
    HS --> B["List contacts\nGET /crm/v3/objects/contacts"]
    HS --> C["Get one contact by email\nGET /crm/v3/objects/contacts/{email}\n?idProperty=email"]
    HS --> D["★ Batch upsert contacts\nPOST /crm/v3/objects/contacts/batch/upsert\nCreates OR updates — the key endpoint"]
    HS --> E["Create property group\nPOST /crm/v3/properties/contacts/groups"]
    HS --> F["Create custom property\nPOST /crm/v3/properties/contacts"]
    HS --> G["List all properties\nGET /crm/v3/properties/contacts?limit=500"]

    style D fill:#4CAF50,color:#fff,stroke:#388E3C
```

**Batch upsert — the most important API call:**

```python
response = requests.post(
    "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert",
    headers={"Authorization": "Bearer pat-na1-...", "Content-Type": "application/json"},
    json={
        "inputs": [
            {
                "id": "jane@example.com",      # match on this value
                "idProperty": "email",          # match using this field
                "properties": {                 # set all these fields
                    "email": "jane@example.com",
                    "firstname": "Jane",
                    "sn_license_number": "RN123456",
                    "sn_ce_status": "In Progress",
                    "sn_order_amount": 99.99
                }
            }
            # up to 100 contacts per call
        ]
    }
)
# 200 = success. Check response["results"] for individual outcomes.
```

**Create a property:**

```python
requests.post(
    "https://api.hubapi.com/crm/v3/properties/contacts",
    headers={"Authorization": "Bearer pat-na1-..."},
    json={
        "name": "sn_license_number",
        "label": "SN: License Number",
        "type": "string",           # string | number | date | enumeration
        "fieldType": "text",        # text | number | date | select
        "groupName": "sn_enrichment"
    }
)
```

---

### FullEnrich API

**What it does:** Give it emails → it finds their LinkedIn profiles.
**Why 0 hits for us:** Our nurses use personal emails (Yahoo, Gmail, Hotmail). FullEnrich works for corporate emails like `jane@hospital.com`.

```mermaid
sequenceDiagram
    participant Python
    participant FullEnrich

    Python->>FullEnrich: POST /contact/reverse/email/bulk
    Note over Python,FullEnrich: {"name": "batch-1", "data": [{"email": "..."}]}
    FullEnrich-->>Python: {"enrichment_id": "abc-123"}

    loop Poll every 10 seconds
        Python->>FullEnrich: GET /contact/reverse/email/bulk/abc-123
        FullEnrich-->>Python: {"status": "IN_PROGRESS"}
    end

    FullEnrich-->>Python: {"status": "FINISHED", "results": [...]}
```

---

### Exa API

**What it does:** Semantic web search — finds nurses by name+state across LinkedIn, Doximity, NPI registries.
**Cost:** ~$0.007 per search. 20 nurses = $0.14.

```python
response = requests.post(
    "https://api.exa.ai/search",
    headers={"x-api-key": "your-exa-key"},
    json={
        "query": "Deborah Lynn Dawson registered nurse Texas",
        "num_results": 5,
        "type": "neural",
        "include_domains": [
            "linkedin.com",
            "doximity.com",
            "opennpi.com",       # NPI registry with employer data
            "opengovus.com",     # Government license records
            "npino.com"          # NPI with specialty info
        ],
        "contents": {"text": {"max_characters": 800}}
    }
)

# Each result has: title, url, score (0-1), text (extracted content)
# We parse the text for: NPI number, employer name, specialty keywords
```

**What we found for our 20 nurses:**

| Nurse | Found |
|---|---|
| Deborah Dawson | NPI `1972630978` · Specialty: **Psychiatric** |
| Renee Hanson | **LinkedIn profile** · Employer: Halifax Health Medical Center |
| Tina King-Pemberton | NPI `1013330109` · **Family NP** specialty |
| Corazon Barcelona | NPI + **Acute Care** + LinkedIn |
| Tosha Vaughn | NPI + **Pediatric** specialty |
| Shawn Taylor | NPI + **Home Health** specialty |

---

<br>

## 12. Phase 2 — S3 at Scale

### Current Status

```mermaid
flowchart LR
    A["✅ Phase 1 Complete\n20 contacts\nHubSpot sandbox\n51 properties validated"] -->|"COT-6043\nresolved by\nPrakhar Jadon"| B["🔜 Phase 2\n17M contacts\nHubSpot production\nWeekly Airflow sync"]
```

### The Jira Ticket

| Field | Value |
|---|---|
| **Ticket** | [COT-6043](https://colibrigroup.atlassian.net/browse/COT-6043) |
| **Assigned to** | Prakhar Jadon |
| **Watching** | Austin Ellingwood |
| **Priority** | Critical |
| **Initiative** | 375 — Build Segments/Audiences leveraging Data Warehouse |

DevOps will provide `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` via 1Password. Set them in `.env`.

### S3 Path

```
Bucket:  prod-data-warehouse-redshift-cdp-data-lake-us-east-1
Prefix:  entity_matching/segmentation_flatview/
File:    hc_ce_renewal_segmentation_flatview_000.csv
Region:  us-east-1
```

### Phase 2 Architecture

```mermaid
flowchart TD
    A["Airflow DAG\nSchedule: Monday 6am"] --> B["s3_pipeline.py\n(to be built)"]

    B --> C["1. List files in S3 prefix"]
    C --> D["2. Download CSV chunk\n10,000 rows at a time"]
    D --> E["3. Delta check\nCompare with last_synced_at\nSkip unchanged records"]
    E --> F{New or\nchanged?}
    F -->|Yes| G["4. Build HubSpot payload\nSame mapping as Phase 1"]
    F -->|No| H["Skip — save API calls"]
    G --> I["5. Batch upsert\n100 contacts per API call"]
    I --> J{More chunks?}
    J -->|Yes| D
    J -->|No| K["6. Log completion\nUpdate sync timestamp"]

    style A fill:#ff7043,color:#fff,stroke:#e64a19
    style E fill:#fff9c4,stroke:#f9a825
    style F fill:#e3f2fd,stroke:#1976D2
    style I fill:#e8f5e9,stroke:#388E3C
```

**Why delta sync?** At 17M records, pushing everything every time would:
- Take ~47 hours at 100 contacts/second
- Cost significant HubSpot API quota
- Be wasteful — most records don't change week-to-week

Delta sync = only push records where something changed since last run.

---

<br>

## 13. Troubleshooting

```mermaid
flowchart TD
    ERROR["Got an error?"] --> A & B & C & D & E

    A["403 — Missing scopes"]
    A --> A1["Go to HubSpot → Private Apps\nAdd crm.objects.contacts.write\nand crm.schemas.contacts.write"]

    B["404 — resource not found\n(on PATCH)"]
    B --> B1["You used PATCH on a contact\nthat doesn't exist yet.\nSwitch to batch/upsert endpoint:\nPOST .../contacts/batch/upsert"]

    C["Property shows None\nor date is wrong"]
    C --> C1["Date issue: use epoch ms not string\nimport calendar\nepoch = calendar.timegm(d.timetuple()) * 1000"]
    C --> C2["Zero value issue: use\nif v is not None:\nnot just\nif v:"]

    D["FullEnrich returns 0 results"]
    D --> D1["Expected for personal emails\n(Gmail, Yahoo, Hotmail)\nUse Exa for these contacts instead"]

    E["ERROR: CSV_FILE not set"]
    E --> E1["Your .env file is missing CSV_FILE\nSet it to the full path of\nHC_CE_Renewal_Nursing_Specialty_3\n(Nursing_Flat_File).csv"]

    style ERROR fill:#f44336,color:#fff,stroke:#d32f2f
    style A fill:#fff3e0,stroke:#FF9800
    style B fill:#fff3e0,stroke:#FF9800
    style C fill:#fff3e0,stroke:#FF9800
    style D fill:#fff3e0,stroke:#FF9800
    style E fill:#fff3e0,stroke:#FF9800
```

---

<br>

## 14. People & Contacts

| Name | Role | Email |
|---|---|---|
| **Sam Chaudhary** | GTM Engineering — project lead | sam.chaudhary@colibrigroup.com |
| **Aliza John** | Intern — that's you! | — |
| **Madhankumar Pillay** | Product owner | — |
| **Prabhu** | Senior leadership | — |
| **Veena Anantharam** | Data architecture | — |
| **Sandesh Segu** | Data engineering | — |
| **Prakhar Jadon** | DevOps — S3 access (COT-6043) | — |
| **Austin Ellingwood** | DevOps — cc on COT-6043 | — |

---

<br>

## Quick Reference Card

| What | Command |
|---|---|
| Dry run (safe test) | `python3 enrich.py --dry-run --skip-fullenrich` |
| Push contacts | `python3 enrich.py --skip-fullenrich` |
| Push all 57 fields | `python3 push_all.py` |
| Web enrichment | `python3 exa_enrich.py` |
| Verify everything | `python3 verify_all.py` |
| Update CSV | `python3 build_csv.py` |
| Audit field counts | `python3 audit.py` |
| Check portal info | `curl -s https://api.hubapi.com/integrations/v1/me -H "Authorization: Bearer $HUBSPOT_API_KEY"` |

---

<br>

> *Built by Sam Chaudhary with Claude Code.*
> *Questions? Open an issue on this repo or email sam.chaudhary@colibrigroup.com*
