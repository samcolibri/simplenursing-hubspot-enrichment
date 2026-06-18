# SimpleNursing HubSpot Enrichment Pipeline

> **Hey Aliza 👋** — this README is written specifically for you. It covers everything we built, every decision we made, every API we used, and exactly how to run the whole thing from your laptop. Read it top to bottom once before you touch any code.

---

## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [Why We Built It](#2-why-we-built-it)
3. [Architecture Overview](#3-architecture-overview)
4. [Local Setup](#4-local-setup)
5. [Data Source: The Excel / CSV File](#5-data-source-the-excel--csv-file)
6. [HubSpot Setup](#6-hubspot-setup)
7. [Step 1 — Run the Main Enrichment Pipeline](#7-step-1--run-the-main-enrichment-pipeline)
8. [Step 2 — Run Exa Web Enrichment](#8-step-2--run-exa-web-enrichment)
9. [Step 3 — Verify Everything](#9-step-3--verify-everything)
10. [Step 4 — Update the CSV with HubSpot IDs](#10-step-4--update-the-csv-with-hubspot-ids)
11. [All HubSpot Properties We Created](#11-all-hubspot-properties-we-created)
12. [CSV Column → HubSpot Property Mapping](#12-csv-column--hubspot-property-mapping)
13. [APIs Used — Full Reference](#13-apis-used--full-reference)
14. [Phase 2: S3 Pipeline (Coming Next)](#14-phase-2-s3-pipeline-coming-next)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. What This Project Does

We take a flat file of **nursing customer records** (from Colibri's data warehouse) and push all the data into **HubSpot CRM** as enriched contact properties.

Before this project, HubSpot had basic contact info (name, email, phone). After this project, every nursing contact in HubSpot has:

- Their **state nursing license** number, issue date, and renewal date
- **CE (Continuing Education) completion** status and credits earned
- **Membership** tier, status, start/end dates
- **Purchase history** — what courses they bought, how much they paid
- **Direct mail** campaign history — what mailers they received
- **Specialty** (Psychiatric, Pediatric, Family, etc.) discovered via web search
- **NPI number** (National Provider Identifier — the unique ID for every licensed nurse)
- **LinkedIn profile / Doximity profile** URL

This lets the marketing team do **proper segmentation**. Example: don't send a membership upsell email to someone who already has an active membership. Don't send a renewal reminder to someone who already renewed. These things were impossible before because HubSpot didn't have the data.

---

## 2. Why We Built It

In a meeting with **Madhankumar Pillay** (product), **Prabhu** (senior stakeholder), and **Aliza John** (you!), the goal was defined:

> "End this quarter with HubSpot having the full view of the SimpleNursing database record so marketing can do proper segmentation and targeted campaigns."

The data lives in Colibri's **Redshift data warehouse**, exported as flat files to **S3**. The decision was made to use a **file-based integration** (not a direct database connection) because:

1. Redshift is a data warehouse — tight coupling is bad practice
2. We're talking 17 million records — individual API calls won't scale
3. File-based allows delta sync (only push what changed)

We started with a **20-record POC** using an Excel file Aliza had, validated the full data mapping, then built the pipeline. The POC is live in the HubSpot **sandbox** (portal 51121485). The next phase scales it to the full 17M records via S3.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        PHASE 1 (DONE ✓)                         │
│                                                                  │
│  Excel/CSV File  ──►  enrich.py  ──►  HubSpot CRM               │
│  (20 contacts)        (maps all       (51 custom                 │
│                        57 fields)      properties)               │
│                                                                  │
│  + FullEnrich  ──►  Reverse email lookup ──► LinkedIn profiles  │
│  + Exa API     ──►  Web search per nurse ──► NPI, employer,     │
│                                              specialty           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      PHASE 2 (IN PROGRESS)                       │
│                                                                  │
│  AWS S3 Bucket                                                   │
│  (17M records)  ──►  s3_pipeline.py  ──►  HubSpot CRM           │
│                       - chunked reads      (batch upsert         │
│                       - delta logic         by email)            │
│                       - batch upsert                             │
│                                                                  │
│  Orchestration: Airflow (scheduled, weekly refresh)              │
│  S3 Access: Jira ticket COT-6043 (assigned to Prakhar Jadon)    │
└─────────────────────────────────────────────────────────────────┘
```

**Key concept — HubSpot Batch Upsert:**
We use `POST /crm/v3/objects/contacts/batch/upsert` with `idProperty: "email"`. This means:
- If a contact with that email **exists** → it updates them
- If a contact with that email **doesn't exist** → it creates them

One API call handles both cases. No need to check first. This is how we scale to 17M.

---

## 4. Local Setup

### Prerequisites
- Python 3.11+ (we use `uv` to manage the virtual environment)
- `uv` installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Git

### Clone and install

```bash
git clone https://github.com/samcolibri/simplenursing-hubspot-enrichment.git
cd simplenursing-hubspot-enrichment

# Create virtual environment with Python 3.11
uv venv --python 3.11

# Activate it
source .venv/bin/activate   # Mac/Linux
# .venv\Scripts\activate    # Windows

# Install dependencies
uv pip install -r requirements.txt
```

### Configure credentials

```bash
cp .env.example .env
```

Now open `.env` and fill in the values. You need:

| Variable | Where to get it |
|---|---|
| `HUBSPOT_API_KEY` | HubSpot → Settings → Integrations → Private Apps → your app → Access Token |
| `FULLENRICH_API_KEY` | fullenrich.com → Dashboard → API Keys |
| `EXA_API_KEY` | exa.ai → Dashboard → API Keys |
| `EXCEL_FILE` | Path to `HC_CE_Renewal_Nursing_Specialty_3.xlsx` on your laptop |

> **Never commit your `.env` file.** It's in `.gitignore`. Never remove it from there.

### Verify setup

```bash
python3 -c "import openpyxl, requests; print('All dependencies OK')"
```

---

## 5. Data Source: The Excel / CSV File

The source file is: `HC_CE_Renewal_Nursing_Specialty_3.xlsx`
Sheet name: `Nursing_Flat_File`

The file has **3 header rows** (unusual — pay attention to this):

| Row | Contains |
|---|---|
| Row 1 | **Section names** — PERSON, LICENSE, LMS ENGAGEMENT, PURCHASE HISTORY, etc. |
| Row 2 | **CSV field names** — `resolved_person_id`, `person_name`, `person_email`, etc. |
| Row 3 | **HubSpot property names** ← we added this row (see Step 4) |
| Rows 4+ | **Actual data** — one row per customer |

Total: **57 columns** across 9 sections, **20 contacts** in the POC file.

The sections are:

```
PERSON               → who they are (name, email, phone, address)
PERSON SOURCE        → where they came from (NetSuite, brand = Elite)
LICENSE              → their nursing license (number, state, issue/renewal date)
LMS ENGAGEMENT       → what courses they've taken
PURCHASE HISTORY     → what they've bought and for how much
MEMBERSHIP           → membership tier, status, start/end dates
MARKETING CONSENT    → Opt-In/Out, channel, timestamp
CE COMPLETION        → continuing education credits required/completed
DIRECT MAIL          → what physical mailers they've received
SPECIALTY            → nursing specialty (empty in POC file)
```

---

## 6. HubSpot Setup

### Creating a Private App (do this once)

1. Log in to HubSpot
2. Go to **Settings** (gear icon top right)
3. **Integrations** → **Private Apps**
4. Click **Create a private app**
5. Name it: `SimpleNursing Enrichment Pipeline`
6. Go to the **Scopes** tab and enable ALL of the following:
   - `crm.objects.contacts.read` + `crm.objects.contacts.write`
   - `crm.schemas.contacts.read` + `crm.schemas.contacts.write`
   - `crm.objects.custom.read` + `crm.objects.custom.write`
   - `crm.schemas.custom.read` + `crm.schemas.custom.write`
   - `crm.lists.read` + `crm.lists.write`
7. Click **Create app**
8. Copy the **Access Token** — it starts with `pat-na1-...`
9. Paste it into your `.env` as `HUBSPOT_API_KEY`

### What portal to use

- **Sandbox** (portal `51121485`): use for testing. This is where our POC lives.
- **Production**: the real HubSpot with all marketing contacts. Use only after full testing.

To see which portal your token connects to:
```bash
curl -s "https://api.hubapi.com/integrations/v1/me" \
  -H "Authorization: Bearer YOUR_TOKEN" | python3 -m json.tool
```
Look for `"portalId"` and `"accountType"` in the response.

### How to see custom properties in HubSpot UI

After running the pipeline, the properties won't show automatically on a contact record. To see them:

1. Open any contact in HubSpot
2. Scroll to the **"About this contact"** section in the left sidebar
3. Click **"View all properties"** at the bottom
4. Type `sn_` in the search box
5. All 51 enriched properties appear

To **pin them** so they always show:
1. Click **Actions** → **Edit properties**
2. Search `SimpleNursing`
3. Select the ones you want visible
4. Save

---

## 7. Step 1 — Run the Main Enrichment Pipeline

**File:** `enrich.py`

This script does three things:
1. Reads the Excel file and parses all 57 columns
2. Optionally runs FullEnrich reverse lookup (email → LinkedIn profile)
3. Creates all custom HubSpot properties (if they don't exist yet)
4. Batch-upserts all 20 contacts to HubSpot

### Run it

```bash
# Dry run first — validates everything without writing to HubSpot
python3 enrich.py --dry-run --skip-fullenrich

# Live run (skipping FullEnrich for speed)
python3 enrich.py --skip-fullenrich

# Full run including FullEnrich (takes ~60 seconds to poll results)
python3 enrich.py
```

### What you'll see

```
==========================================================
  SimpleNursing HubSpot Enrichment Pipeline
  Mode: LIVE
==========================================================

[13:38:14] Loaded 20 records
[13:38:14] FullEnrich: skipped
[13:38:14] Setting up HubSpot properties...
[13:38:15] Property group 'sn_enrichment' already exists
[13:38:15] Properties: 0 created, 30 already existed
[13:38:15] Upserting 20 contacts (batch mode)...
[13:38:17]   ✓ annmarieshoemaker@yahoo.com (created)
[13:38:17]   ✓ debdawson@ymail.com (updated)
...
==========================================================
  RESULTS
==========================================================
  Total records   : 20
  Upserted ok     : 20
  Errors          : 0
==========================================================
```

### How the HubSpot batch upsert works

```python
# The key API call in enrich.py:
requests.post(
    "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert",
    headers={"Authorization": f"Bearer {HS_TOKEN}"},
    json={
        "inputs": [
            {
                "id": "email@example.com",      # match by email
                "idProperty": "email",           # tell HubSpot to match on email field
                "properties": {                  # everything to set on this contact
                    "email": "email@example.com",
                    "firstname": "Jane",
                    "sn_license_number": "RN123456",
                    "sn_ce_status": "In Progress",
                    ...
                }
            }
        ]
    }
)
```

Up to 100 contacts per batch call. For 17M records, we'll chunk into batches of 100 with rate limiting.

---

## 8. Step 2 — Run Exa Web Enrichment

**File:** `exa_enrich.py`

After the main pipeline, we use **Exa** (a semantic web search API) to find each nurse's professional profile online. For each nurse we search:
- LinkedIn
- Doximity (the "LinkedIn for doctors/nurses")
- NPI registry (opennpi.com, npino.com, opengovus.com)

We extract: **NPI number**, **employer/hospital**, **specialty**, **professional profile URL**.

### Run it

```bash
python3 exa_enrich.py

# Dry run
python3 exa_enrich.py --dry-run
```

### How Exa works

```python
# For each nurse, we send this to https://api.exa.ai/search:
{
    "query": "Deborah Lynn Dawson registered nurse Texas",
    "num_results": 5,
    "type": "neural",
    "include_domains": [
        "linkedin.com", "doximity.com",
        "opennpi.com", "opengovus.com", "npino.com"
    ],
    "contents": {"text": {"max_characters": 800}}
}

# Cost: ~$0.007 per search
# For 20 nurses: ~$0.14 total
# For 17M nurses: ~$119,000 — so Exa is for profile enrichment only, not mass data
```

**Note on FullEnrich:** FullEnrich works the other direction — give it a LinkedIn URL, it finds the email and phone. Since our nurses have Yahoo/Gmail emails, FullEnrich found 0/20 matches. Exa works better for finding NPI + employer from a name search.

---

## 9. Step 3 — Verify Everything

**File:** `verify_all.py`

This script does two checks:
1. **Schema check** — are all 51 `sn_` properties registered in HubSpot?
2. **Data check** — do all 20 contacts have the right values matching the CSV?

```bash
python3 verify_all.py
```

Expected output:
```
CHECK 1: All sn_ properties exist in HubSpot schema
  ✓ All 51 sn_ properties exist in HubSpot schema

CHECK 2: All 20 contacts have data matching CSV
  ✓ annmarieshoemaker@yahoo.com
  ✓ rghanson58@gmail.com
  ...
  ALL 20 CONTACTS VERIFIED ✓
```

---

## 10. Step 4 — Update the CSV with HubSpot IDs

**File:** `build_csv.py`

This script takes the original CSV and:
1. Adds a **new row 3** with the exact HubSpot property name for each column
2. Adds a **`hubspot_id` column** (last column) with the real HubSpot object ID for each contact

```bash
python3 build_csv.py
```

The output CSV structure:
```
Row 1: PERSON | | | PERSON SOURCE | ... | HUBSPOT
Row 2: resolved_person_id | person_name | person_email | ... | hubspot_id
Row 3: sn_person_id | firstname + lastname | email | ... | hs_object_id  ← NEW
Row 4: 4001877 | Annmarie Shoemaker | ANNMARIE@... | ... | 228714887471  ← data
...
```

---

## 11. All HubSpot Properties We Created

All properties live in a group called **`sn_enrichment`** (label: "SimpleNursing Enrichment").

### PERSON / SOURCE (6 properties)

| Property Name | Label | Type | Source |
|---|---|---|---|
| `sn_person_id` | SN: Resolved Person ID | string | CSV |
| `sn_native_id` | SN: Native Person ID (NetSuite) | string | CSV |
| `sn_brand` | SN: Brand | string | CSV |
| `sn_source_name` | SN: Source Name | string | CSV |
| `sn_source_platform` | SN: Source Platform | string | CSV |
| `sn_created_at` | SN: Record Created At | date | CSV |

### LICENSE (6 properties)

| Property Name | Label | Type | Source |
|---|---|---|---|
| `sn_license_id` | SN: License ID | string | CSV |
| `sn_license_number` | SN: License Number | string | CSV |
| `sn_license_state` | SN: License State | string | CSV |
| `sn_profession` | SN: Profession | string | CSV |
| `sn_license_issued_date` | SN: License Issued Date | date | CSV |
| `sn_est_renewal_date` | SN: Estimated Renewal Date | date | CSV |

### LMS ENGAGEMENT (6 properties)

| Property Name | Label | Type | Source |
|---|---|---|---|
| `sn_course_id` | SN: Course ID | string | CSV |
| `sn_course_title` | SN: Course Title | string | CSV |
| `sn_lms_completion_status` | SN: LMS Completion Status | string | CSV |
| `sn_credits_earned` | SN: LMS Credits Earned | number | CSV |
| `sn_last_activity_date` | SN: Last LMS Activity Date | date | CSV |
| `sn_lms_source` | SN: LMS Source | string | CSV |

### PURCHASE HISTORY (7 properties)

| Property Name | Label | Type | Source |
|---|---|---|---|
| `sn_order_id` | SN: Order ID | string | CSV |
| `sn_product_name` | SN: Product Name | string | CSV |
| `sn_product_category` | SN: Product Category | string | CSV |
| `sn_order_amount` | SN: Order Amount ($) | number | CSV |
| `sn_order_date` | SN: Order Date | date | CSV |
| `sn_payment_status` | SN: Payment Status | string | CSV |
| `sn_purchase_source` | SN: Purchase Source | string | CSV |

### MEMBERSHIP (6 properties)

| Property Name | Label | Type | Values |
|---|---|---|---|
| `sn_membership_status` | SN: Membership Status | enum | Active / Expired / Cancelled |
| `sn_membership_tier` | SN: Membership Tier | string | Regular, Lite, etc. |
| `sn_membership_cadence` | SN: Membership Billing Cadence | string | Annual, Monthly |
| `sn_mem_brand` | SN: Membership Brand | string | |
| `sn_mem_start_date` | SN: Membership Start Date | date | |
| `sn_mem_end_date` | SN: Membership End Date | date | |

### MARKETING CONSENT (4 properties)

| Property Name | Label | Type | Values |
|---|---|---|---|
| `sn_channel` | SN: Marketing Channel | string | Email |
| `sn_consent_status` | SN: Consent Status | enum | Opt-In / Opt-Out |
| `sn_consent_brand` | SN: Consent Brand | string | |
| `sn_consent_timestamp` | SN: Consent Timestamp | date | |

### CE COMPLETION (4 properties)

| Property Name | Label | Type | Values |
|---|---|---|---|
| `sn_ce_period` | SN: CE Period | string | Current Renewal |
| `sn_credits_completed` | SN: CE Credits Completed | number | |
| `sn_ce_status` | SN: CE Status | enum | Not Started / In Progress / Complete |
| `sn_ce_period_end_date` | SN: CE Period End Date | date | |

### DIRECT MAIL (6 properties)

| Property Name | Label | Type | Source |
|---|---|---|---|
| `sn_send_channel` | SN: Direct Mail Channel | string | CSV |
| `sn_send_brand` | SN: Direct Mail Brand | string | CSV |
| `sn_send_date` | SN: Direct Mail Send Date | date | CSV |
| `sn_creative_version` | SN: Creative Version | string | CSV |
| `sn_book_title_sent` | SN: Book Title Sent | string | CSV |
| `sn_book_sent_date` | SN: Book Sent Date | date | CSV |

### EXA ENRICHMENT (6 properties)

| Property Name | Label | Type | Source |
|---|---|---|---|
| `sn_exa_employer` | SN: Employer (Exa) | string | Exa web search |
| `sn_exa_specialty` | SN: Specialty (Exa) | string | Exa web search |
| `sn_exa_npi` | SN: NPI Number (Exa) | string | Exa → NPI registry |
| `sn_exa_profile_url` | SN: Professional Profile URL | string | Exa web search |
| `sn_exa_profile_type` | SN: Profile Source (Exa) | string | LinkedIn / Doximity / NPI Registry |
| `sn_exa_enriched_at` | SN: Exa Enriched At | string | pipeline timestamp |

---

## 12. CSV Column → HubSpot Property Mapping

| Section | CSV Column | HubSpot Property |
|---|---|---|
| PERSON | `resolved_person_id` | `sn_person_id` |
| PERSON | `person_name` | `firstname` + `lastname` (split on last space) |
| PERSON | `person_email` | `email` |
| PERSON | `person_address` | `address` |
| PERSON | `person_phone` | `phone` |
| PERSON | `created_at` | `sn_created_at` |
| PERSON SOURCE | `source_name` | `sn_source_name` |
| PERSON SOURCE | `source_platform` | `sn_source_platform` |
| PERSON SOURCE | `native_person_id` | `sn_native_id` |
| PERSON SOURCE | `brand` | `sn_brand` |
| LICENSE | `resolved_license_id` | `sn_license_id` |
| LICENSE | `license_number` | `sn_license_number` + `license_number` (existing prop) |
| LICENSE | `state` | `sn_license_state` + `license_state_abbreviation` (existing) |
| LICENSE | `profession` | `sn_profession` |
| LICENSE | `license_issued_date` | `sn_license_issued_date` |
| LICENSE | `est_renewal_date` | `sn_est_renewal_date` + `education_renewal_date_us_nurses` (existing) |
| LMS ENGAGEMENT | `course_id` | `sn_course_id` |
| LMS ENGAGEMENT | `course_title` | `sn_course_title` |
| LMS ENGAGEMENT | `completion_status` | `sn_lms_completion_status` |
| LMS ENGAGEMENT | `credits_earned` | `sn_credits_earned` |
| LMS ENGAGEMENT | `last_activity_date` | `sn_last_activity_date` |
| LMS ENGAGEMENT | `lms_source` | `sn_lms_source` |
| PURCHASE HISTORY | `order_id` | `sn_order_id` |
| PURCHASE HISTORY | `product_name` | `sn_product_name` |
| PURCHASE HISTORY | `product_category` | `sn_product_category` |
| PURCHASE HISTORY | `order_amount` | `sn_order_amount` |
| PURCHASE HISTORY | `order_date` | `sn_order_date` |
| PURCHASE HISTORY | `payment_status` | `sn_payment_status` |
| PURCHASE HISTORY | `purchase_source` | `sn_purchase_source` |
| MEMBERSHIP | `membership_billing_cadence` | `sn_membership_cadence` |
| MEMBERSHIP | `membership_tier` | `sn_membership_tier` |
| MEMBERSHIP | `mem_brand` | `sn_mem_brand` |
| MEMBERSHIP | `mem_start_date` | `sn_mem_start_date` |
| MEMBERSHIP | `mem_end_date` | `sn_mem_end_date` + `membership_end_date` (existing) |
| MEMBERSHIP | `mem_status` | `sn_membership_status` |
| MARKETING CONSENT | `channel` | `sn_channel` |
| MARKETING CONSENT | `consent_status` | `sn_consent_status` |
| MARKETING CONSENT | `consent_brand` | `sn_consent_brand` |
| MARKETING CONSENT | `consent_timestamp` | `sn_consent_timestamp` |
| CE COMPLETION | `ce_period` | `sn_ce_period` |
| CE COMPLETION | `credits_completed` | `sn_credits_completed` |
| CE COMPLETION | `ce_status` | `sn_ce_status` |
| CE COMPLETION | `period_end_date` | `sn_ce_period_end_date` |
| DIRECT MAIL | `send_channel` | `sn_send_channel` |
| DIRECT MAIL | `send_brand` | `sn_send_brand` |
| DIRECT MAIL | `send_date` | `sn_send_date` |
| DIRECT MAIL | `creative_version` | `sn_creative_version` |
| DIRECT MAIL | `book_title_sent` | `sn_book_title_sent` |
| DIRECT MAIL | `book_sent_date` | `sn_book_sent_date` |
| SPECIALTY | `speciality` | `sn_specialty` (no data in POC file) |
| SPECIALTY | `nurse_professions` | `sn_nurse_professions` (no data in POC file) |

**Columns with no data in the POC file** (we create the property but it stays empty):
`score`, `credits_required`, `send_id`, `campaign_name`, `response_flag`, `response_date`, `speciality`, `nurse_professions`

---

## 13. APIs Used — Full Reference

### HubSpot API

**Base URL:** `https://api.hubapi.com`

**Auth header:** `Authorization: Bearer pat-na1-xxxxx...`

| What | Method | Endpoint |
|---|---|---|
| List contacts | GET | `/crm/v3/objects/contacts?properties=email,firstname` |
| Get one contact by email | GET | `/crm/v3/objects/contacts/{email}?idProperty=email` |
| **Batch upsert contacts** | POST | `/crm/v3/objects/contacts/batch/upsert` |
| Create a contact property | POST | `/crm/v3/properties/contacts` |
| List all contact properties | GET | `/crm/v3/properties/contacts?limit=500` |
| Create a property group | POST | `/crm/v3/properties/contacts/groups` |
| List property groups | GET | `/crm/v3/properties/contacts/groups` |
| Check your portal info | GET | `/integrations/v1/me` |

**Batch upsert payload format:**
```json
{
  "inputs": [
    {
      "id": "email@example.com",
      "idProperty": "email",
      "properties": {
        "email": "email@example.com",
        "firstname": "Jane",
        "sn_license_number": "RN123456"
      }
    }
  ]
}
```
- Max 100 contacts per batch call
- Returns 200 with results array on success
- `id` in the response is the HubSpot contact ID (e.g., `228719219593`)

**Property creation payload:**
```json
{
  "name": "sn_license_number",
  "label": "SN: License Number",
  "type": "string",
  "fieldType": "text",
  "groupName": "sn_enrichment"
}
```

For **enumeration** (dropdown) properties, add an `options` array:
```json
{
  "name": "sn_membership_status",
  "label": "SN: Membership Status",
  "type": "enumeration",
  "fieldType": "select",
  "groupName": "sn_enrichment",
  "options": [
    {"label": "Active",    "value": "Active",    "displayOrder": 0},
    {"label": "Expired",   "value": "Expired",   "displayOrder": 1},
    {"label": "Cancelled", "value": "Cancelled", "displayOrder": 2}
  ]
}
```

For **date** properties, HubSpot expects **epoch milliseconds at midnight UTC**:
```python
import calendar
from datetime import datetime
d = datetime(2026, 6, 12)
epoch_ms = int(calendar.timegm(d.timetuple()) * 1000)  # → 1749686400000
```
Do NOT send a string like `"2026-06-12"` for date fields — it won't work.

**Important gotcha — zero values:**
```python
# WRONG — Python treats 0 as falsy, so this skips zero values
if v := to_num(row.get("credits_earned")):
    p["sn_credits_earned"] = v   # ← 0 never gets set!

# CORRECT — check for None explicitly
v = to_num(row.get("credits_earned"))
if v is not None:
    p["sn_credits_earned"] = v   # ← 0 gets set correctly
```
We hit this bug for `order_amount = 0` and `credits_earned = 0`. Fixed in `push_all.py`.

---

### FullEnrich API

**Base URL:** `https://app.fullenrich.com/api/v1`

**Auth header:** `Authorization: Bearer YOUR_KEY`

FullEnrich is a **LinkedIn enrichment** tool. Give it a LinkedIn URL → it returns email and phone. Or give it emails → it finds their LinkedIn profiles (**reverse lookup**).

| What | Method | Endpoint |
|---|---|---|
| Check credits | GET | `/account/credits` |
| Start bulk reverse lookup (email → LinkedIn) | POST | `/contact/reverse/email/bulk` |
| Poll reverse lookup status | GET | `/contact/reverse/email/bulk/{reverse_id}` |
| Start LinkedIn enrichment (LinkedIn → email) | POST | `/contact/enrich/bulk` |
| Poll enrichment status | GET | `/contact/enrich/bulk/{enrichment_id}` |

**Reverse lookup payload:**
```json
{
  "name": "my-lookup-name",
  "data": [
    {"email": "jane@example.com"},
    {"email": "bob@yahoo.com"}
  ]
}
```

**Poll until status = "FINISHED"** — it's async, usually takes 30–60 seconds.

**Note:** FullEnrich works best for B2B professional emails (company domains). For B2C emails (Gmail, Yahoo, Hotmail), it returns 0 results. Our nursing contacts use personal emails so we got 0/20 matches.

---

### Exa API

**Base URL:** `https://api.exa.ai`

**Auth header:** `x-api-key: YOUR_KEY`

Exa is a **semantic web search API** — smarter than Google for finding specific people.

| What | Method | Endpoint |
|---|---|---|
| Search | POST | `/search` |

**Search payload:**
```json
{
  "query": "Deborah Lynn Dawson registered nurse Texas",
  "num_results": 5,
  "type": "neural",
  "use_autoprompt": false,
  "include_domains": ["linkedin.com", "doximity.com", "opennpi.com", "opengovus.com", "npino.com"],
  "contents": {
    "text": {"max_characters": 800}
  }
}
```

**Response structure:**
```json
{
  "results": [
    {
      "title": "Deborah Dawson — NPI Registry",
      "url": "https://npino.com/nurse/1972630978-debra-d-dawson/",
      "score": 1.0,
      "text": "Deborah D Dawson... specialization is Registered Nurse - Psych/mental Health..."
    }
  ],
  "costDollars": {"total": 0.007}
}
```

**Cost:** $0.007 per search. For 20 nurses × 2 searches = $0.28.

---

## 14. Phase 2: S3 Pipeline (Coming Next)

### What changes at 17M scale

The Excel/CSV approach works for 20 records. For 17 million:

1. **File size** — the S3 file will be huge. We need to read it in **chunks** (e.g., 10,000 rows at a time)
2. **Delta sync** — we can't re-push all 17M every run. We need to track `last_sync_timestamp` and only push records where something changed
3. **Rate limits** — HubSpot allows ~100 req/s on paid plans. At 100 contacts per batch = 10,000 contacts/second theoretical max
4. **Orchestration** — Airflow will trigger the pipeline on a schedule (e.g., weekly Monday)

### S3 access

Jira ticket **COT-6043** (assigned to Prakhar Jadon) requests these credentials:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_DEFAULT_REGION=us-east-1`

Scoped to: `s3://prod-data-warehouse-redshift-cdp-data-lake-us-east-1/entity_matching/segmentation_flatview/`

First file: `hc_ce_renewal_segmentation_flatview_000.csv`

### How to read from S3 once you have credentials

```python
import boto3

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name="us-east-1"
)

# List files in the prefix
response = s3.list_objects_v2(
    Bucket="prod-data-warehouse-redshift-cdp-data-lake-us-east-1",
    Prefix="entity_matching/segmentation_flatview/"
)
for obj in response["Contents"]:
    print(obj["Key"])

# Download the file
s3.download_file(
    "prod-data-warehouse-redshift-cdp-data-lake-us-east-1",
    "entity_matching/segmentation_flatview/hc_ce_renewal_segmentation_flatview_000.csv",
    "/local/path/output.csv"
)
```

Install boto3: `uv pip install boto3`

---

## 15. Troubleshooting

### "This app hasn't been granted all required scopes"
Your HubSpot token is missing permissions. Go to HubSpot → Settings → Integrations → Private Apps → your app → Scopes tab, and add `crm.objects.contacts.write` and `crm.schemas.contacts.write`.

### "resource not found" (404) when upserting contacts
You're using `PATCH` to update a contact that doesn't exist yet. Switch to the **batch upsert** endpoint (`POST /crm/v3/objects/contacts/batch/upsert`) which creates-or-updates in one call.

### Properties show as "None" in HubSpot
- Check the date format — HubSpot dates must be epoch milliseconds, not strings
- Check for zero values — use `if v is not None:` not `if v:` for numbers

### FullEnrich returns 0 results
Expected for personal emails (Gmail, Yahoo, Hotmail). FullEnrich works for corporate email domains. Use Exa instead for finding NPI/profile from name+state.

### "Please select from an Initiative" when creating Jira ticket
The COT project requires an Initiative field. Must use `{"id": "XXXXX"}` format (not `[{...}]` array). Get the id by calling:
```
GET /rest/api/3/issue/createmeta?projectKeys=COT&issuetypeIds=3&expand=projects.issuetypes.fields
```

---

## People

| Name | Role | Contact |
|---|---|---|
| Sam Chaudhary | GTM Engineering (project lead) | sam.chaudhary@colibrigroup.com |
| Aliza John | Intern (you!) | — |
| Madhankumar Pillay | Product owner | — |
| Veena Anantharam | Data architecture | — |
| Sandesh Segu | Data engineering | — |
| Prakhar Jadon | DevOps (S3 access owner) | COT-6043 assignee |
| Austin Ellingwood | DevOps (cc) | — |

---

*Built by Sam Chaudhary with Claude Code. Questions? Open an issue or ping Sam directly.*
