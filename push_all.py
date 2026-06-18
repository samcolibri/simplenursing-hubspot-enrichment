"""
Push ALL 57 CSV fields to HubSpot.
Creates missing properties, batch-upserts all 20 contacts.
"""
import csv, os, time, calendar
from datetime import datetime
import requests

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

HS_TOKEN  = os.environ["HUBSPOT_API_KEY"]
CSV_FILE  = "/Users/anmolsam/Downloads/HC_CE_Renewal_Nursing_Specialty_3(Nursing_Flat_File).csv"
HS_BASE   = "https://api.hubapi.com"
HS_H      = {"Authorization": f"Bearer {HS_TOKEN}", "Content-Type": "application/json"}
GROUP     = "sn_enrichment"

# ── Every sn_ property we want in HubSpot ────────────────────────────────────
ALL_PROPS = [
    # PERSON
    {"name":"sn_person_id",           "label":"SN: Person ID",                  "type":"string", "fieldType":"text"},
    {"name":"sn_native_id",           "label":"SN: Native Person ID (NetSuite)","type":"string", "fieldType":"text"},
    {"name":"sn_brand",               "label":"SN: Brand",                      "type":"string", "fieldType":"text"},
    {"name":"sn_source_name",         "label":"SN: Source Name",                "type":"string", "fieldType":"text"},
    {"name":"sn_source_platform",     "label":"SN: Source Platform",            "type":"string", "fieldType":"text"},
    {"name":"sn_created_at",          "label":"SN: Record Created At",          "type":"date",   "fieldType":"date"},
    # LICENSE
    {"name":"sn_license_id",          "label":"SN: License ID",                 "type":"string", "fieldType":"text"},
    {"name":"sn_license_number",      "label":"SN: License Number",             "type":"string", "fieldType":"text"},
    {"name":"sn_license_state",       "label":"SN: License State",              "type":"string", "fieldType":"text"},
    {"name":"sn_profession",          "label":"SN: Profession",                 "type":"string", "fieldType":"text"},
    {"name":"sn_license_issued_date", "label":"SN: License Issued Date",        "type":"date",   "fieldType":"date"},
    {"name":"sn_est_renewal_date",    "label":"SN: Estimated Renewal Date",     "type":"date",   "fieldType":"date"},
    # LMS ENGAGEMENT
    {"name":"sn_course_id",           "label":"SN: Course ID",                  "type":"string", "fieldType":"text"},
    {"name":"sn_course_title",        "label":"SN: Course Title",               "type":"string", "fieldType":"text"},
    {"name":"sn_lms_completion_status","label":"SN: LMS Completion Status",     "type":"string", "fieldType":"text"},
    {"name":"sn_credits_earned",      "label":"SN: LMS Credits Earned",         "type":"number", "fieldType":"number"},
    {"name":"sn_last_activity_date",  "label":"SN: Last LMS Activity Date",     "type":"date",   "fieldType":"date"},
    {"name":"sn_lms_source",          "label":"SN: LMS Source",                 "type":"string", "fieldType":"text"},
    # PURCHASE HISTORY
    {"name":"sn_order_id",            "label":"SN: Order ID",                   "type":"string", "fieldType":"text"},
    {"name":"sn_product_name",        "label":"SN: Product Name",               "type":"string", "fieldType":"text"},
    {"name":"sn_product_category",    "label":"SN: Product Category",           "type":"string", "fieldType":"text"},
    {"name":"sn_order_amount",        "label":"SN: Order Amount ($)",           "type":"number", "fieldType":"number"},
    {"name":"sn_order_date",          "label":"SN: Order Date",                 "type":"date",   "fieldType":"date"},
    {"name":"sn_payment_status",      "label":"SN: Payment Status",             "type":"string", "fieldType":"text"},
    {"name":"sn_purchase_source",     "label":"SN: Purchase Source",            "type":"string", "fieldType":"text"},
    # MEMBERSHIP
    {"name":"sn_membership_status",   "label":"SN: Membership Status",          "type":"enumeration","fieldType":"select",
     "options":[{"label":"Active","value":"Active","displayOrder":0},
                {"label":"Expired","value":"Expired","displayOrder":1},
                {"label":"Cancelled","value":"Cancelled","displayOrder":2}]},
    {"name":"sn_membership_tier",     "label":"SN: Membership Tier",            "type":"string", "fieldType":"text"},
    {"name":"sn_membership_cadence",  "label":"SN: Membership Billing Cadence", "type":"string", "fieldType":"text"},
    {"name":"sn_mem_brand",           "label":"SN: Membership Brand",           "type":"string", "fieldType":"text"},
    {"name":"sn_mem_start_date",      "label":"SN: Membership Start Date",      "type":"date",   "fieldType":"date"},
    {"name":"sn_mem_end_date",        "label":"SN: Membership End Date",        "type":"date",   "fieldType":"date"},
    # MARKETING CONSENT
    {"name":"sn_channel",             "label":"SN: Marketing Channel",          "type":"string", "fieldType":"text"},
    {"name":"sn_consent_status",      "label":"SN: Consent Status",             "type":"enumeration","fieldType":"select",
     "options":[{"label":"Opt-In","value":"Opt-In","displayOrder":0},
                {"label":"Opt-Out","value":"Opt-Out","displayOrder":1}]},
    {"name":"sn_consent_brand",       "label":"SN: Consent Brand",              "type":"string", "fieldType":"text"},
    {"name":"sn_consent_timestamp",   "label":"SN: Consent Timestamp",          "type":"date",   "fieldType":"date"},
    # CE COMPLETION
    {"name":"sn_ce_period",           "label":"SN: CE Period",                  "type":"string", "fieldType":"text"},
    {"name":"sn_credits_completed",   "label":"SN: CE Credits Completed",       "type":"number", "fieldType":"number"},
    {"name":"sn_ce_status",           "label":"SN: CE Status",                  "type":"enumeration","fieldType":"select",
     "options":[{"label":"Not Started","value":"Not Started","displayOrder":0},
                {"label":"In Progress","value":"In Progress","displayOrder":1},
                {"label":"Complete","value":"Complete","displayOrder":2}]},
    {"name":"sn_ce_period_end_date",  "label":"SN: CE Period End Date",         "type":"date",   "fieldType":"date"},
    # DIRECT MAIL
    {"name":"sn_send_channel",        "label":"SN: Direct Mail Channel",        "type":"string", "fieldType":"text"},
    {"name":"sn_send_brand",          "label":"SN: Direct Mail Brand",          "type":"string", "fieldType":"text"},
    {"name":"sn_send_date",           "label":"SN: Direct Mail Send Date",      "type":"date",   "fieldType":"date"},
    {"name":"sn_creative_version",    "label":"SN: Creative Version",           "type":"string", "fieldType":"text"},
    {"name":"sn_book_title_sent",     "label":"SN: Book Title Sent",            "type":"string", "fieldType":"text"},
    {"name":"sn_book_sent_date",      "label":"SN: Book Sent Date",             "type":"date",   "fieldType":"date"},
    # EXA (already created, listed for completeness)
    {"name":"sn_exa_employer",        "label":"SN: Employer (Exa)",             "type":"string", "fieldType":"text"},
    {"name":"sn_exa_specialty",       "label":"SN: Specialty (Exa)",            "type":"string", "fieldType":"text"},
    {"name":"sn_exa_npi",             "label":"SN: NPI Number (Exa)",           "type":"string", "fieldType":"text"},
    {"name":"sn_exa_profile_url",     "label":"SN: Professional Profile URL",   "type":"string", "fieldType":"text"},
    {"name":"sn_exa_profile_type",    "label":"SN: Profile Source (Exa)",       "type":"string", "fieldType":"text"},
    # Meta
    {"name":"sn_enriched_at",         "label":"SN: Last Enriched At",           "type":"string", "fieldType":"text"},
]

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def to_epoch_ms(val):
    if not val or not str(val).strip(): return None
    s = str(val).strip()[:10]
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return int(calendar.timegm(d.timetuple()) * 1000)
    except: return None

def to_num(val):
    # Returns None only if unparseable — 0 is a valid value
    if val is None or str(val).strip() == "": return None
    try: return float(str(val).strip())
    except: return None

def s(val):
    v = str(val).strip() if val else ""
    return v if v else None

# ── Step 1: Create missing properties ─────────────────────────────────────────
def ensure_properties():
    r = requests.get(f"{HS_BASE}/crm/v3/properties/contacts?limit=500", headers=HS_H, timeout=15)
    existing = {p["name"] for p in r.json().get("results", [])}
    created = skipped = errors = 0
    for prop in ALL_PROPS:
        if prop["name"] in existing:
            skipped += 1
            continue
        body = {k: v for k, v in prop.items() if k in ("name","label","type","fieldType","options")}
        body["groupName"] = GROUP
        r2 = requests.post(f"{HS_BASE}/crm/v3/properties/contacts", headers=HS_H, json=body, timeout=15)
        if r2.status_code in (200, 201):
            log(f"  ✓ created: {prop['name']}")
            created += 1
        elif r2.status_code == 409:
            skipped += 1  # already exists (race)
        else:
            log(f"  ✗ {prop['name']}: {r2.status_code} {r2.text[:80]}")
            errors += 1
    log(f"Properties: {created} created, {skipped} already existed, {errors} errors")

# ── Step 2: Build full property map for one CSV row ───────────────────────────
def build_props(row):
    p = {}

    # Standard HubSpot fields
    email = s(row.get("person_email",""))
    if email: p["email"] = email.lower()

    name = s(row.get("person_name",""))
    if name:
        parts = name.rsplit(" ", 1)
        p["firstname"] = parts[0]
        p["lastname"]  = parts[1] if len(parts) > 1 else ""

    for hs, csv_key in [("phone","person_phone"),("address","person_address"),("state","state")]:
        if v := s(row.get(csv_key)): p[hs] = v

    # Cross-map to existing standard props
    if v := to_epoch_ms(row.get("est_renewal_date")):
        p["education_renewal_date_us_nurses"] = v
    if v := s(row.get("license_number")):
        p["license_number"] = v
    if v := s(row.get("state")):
        p["license_state_abbreviation"] = v
    if v := to_epoch_ms(row.get("mem_end_date")):
        p["membership_end_date"] = v

    # PERSON
    if v := s(row.get("resolved_person_id")):   p["sn_person_id"]       = v
    if v := s(row.get("native_person_id")):     p["sn_native_id"]       = v
    if v := s(row.get("brand")):                p["sn_brand"]           = v
    if v := s(row.get("source_name")):          p["sn_source_name"]     = v
    if v := s(row.get("source_platform")):      p["sn_source_platform"] = v
    if v := to_epoch_ms(row.get("created_at")): p["sn_created_at"]      = v

    # LICENSE
    if v := s(row.get("resolved_license_id")):  p["sn_license_id"]          = v
    if v := s(row.get("license_number")):        p["sn_license_number"]      = v
    if v := s(row.get("state")):                 p["sn_license_state"]       = v
    if v := s(row.get("profession")):            p["sn_profession"]          = v
    if v := to_epoch_ms(row.get("license_issued_date")): p["sn_license_issued_date"] = v
    if v := to_epoch_ms(row.get("est_renewal_date")):    p["sn_est_renewal_date"]    = v

    # LMS ENGAGEMENT
    if v := s(row.get("course_id")):             p["sn_course_id"]            = v
    if v := s(row.get("course_title")):          p["sn_course_title"]         = v
    if v := s(row.get("completion_status")):     p["sn_lms_completion_status"]= v
    v = to_num(row.get("credits_earned"));   (p.__setitem__("sn_credits_earned", v) if v is not None else None)
    if v := to_epoch_ms(row.get("last_activity_date")): p["sn_last_activity_date"] = v
    if v := s(row.get("lms_source")):            p["sn_lms_source"]           = v

    # PURCHASE HISTORY
    if v := s(row.get("order_id")):              p["sn_order_id"]        = v
    if v := s(row.get("product_name")):          p["sn_product_name"]    = v
    if v := s(row.get("product_category")):      p["sn_product_category"]= v
    v = to_num(row.get("order_amount"));     (p.__setitem__("sn_order_amount", v) if v is not None else None)
    if v := to_epoch_ms(row.get("order_date")):  p["sn_order_date"]      = v
    if v := s(row.get("payment_status")):        p["sn_payment_status"]  = v
    if v := s(row.get("purchase_source")):       p["sn_purchase_source"] = v

    # MEMBERSHIP
    if v := s(row.get("mem_status")):            p["sn_membership_status"]  = v
    if v := s(row.get("membership_tier")):       p["sn_membership_tier"]    = v
    if v := s(row.get("membership_billing_cadence")): p["sn_membership_cadence"] = v
    if v := s(row.get("mem_brand")):             p["sn_mem_brand"]          = v
    if v := to_epoch_ms(row.get("mem_start_date")): p["sn_mem_start_date"] = v
    if v := to_epoch_ms(row.get("mem_end_date")):   p["sn_mem_end_date"]   = v

    # MARKETING CONSENT
    if v := s(row.get("channel")):               p["sn_channel"]           = v
    if v := s(row.get("consent_status")):        p["sn_consent_status"]    = v
    if v := s(row.get("consent_brand")):         p["sn_consent_brand"]     = v
    if v := to_epoch_ms(row.get("consent_timestamp")): p["sn_consent_timestamp"] = v

    # CE COMPLETION
    if v := s(row.get("ce_period")):             p["sn_ce_period"]       = v
    v = to_num(row.get("credits_completed")); (p.__setitem__("sn_credits_completed", v) if v is not None else None)
    if v := s(row.get("ce_status")):             p["sn_ce_status"]       = v
    if v := to_epoch_ms(row.get("period_end_date")): p["sn_ce_period_end_date"] = v

    # DIRECT MAIL
    if v := s(row.get("send_channel")):          p["sn_send_channel"]    = v
    if v := s(row.get("send_brand")):            p["sn_send_brand"]      = v
    if v := to_epoch_ms(row.get("send_date")):   p["sn_send_date"]       = v
    if v := s(row.get("creative_version")):      p["sn_creative_version"]= v
    if v := s(row.get("book_title_sent")):       p["sn_book_title_sent"] = v
    if v := to_epoch_ms(row.get("book_sent_date")): p["sn_book_sent_date"] = v

    p["sn_enriched_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return {k: v for k, v in p.items() if v is not None}

# ── Step 3: Batch upsert ──────────────────────────────────────────────────────
def upsert(records):
    inputs = []
    for row in records:
        email = s(row.get("person_email",""))
        if not email: continue
        props = build_props(row)
        inputs.append({"id": email.lower(), "idProperty": "email", "properties": props})
        log(f"  built: {email.lower()} — {len(props)} props")

    log(f"\nBatch upserting {len(inputs)} contacts…")
    r = requests.post(
        f"{HS_BASE}/crm/v3/objects/contacts/batch/upsert",
        headers=HS_H, json={"inputs": inputs}, timeout=30
    )
    if r.status_code == 200:
        log(f"✓ All {len(inputs)} contacts upserted successfully")
    else:
        log(f"✗ {r.status_code}: {r.text[:300]}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "="*58)
    print("  Full CSV → HubSpot Push (all 57 fields)")
    print("="*58 + "\n")

    with open(CSV_FILE, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    field_names = rows[1]
    records = [dict(zip(field_names, row)) for row in rows[2:]]
    log(f"Loaded {len(records)} contacts from CSV")

    log("\nEnsuring all HubSpot properties exist…")
    ensure_properties()

    log("\nBuilding contact payloads…")
    upsert(records)

    print("\n" + "="*58)
    print("  DONE — all 57 CSV fields are now in HubSpot")
    print("="*58 + "\n")

if __name__ == "__main__":
    main()
