"""
Exa Enrichment — SimpleNursing HubSpot Pipeline
================================================
Searches each nurse by name+state across LinkedIn, Doximity, NPI registries.
Extracts: employer, specialty, NPI, professional profile URL.
Pushes new fields to HubSpot under the sn_enrichment group.

Usage:
  python exa_enrich.py             # enrich all 20 contacts
  python exa_enrich.py --dry-run   # print results without writing to HubSpot
"""

import argparse
import os
from pathlib import Path
import re
import time
from datetime import datetime

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
except ImportError:
    pass

HS_TOKEN = os.environ["HUBSPOT_API_KEY"]
EXA_TOKEN = os.environ["EXA_API_KEY"]
EXCEL_FILE = os.environ.get("CSV_FILE") or os.environ.get("EXCEL_FILE") or (_ for _ in ()).throw(SystemExit("ERROR: CSV_FILE not set in .env"))

HS_BASE  = "https://api.hubapi.com"
EXA_BASE = "https://api.exa.ai"

HS_HEADERS  = {"Authorization": f"Bearer {HS_TOKEN}",  "Content-Type": "application/json"}
EXA_HEADERS = {"x-api-key": EXA_TOKEN,                 "Content-Type": "application/json"}

STATE_NAMES = {
    "TX": "Texas", "MA": "Massachusetts", "WA": "Washington",
    "MI": "Michigan", "CA": "California", "NY": "New York",
    "FL": "Florida", "IL": "Illinois", "OH": "Ohio", "PA": "Pennsylvania",
}

# ---------------------------------------------------------------------------
# Additional HubSpot properties to create
# ---------------------------------------------------------------------------

EXA_PROPERTIES = [
    {"name": "sn_exa_employer",     "label": "SN: Employer (Exa)",          "type": "string", "fieldType": "text"},
    {"name": "sn_exa_specialty",    "label": "SN: Specialty (Exa)",         "type": "string", "fieldType": "text"},
    {"name": "sn_exa_npi",         "label": "SN: NPI Number (Exa)",        "type": "string", "fieldType": "text"},
    {"name": "sn_exa_profile_url",  "label": "SN: Professional Profile URL (Exa)", "type": "string", "fieldType": "text"},
    {"name": "sn_exa_profile_type", "label": "SN: Profile Source (Exa)",   "type": "string", "fieldType": "text"},
    {"name": "sn_exa_enriched_at",  "label": "SN: Exa Enriched At",        "type": "string", "fieldType": "text"},
]

GROUP_NAME = "sn_enrichment"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg, indent=""):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {indent}{msg}")


def extract_npi(text, url):
    """Extract NPI number from text or URL."""
    # NPI appears in URLs like /npi/1234567890 or /provider/1234567890
    for pattern in [r'/npi/(\d{10})', r'/provider/(\d{10})', r'NPI[:\s#]+(\d{10})', r'\b(\d{10})\b']:
        m = re.search(pattern, url + " " + (text or ""))
        if m and m.group(1).startswith('1'):
            return m.group(1)
    return None


def extract_employer(text, url):
    """Try to pull employer/hospital from NPI result text."""
    if not text:
        return None
    # NPI pages often have address lines with hospital names
    for pattern in [
        r'(?:Organization|Employer|Hospital|Medical|Health|Clinic|System)[:\s]+([A-Z][^\n.]{5,60})',
        r'affiliated with ([A-Z][^\n.]{5,60})',
        r'(?:works? at|employed by|practices? at)\s+([A-Z][^\n.]{5,60})',
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_specialty(text, title):
    """Extract specialty from Doximity/NPI text."""
    known_specialties = [
        "Family", "Pediatric", "Critical Care", "Emergency", "Oncology",
        "Cardiology", "Orthopedic", "Neurology", "Geriatric", "Psychiatric",
        "Obstetric", "Neonatal", "ICU", "Acute Care", "Primary Care",
        "Medical-Surgical", "Home Health", "Hospice", "Palliative",
        "Operating Room", "PACU", "Labor", "Delivery",
    ]
    combined = (title or "") + " " + (text or "")[:500]
    for spec in known_specialties:
        if spec.lower() in combined.lower():
            return spec
    return None


def classify_url(url):
    """Return profile source type from URL."""
    if "linkedin.com" in url:
        return "LinkedIn"
    if "doximity.com" in url:
        return "Doximity"
    if any(d in url for d in ["opennpi.com", "npino.com", "opengovus.com", "npidb.org"]):
        return "NPI Registry"
    if "healthgrades.com" in url:
        return "Healthgrades"
    return "Web"


# ---------------------------------------------------------------------------
# Exa search for one nurse
# ---------------------------------------------------------------------------

def exa_search_nurse(name, state_abbr, email):
    """Run up to 2 Exa queries for a nurse. Return best hit dict."""
    state_full = STATE_NAMES.get(state_abbr, state_abbr)
    first_name = name.split()[0]
    last_name = name.split()[-1]

    queries = [
        # Query 1: professional directories — high precision
        {
            "query": f"{name} registered nurse {state_full}",
            "num_results": 5,
            "type": "neural",
            "use_autoprompt": False,
            "include_domains": [
                "linkedin.com", "doximity.com",
                "opennpi.com", "opengovus.com", "npino.com",
                "healthgrades.com", "vitals.com"
            ],
            "contents": {"text": {"max_characters": 800}},
        },
        # Query 2: broader web (catches hospital bio pages, news, etc.)
        {
            "query": f'"{first_name} {last_name}" nurse {state_abbr}',
            "num_results": 3,
            "type": "keyword",
            "use_autoprompt": False,
            "contents": {"text": {"max_characters": 600}},
        },
    ]

    best = {
        "npi": None, "employer": None, "specialty": None,
        "profile_url": None, "profile_type": None,
    }

    name_lower = name.lower()
    name_parts = [p.lower() for p in name.split() if len(p) > 2]

    for qi, qbody in enumerate(queries):
        r = requests.post(f"{EXA_BASE}/search", headers=EXA_HEADERS, json=qbody, timeout=20)
        if r.status_code != 200:
            log(f"  Exa Q{qi+1} error {r.status_code}", "    ")
            continue

        results = r.json().get("results", [])

        for hit in results:
            url   = hit.get("url", "")
            title = hit.get("title", "")
            text  = hit.get("text", "")
            score = hit.get("score", 0)

            # Relevance check: title or text must contain name parts
            combined_lower = (title + " " + text[:300]).lower()
            matching_parts = sum(1 for p in name_parts if p in combined_lower)
            if matching_parts < 2 and score < 0.7:
                continue

            # NPI
            if not best["npi"]:
                npi = extract_npi(text, url)
                if npi:
                    best["npi"] = npi

            # Profile URL (prefer LinkedIn > Doximity > NPI)
            if not best["profile_url"] or (
                classify_url(url) == "LinkedIn" and best["profile_type"] != "LinkedIn"
            ) or (
                classify_url(url) == "Doximity" and best["profile_type"] == "NPI Registry"
            ):
                best["profile_url"]  = url
                best["profile_type"] = classify_url(url)

            # Employer
            if not best["employer"]:
                emp = extract_employer(text, url)
                if emp:
                    best["employer"] = emp

            # Specialty
            if not best["specialty"]:
                spec = extract_specialty(text, title)
                if spec:
                    best["specialty"] = spec

        time.sleep(0.3)  # be polite to Exa

        # Stop early if we have good data
        if best["profile_url"] and (best["npi"] or best["employer"]):
            break

    return best


# ---------------------------------------------------------------------------
# Ensure extra HubSpot properties exist
# ---------------------------------------------------------------------------

def ensure_exa_properties(dry_run):
    r = requests.get(f"{HS_BASE}/crm/v3/properties/contacts?limit=500",
                     headers=HS_HEADERS, timeout=15)
    existing = {p["name"] for p in r.json().get("results", [])}

    created = skipped = 0
    for prop in EXA_PROPERTIES:
        if prop["name"] in existing:
            skipped += 1
            continue
        log(f"  + {prop['name']}", "  ")
        if dry_run:
            created += 1
            continue
        body = {k: v for k, v in prop.items()
                if k in ("name", "label", "type", "fieldType")}
        body["groupName"] = GROUP_NAME
        r2 = requests.post(f"{HS_BASE}/crm/v3/properties/contacts",
                           headers=HS_HEADERS, json=body, timeout=15)
        if r2.status_code in (200, 201):
            created += 1
        else:
            log(f"  ⚠ {prop['name']}: {r2.status_code} {r2.text[:80]}", "  ")
    log(f"Exa properties: {created} created, {skipped} already existed")


# ---------------------------------------------------------------------------
# Main enrichment loop
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--excel", default=EXCEL_FILE)
    args = ap.parse_args()

    print("\n" + "=" * 58)
    print("  Exa Enrichment — SimpleNursing HubSpot Pipeline")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 58 + "\n")

    # Load contacts from Excel (same source of truth)
    import openpyxl
    wb = openpyxl.load_workbook(args.excel, read_only=True)
    ws = wb["Nursing_Flat_File"]
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[1]
    records = [dict(zip(headers, row)) for row in rows[2:]]
    log(f"Loaded {len(records)} contacts")

    # Ensure Exa properties exist in HubSpot
    log("Ensuring Exa HubSpot properties…")
    ensure_exa_properties(dry_run=args.dry_run)

    # Enrich each contact
    enriched_count = 0
    batch_inputs = []

    for i, row in enumerate(records, 1):
        email = str(row.get("person_email", "") or "").strip().lower()
        name  = str(row.get("person_name",  "") or "").strip()
        state = str(row.get("state",        "") or "").strip()

        if not email or not name:
            continue

        log(f"[{i:02d}/{len(records)}] {name} ({state}) — {email}")

        exa = exa_search_nurse(name, state, email)

        found_fields = [k for k, v in exa.items() if v]
        log(f"  → found: {', '.join(found_fields) if found_fields else 'nothing'}", "  ")

        if exa.get("profile_url"):
            log(f"  → {exa['profile_type']}: {exa['profile_url'][:80]}", "  ")
        if exa.get("employer"):
            log(f"  → employer: {exa['employer'][:60]}", "  ")
        if exa.get("npi"):
            log(f"  → NPI: {exa['npi']}", "  ")
        if exa.get("specialty"):
            log(f"  → specialty: {exa['specialty']}", "  ")

        # Build HubSpot update payload
        props = {"sn_exa_enriched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
        if exa.get("employer"):
            props["sn_exa_employer"]    = exa["employer"]
            props["company"]            = exa["employer"]  # standard HS prop
        if exa.get("specialty"):
            props["sn_exa_specialty"]   = exa["specialty"]
        if exa.get("npi"):
            props["sn_exa_npi"]        = exa["npi"]
        if exa.get("profile_url"):
            props["sn_exa_profile_url"] = exa["profile_url"]
            props["sn_exa_profile_type"]= exa["profile_type"]
            if exa["profile_type"] == "LinkedIn":
                props["sn_linkedin_url"] = exa["profile_url"]

        if len(props) > 1:  # more than just the timestamp
            enriched_count += 1

        batch_inputs.append({"id": email, "idProperty": "email", "properties": props})

    # Batch upsert to HubSpot
    log(f"\nWriting {len(batch_inputs)} contacts to HubSpot…")
    if not args.dry_run and batch_inputs:
        r = requests.post(
            f"{HS_BASE}/crm/v3/objects/contacts/batch/upsert",
            headers=HS_HEADERS,
            json={"inputs": batch_inputs},
            timeout=30,
        )
        if r.status_code == 200:
            log(f"  ✓ All {len(batch_inputs)} contacts updated", "  ")
        else:
            log(f"  ✗ {r.status_code}: {r.text[:200]}", "  ")
    elif args.dry_run:
        log("  [dry-run] would write to HubSpot", "  ")

    print("\n" + "=" * 58)
    print("  RESULTS")
    print("=" * 58)
    print(f"  Contacts processed : {len(records)}")
    print(f"  Contacts enriched  : {enriched_count}")
    print(f"  HubSpot updated    : {'yes' if not args.dry_run else 'dry-run'}")
    print("=" * 58 + "\n")


if __name__ == "__main__":
    main()
