"""
SimpleNursing HubSpot Enrichment Pipeline
=========================================
1. Reads Excel flat file (HC_CE_Renewal_Nursing_Specialty_3.xlsx)
2. Runs FullEnrich reverse lookup (email -> LinkedIn profile)
3. Creates custom HubSpot contact properties (idempotent)
4. Batch-upserts all contacts (creates OR updates by email)

Usage:
  python enrich.py                    # full run (incl. FullEnrich)
  python enrich.py --dry-run          # validate without writing to HubSpot
  python enrich.py --skip-fullenrich  # skip FullEnrich step
"""

import argparse
import os
import sys
import time
import calendar
from datetime import datetime

import openpyxl
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

HS_TOKEN = os.environ["HUBSPOT_API_KEY"]
FE_TOKEN = os.environ["FULLENRICH_API_KEY"]
EXCEL_FILE = os.getenv("EXCEL_FILE", "/Users/anmolsam/Downloads/HC_CE_Renewal_Nursing_Specialty_3.xlsx")

HS_BASE = "https://api.hubapi.com"
FE_BASE = "https://app.fullenrich.com/api/v1"

HS_HEADERS = {"Authorization": f"Bearer {HS_TOKEN}", "Content-Type": "application/json"}
FE_HEADERS = {"Authorization": f"Bearer {FE_TOKEN}", "Content-Type": "application/json"}

GROUP_NAME = "sn_enrichment"
BATCH_SIZE = 100  # HubSpot batch upsert max

# ---------------------------------------------------------------------------
# Custom properties (group: sn_enrichment, prefix: sn_)
# ---------------------------------------------------------------------------

CUSTOM_PROPERTIES = [
    # Person / source IDs
    {"name": "sn_person_id",       "label": "SN: Resolved Person ID",        "type": "string",      "fieldType": "text"},
    {"name": "sn_native_id",       "label": "SN: Native Person ID",          "type": "string",      "fieldType": "text"},
    {"name": "sn_brand",           "label": "SN: Brand",                     "type": "string",      "fieldType": "text"},
    {"name": "sn_source_platform", "label": "SN: Source Platform",           "type": "string",      "fieldType": "text"},
    # License
    {"name": "sn_license_id",      "label": "SN: Resolved License ID",       "type": "string",      "fieldType": "text"},
    {"name": "sn_license_number",  "label": "SN: License Number",            "type": "string",      "fieldType": "text"},
    {"name": "sn_license_state",   "label": "SN: License State",             "type": "string",      "fieldType": "text"},
    {"name": "sn_profession",      "label": "SN: Profession",                "type": "string",      "fieldType": "text"},
    {"name": "sn_license_issued_date", "label": "SN: License Issued Date",   "type": "date",        "fieldType": "date"},
    {"name": "sn_est_renewal_date","label": "SN: Estimated Renewal Date",    "type": "date",        "fieldType": "date"},
    # Membership
    {"name": "sn_membership_status", "label": "SN: Membership Status",       "type": "enumeration", "fieldType": "select",
     "options": [{"label": "Active",     "value": "Active",     "displayOrder": 0},
                 {"label": "Expired",    "value": "Expired",    "displayOrder": 1},
                 {"label": "Cancelled",  "value": "Cancelled",  "displayOrder": 2}]},
    {"name": "sn_membership_tier",   "label": "SN: Membership Tier",         "type": "string",      "fieldType": "text"},
    {"name": "sn_membership_cadence","label": "SN: Membership Billing Cadence","type": "string",    "fieldType": "text"},
    {"name": "sn_mem_brand",         "label": "SN: Membership Brand",        "type": "string",      "fieldType": "text"},
    {"name": "sn_mem_start_date",    "label": "SN: Membership Start Date",   "type": "date",        "fieldType": "date"},
    {"name": "sn_mem_end_date",      "label": "SN: Membership End Date",     "type": "date",        "fieldType": "date"},
    # CE Completion
    {"name": "sn_ce_period",         "label": "SN: CE Period",               "type": "string",      "fieldType": "text"},
    {"name": "sn_credits_required",  "label": "SN: CE Credits Required",    "type": "number",      "fieldType": "number"},
    {"name": "sn_credits_completed", "label": "SN: CE Credits Completed",   "type": "number",      "fieldType": "number"},
    {"name": "sn_ce_status",         "label": "SN: CE Status",              "type": "enumeration", "fieldType": "select",
     "options": [{"label": "Not Started", "value": "Not Started", "displayOrder": 0},
                 {"label": "In Progress",  "value": "In Progress",  "displayOrder": 1},
                 {"label": "Complete",     "value": "Complete",     "displayOrder": 2}]},
    {"name": "sn_ce_period_end_date","label": "SN: CE Period End Date",      "type": "date",        "fieldType": "date"},
    # LMS / Engagement
    {"name": "sn_last_activity_date","label": "SN: Last LMS Activity Date",  "type": "date",        "fieldType": "date"},
    # Marketing consent
    {"name": "sn_consent_status",    "label": "SN: Consent Status",          "type": "enumeration", "fieldType": "select",
     "options": [{"label": "Opt-In",  "value": "Opt-In",  "displayOrder": 0},
                 {"label": "Opt-Out", "value": "Opt-Out", "displayOrder": 1}]},
    {"name": "sn_consent_timestamp", "label": "SN: Consent Timestamp",       "type": "string",      "fieldType": "text"},
    # Specialty
    {"name": "sn_specialty",         "label": "SN: Nursing Specialty",       "type": "string",      "fieldType": "text"},
    {"name": "sn_nurse_professions", "label": "SN: Nurse Professions",       "type": "string",      "fieldType": "text"},
    # FullEnrich
    {"name": "sn_linkedin_url",      "label": "SN: LinkedIn URL",            "type": "string",      "fieldType": "text"},
    {"name": "sn_job_title",         "label": "SN: Job Title",               "type": "string",      "fieldType": "text"},
    {"name": "sn_company",           "label": "SN: Company",                 "type": "string",      "fieldType": "text"},
    # Pipeline metadata
    {"name": "sn_enriched_at",       "label": "SN: Last Enriched At",        "type": "string",      "fieldType": "text"},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg, indent=""):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {indent}{msg}")


def safe_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def safe_date(val):
    """Return epoch milliseconds (midnight UTC) for a date value."""
    if not val:
        return None
    if isinstance(val, str):
        try:
            d = datetime.strptime(val[:10], "%Y-%m-%d")
        except ValueError:
            return None
    elif hasattr(val, "year"):
        d = datetime(val.year, val.month, val.day)
    else:
        return None
    return int(calendar.timegm(d.timetuple()) * 1000)


def safe_num(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ---------------------------------------------------------------------------
# Step 1: Parse Excel
# ---------------------------------------------------------------------------

def load_excel(path):
    log(f"Loading: {path}")
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["Nursing_Flat_File"]
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[1]
    data = [dict(zip(headers, row)) for row in rows[2:]]
    log(f"Loaded {len(data)} records")
    return data


# ---------------------------------------------------------------------------
# Step 2: FullEnrich reverse lookup  (email -> LinkedIn profile)
# ---------------------------------------------------------------------------

def fullenrich_reverse_lookup(emails, skip=False):
    if skip:
        log("FullEnrich: skipped (--skip-fullenrich)")
        return {}

    log(f"FullEnrich: starting reverse lookup for {len(emails)} emails…")
    payload = {
        "name": f"sn-nursing-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "data": [{"email": e.lower()} for e in emails if e],
    }

    r = requests.post(f"{FE_BASE}/contact/reverse/email/bulk",
                      headers=FE_HEADERS, json=payload, timeout=30)

    if r.status_code not in (200, 201):
        log(f"FullEnrich error {r.status_code}: {r.text[:200]}", "  ⚠ ")
        return {}

    resp = r.json()
    reverse_id = resp.get("enrichment_id") or resp.get("reverse_id") or resp.get("id")
    if not reverse_id:
        log(f"No job ID in response: {resp}", "  ⚠ ")
        return {}

    log(f"FullEnrich job ID: {reverse_id} — polling every 10s (up to 6 min)…")

    for attempt in range(36):
        time.sleep(10)
        r2 = requests.get(f"{FE_BASE}/contact/reverse/email/bulk/{reverse_id}",
                          headers=FE_HEADERS, timeout=30)
        if r2.status_code != 200:
            log(f"  poll {attempt+1}: HTTP {r2.status_code}", "  ")
            continue

        result = r2.json()
        status = result.get("status", "").upper()
        log(f"  poll {attempt+1}: {status}", "  ")

        if status in ("FINISHED", "COMPLETED", "DONE"):
            enriched = {}
            for item in result.get("results") or result.get("data") or []:
                email = (item.get("email") or "").lower()
                if not email:
                    continue
                person = item.get("person") or item.get("profile") or {}
                linkedin = person.get("linkedin_url") or item.get("linkedin_url")
                title = person.get("job_title") or person.get("title")
                co = (person.get("current_company") or {}).get("name") or person.get("company")
                if any([linkedin, title, co]):
                    enriched[email] = {"linkedin_url": linkedin, "job_title": title, "company": co}
            log(f"FullEnrich complete: {len(enriched)}/{len(emails)} profiles found")
            return enriched

        if status in ("FAILED", "CANCELED", "CREDITS_INSUFFICIENT"):
            log(f"FullEnrich ended: {status}", "  ⚠ ")
            return {}

    log("FullEnrich timed out (6 min)", "  ⚠ ")
    return {}


# ---------------------------------------------------------------------------
# Step 3: HubSpot — property group + properties (idempotent)
# ---------------------------------------------------------------------------

def ensure_property_group(dry_run):
    r = requests.get(f"{HS_BASE}/crm/v3/properties/contacts/groups",
                     headers=HS_HEADERS, timeout=15)
    if GROUP_NAME in {g["name"] for g in r.json().get("results", [])}:
        log(f"Property group '{GROUP_NAME}' already exists")
        return

    log(f"Creating property group '{GROUP_NAME}'…")
    if dry_run:
        log("  [dry-run] skipped", "  ")
        return

    r2 = requests.post(f"{HS_BASE}/crm/v3/properties/contacts/groups",
                       headers=HS_HEADERS,
                       json={"name": GROUP_NAME, "label": "SimpleNursing Enrichment"},
                       timeout=15)
    log(f"  {'✓ created' if r2.status_code in (200, 201) else f'⚠ {r2.status_code}: {r2.text[:100]}'}", "  ")


def ensure_properties(dry_run):
    r = requests.get(f"{HS_BASE}/crm/v3/properties/contacts?limit=500",
                     headers=HS_HEADERS, timeout=15)
    existing = {p["name"] for p in r.json().get("results", [])}

    created = skipped = 0
    for prop in CUSTOM_PROPERTIES:
        if prop["name"] in existing:
            skipped += 1
            continue

        log(f"  + {prop['name']} ({prop['type']})", "  ")
        if dry_run:
            created += 1
            continue

        body = {k: v for k, v in prop.items()
                if k in ("name", "label", "type", "fieldType", "options", "description")}
        body["groupName"] = GROUP_NAME

        r2 = requests.post(f"{HS_BASE}/crm/v3/properties/contacts",
                           headers=HS_HEADERS, json=body, timeout=15)
        if r2.status_code in (200, 201):
            created += 1
        else:
            log(f"  ⚠ {prop['name']}: {r2.status_code} {r2.text[:100]}", "  ")

    log(f"Properties: {created} created, {skipped} already existed")


# ---------------------------------------------------------------------------
# Step 4: Build HubSpot payload from one Excel row
# ---------------------------------------------------------------------------

def build_props(row, fe_data):
    email = safe_str(row.get("person_email", ""))
    fe = fe_data.get((email or "").lower(), {})

    p = {}

    # Standard HubSpot fields
    if email:
        p["email"] = email.lower()

    name = safe_str(row.get("person_name", ""))
    if name:
        parts = name.rsplit(" ", 1)
        p["firstname"] = parts[0]
        p["lastname"] = parts[1] if len(parts) > 1 else ""

    for hs_key, excel_key in [("phone", "person_phone"), ("address", "person_address"), ("state", "state")]:
        if v := safe_str(row.get(excel_key)):
            p[hs_key] = v

    def sp(hs_key, excel_key, transform=safe_str):
        v = transform(row.get(excel_key))
        if v is not None:
            p[hs_key] = v

    # SN custom + cross-mapped standard props
    sp("sn_person_id",       "resolved_person_id")
    sp("sn_native_id",       "native_person_id")
    sp("sn_brand",           "brand")
    sp("sn_source_platform", "source_platform")
    sp("sn_license_id",      "resolved_license_id")
    sp("sn_license_number",  "license_number")
    sp("sn_license_state",   "state")
    sp("sn_profession",      "profession")
    sp("sn_license_issued_date", "license_issued_date", safe_date)
    sp("sn_est_renewal_date",    "est_renewal_date",    safe_date)

    if "sn_est_renewal_date" in p:
        p["education_renewal_date_us_nurses"] = p["sn_est_renewal_date"]
    if lic := safe_str(row.get("license_number")):
        p["license_number"] = lic
    if st := safe_str(row.get("state")):
        p["license_state_abbreviation"] = st

    sp("sn_membership_status",   "mem_status")
    sp("sn_membership_tier",     "membership_tier")
    sp("sn_membership_cadence",  "membership_billing_cadence")
    sp("sn_mem_brand",           "mem_brand")
    sp("sn_mem_start_date",      "mem_start_date",  safe_date)
    sp("sn_mem_end_date",        "mem_end_date",    safe_date)

    if "sn_mem_end_date" in p:
        p["membership_end_date"] = p["sn_mem_end_date"]

    sp("sn_ce_period",           "ce_period")
    sp("sn_credits_required",    "credits_required",  safe_num)
    sp("sn_credits_completed",   "credits_completed", safe_num)
    sp("sn_ce_status",           "ce_status")
    sp("sn_ce_period_end_date",  "period_end_date",   safe_date)
    sp("sn_last_activity_date",  "last_activity_date",safe_date)
    sp("sn_consent_status",      "consent_status")
    sp("sn_consent_timestamp",   "consent_timestamp")
    sp("sn_specialty",           "speciality")
    sp("sn_nurse_professions",   "nurse_professions")

    if fe.get("linkedin_url"):
        p["sn_linkedin_url"] = fe["linkedin_url"]
    if fe.get("job_title"):
        p["sn_job_title"] = fe["job_title"]
        p["jobtitle"] = fe["job_title"]
    if fe.get("company"):
        p["sn_company"] = fe["company"]
        p["company"] = fe["company"]

    p["sn_enriched_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return {k: v for k, v in p.items() if v is not None}


# ---------------------------------------------------------------------------
# Step 5: Batch upsert contacts (create OR update by email)
# ---------------------------------------------------------------------------

def upsert_contacts(records, fe_data, dry_run):
    success = errors = 0
    valid = []

    for row in records:
        email = safe_str(row.get("person_email", ""))
        if not email:
            log("no email — skipping row", "  ⚠ ")
            errors += 1
            continue
        props = build_props(row, fe_data)
        valid.append({"id": email.lower(), "idProperty": "email", "properties": props})

    if dry_run:
        for item in valid:
            log(f"  [dry-run] {item['id']} — {len(item['properties'])} props", "  ")
        return len(valid), errors

    for batch in chunks(valid, BATCH_SIZE):
        r = requests.post(
            f"{HS_BASE}/crm/v3/objects/contacts/batch/upsert",
            headers=HS_HEADERS,
            json={"inputs": batch},
            timeout=30,
        )

        if r.status_code == 200:
            results = r.json().get("results", [])
            for item in results:
                email = item.get("properties", {}).get("email", "?")
                created = item.get("properties", {}).get("createdate", "") == item.get("properties", {}).get("lastmodifieddate", "X")
                action = "created" if created else "updated"
                log(f"  ✓ {email} ({action})", "  ")
            success += len(results)
        elif r.status_code == 207:
            # Partial success
            data = r.json()
            ok = data.get("results", [])
            errs = data.get("errors", [])
            for item in ok:
                log(f"  ✓ {item.get('properties',{}).get('email','?')}", "  ")
            for e in errs:
                log(f"  ✗ {e}", "  ")
            success += len(ok)
            errors += len(errs)
        else:
            log(f"  ✗ batch error {r.status_code}: {r.text[:200]}", "  ")
            errors += len(batch)

    return success, errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="SimpleNursing HubSpot Enrichment Pipeline")
    ap.add_argument("--dry-run",         action="store_true", help="No writes to HubSpot")
    ap.add_argument("--skip-fullenrich", action="store_true", help="Skip FullEnrich step")
    ap.add_argument("--excel",           default=EXCEL_FILE,  help="Excel file path")
    args = ap.parse_args()

    print("\n" + "=" * 58)
    print("  SimpleNursing HubSpot Enrichment Pipeline")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 58 + "\n")

    records = load_excel(args.excel)

    emails = [r.get("person_email", "") for r in records if r.get("person_email")]
    fe_data = fullenrich_reverse_lookup(emails, skip=args.skip_fullenrich)

    log("Setting up HubSpot properties…")
    ensure_property_group(dry_run=args.dry_run)
    ensure_properties(dry_run=args.dry_run)

    log(f"\nUpserting {len(records)} contacts (batch mode)…")
    ok, err = upsert_contacts(records, fe_data, dry_run=args.dry_run)

    print("\n" + "=" * 58)
    print("  RESULTS")
    print("=" * 58)
    print(f"  Total records   : {len(records)}")
    print(f"  Upserted ok     : {ok}")
    print(f"  Errors          : {err}")
    print(f"  FullEnrich hits : {len(fe_data)}")
    if args.dry_run:
        print("\n  Run without --dry-run to apply changes.")
    print("=" * 58 + "\n")


if __name__ == "__main__":
    main()
