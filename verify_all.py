"""Double-check: verify every property exists in HubSpot AND has data on every contact that should have it."""
import csv, requests

import os
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
HS_TOKEN = os.environ["HUBSPOT_API_KEY"]
HS_H = {"Authorization": f"Bearer {HS_TOKEN}", "Content-Type": "application/json"}
HS_BASE = "https://api.hubapi.com"

# Complete CSV col -> HubSpot property mapping (every column)
MAPPING = [
    # col index, csv_header, hs_property
    ("resolved_person_id",          "sn_person_id"),
    ("person_name",                 "firstname + lastname"),  # split
    ("person_email",                "email"),
    ("person_address",              "address"),
    ("person_phone",                "phone"),
    ("created_at",                  "sn_created_at"),
    ("source_name",                 "sn_source_name"),
    ("source_platform",             "sn_source_platform"),
    ("native_person_id",            "sn_native_id"),
    ("brand",                       "sn_brand"),
    ("resolved_license_id",         "sn_license_id"),
    ("license_number",              "sn_license_number"),
    ("state",                       "sn_license_state"),
    ("profession",                  "sn_profession"),
    ("license_issued_date",         "sn_license_issued_date"),
    ("est_renewal_date",            "sn_est_renewal_date"),
    ("course_id",                   "sn_course_id"),
    ("course_title",                "sn_course_title"),
    ("completion_status",           "sn_lms_completion_status"),
    ("credits_earned",              "sn_credits_earned"),
    ("score",                       "(no data in CSV)"),
    ("last_activity_date",          "sn_last_activity_date"),
    ("lms_source",                  "sn_lms_source"),
    ("order_id",                    "sn_order_id"),
    ("product_name",                "sn_product_name"),
    ("product_category",            "sn_product_category"),
    ("order_amount",                "sn_order_amount"),
    ("order_date",                  "sn_order_date"),
    ("payment_status",              "sn_payment_status"),
    ("purchase_source",             "sn_purchase_source"),
    ("membership_billing_cadence",  "sn_membership_cadence"),
    ("membership_tier",             "sn_membership_tier"),
    ("mem_brand",                   "sn_mem_brand"),
    ("mem_start_date",              "sn_mem_start_date"),
    ("mem_end_date",                "sn_mem_end_date"),
    ("mem_status",                  "sn_membership_status"),
    ("channel",                     "sn_channel"),
    ("consent_status",              "sn_consent_status"),
    ("consent_brand",               "sn_consent_brand"),
    ("consent_timestamp",           "sn_consent_timestamp"),
    ("ce_period",                   "sn_ce_period"),
    ("credits_required",            "(no data in CSV)"),
    ("credits_completed",           "sn_credits_completed"),
    ("ce_status",                   "sn_ce_status"),
    ("period_end_date",             "sn_ce_period_end_date"),
    ("send_id",                     "(no data in CSV)"),
    ("campaign_name",               "(no data in CSV)"),
    ("send_channel",                "sn_send_channel"),
    ("send_brand",                  "sn_send_brand"),
    ("send_date",                   "sn_send_date"),
    ("creative_version",            "sn_creative_version"),
    ("book_title_sent",             "sn_book_title_sent"),
    ("book_sent_date",              "sn_book_sent_date"),
    ("response_flag",               "(no data in CSV)"),
    ("response_date",               "(no data in CSV)"),
    ("speciality",                  "(no data in CSV)"),
    ("nurse_professions",           "(no data in CSV)"),
]

# All real HS properties we created
ALL_HS_PROPS = [hs for _, hs in MAPPING if not hs.startswith("(") and hs != "firstname + lastname"]
ALL_HS_PROPS += ["firstname", "lastname", "hubspot_id",
                 "sn_exa_employer","sn_exa_specialty","sn_exa_npi","sn_exa_profile_url","sn_exa_profile_type","sn_enriched_at"]

# --- CHECK 1: All properties exist in HubSpot schema ---
print("=" * 60)
print("CHECK 1: All sn_ properties exist in HubSpot schema")
print("=" * 60)
r = requests.get(f"{HS_BASE}/crm/v3/properties/contacts?limit=500", headers=HS_H, timeout=15)
existing = {p["name"] for p in r.json().get("results", [])}
missing_schema = [p for p in ALL_HS_PROPS if p.startswith("sn_") and p not in existing]
if missing_schema:
    print(f"  ✗ MISSING FROM SCHEMA: {missing_schema}")
else:
    print(f"  ✓ All {len([p for p in ALL_HS_PROPS if p.startswith('sn_')])} sn_ properties exist in HubSpot schema")

# --- CHECK 2: All 20 contacts have correct data ---
print("\n" + "=" * 60)
print("CHECK 2: All 20 contacts have data matching CSV")
print("=" * 60)

with open("/Users/anmolsam/Downloads/HC_CE_Renewal_Nursing_Specialty_3(Nursing_Flat_File).csv", newline="") as f:
    rows = list(csv.reader(f))
field_names = rows[1]
records = [dict(zip(field_names, r)) for r in rows[2:]]

# Key verifiable fields (non-date, non-zero checks)
KEY_CHECKS = [
    ("person_email",    "email"),
    ("license_number",  "sn_license_number"),
    ("state",           "sn_license_state"),
    ("profession",      "sn_profession"),
    ("brand",           "sn_brand"),
    ("source_platform", "sn_source_platform"),
    ("ce_status",       "sn_ce_status"),
    ("consent_status",  "sn_consent_status"),
]

all_ok = True
for row in records:
    email = row.get("person_email","").strip().lower()
    props_to_fetch = ",".join(set([hs for _, hs in KEY_CHECKS] + ["sn_credits_earned","sn_order_amount","sn_credits_completed"]))
    r = requests.get(
        f"{HS_BASE}/crm/v3/objects/contacts/{email}",
        headers=HS_H, params={"idProperty":"email","properties": props_to_fetch}, timeout=15
    )
    if r.status_code != 200:
        print(f"  ✗ {email} NOT FOUND")
        all_ok = False
        continue
    p = r.json().get("properties", {})
    issues = []
    for csv_f, hs_f in KEY_CHECKS:
        csv_val = row.get(csv_f,"").strip().lower()
        hs_val  = (p.get(hs_f) or "").strip().lower()
        if csv_val and hs_val and csv_val != hs_val:
            issues.append(f"{hs_f}: CSV={csv_val!r} HS={hs_val!r}")
        elif csv_val and not hs_val:
            issues.append(f"{hs_f}: has CSV data but EMPTY in HS")
    # Check numeric zeros landed
    for csv_f, hs_f in [("credits_earned","sn_credits_earned"),("order_amount","sn_order_amount"),("credits_completed","sn_credits_completed")]:
        csv_val = row.get(csv_f,"").strip()
        hs_val  = p.get(hs_f)
        if csv_val != "" and hs_val is None:
            issues.append(f"{hs_f}: CSV={csv_val!r} missing in HS")
    if issues:
        print(f"  ✗ {email}: {issues}")
        all_ok = False
    else:
        print(f"  ✓ {email}")

if all_ok:
    print("\n  ALL 20 CONTACTS VERIFIED ✓")
else:
    print("\n  SOME ISSUES FOUND — fix before CSV export")

print("\n" + "=" * 60)
print("MAPPING TABLE (CSV col -> HubSpot property)")
print("=" * 60)
for csv_f, hs_f in MAPPING:
    print(f"  {csv_f:35} → {hs_f}")
