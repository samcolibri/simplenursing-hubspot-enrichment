import csv, requests, os

import os
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
HS_TOKEN = os.environ["HUBSPOT_API_KEY"]
HS_H = {"Authorization": f"Bearer {HS_TOKEN}", "Content-Type": "application/json"}
HS_BASE = "https://api.hubapi.com"

ALL_SN = [
    "email","firstname","lastname","phone","address","state",
    "license_number","license_state_abbreviation","education_renewal_date_us_nurses","membership_end_date",
    "sn_person_id","sn_native_id","sn_brand","sn_source_name","sn_source_platform","sn_created_at",
    "sn_license_id","sn_license_number","sn_license_state","sn_profession","sn_license_issued_date","sn_est_renewal_date",
    "sn_course_id","sn_course_title","sn_lms_completion_status","sn_credits_earned","sn_last_activity_date","sn_lms_source",
    "sn_order_id","sn_product_name","sn_product_category","sn_order_amount","sn_order_date","sn_payment_status","sn_purchase_source",
    "sn_membership_status","sn_membership_tier","sn_membership_cadence","sn_mem_brand","sn_mem_start_date","sn_mem_end_date",
    "sn_channel","sn_consent_status","sn_consent_brand","sn_consent_timestamp",
    "sn_ce_period","sn_credits_completed","sn_ce_status","sn_ce_period_end_date",
    "sn_send_channel","sn_send_brand","sn_send_date","sn_creative_version","sn_book_title_sent","sn_book_sent_date",
    "sn_exa_employer","sn_exa_specialty","sn_exa_npi","sn_exa_profile_url","sn_exa_profile_type","sn_enriched_at"
]

# CSV field -> sn_ property name mapping
MAPPING = {
    "resolved_person_id": "sn_person_id",
    "native_person_id":   "sn_native_id",
    "brand":              "sn_brand",
    "source_name":        "sn_source_name",
    "source_platform":    "sn_source_platform",
    "created_at":         "sn_created_at",
    "resolved_license_id":"sn_license_id",
    "license_number":     "sn_license_number",
    "state":              "sn_license_state",
    "profession":         "sn_profession",
    "license_issued_date":"sn_license_issued_date",
    "est_renewal_date":   "sn_est_renewal_date",
    "course_id":          "sn_course_id",
    "course_title":       "sn_course_title",
    "completion_status":  "sn_lms_completion_status",
    "credits_earned":     "sn_credits_earned",
    "last_activity_date": "sn_last_activity_date",
    "lms_source":         "sn_lms_source",
    "order_id":           "sn_order_id",
    "product_name":       "sn_product_name",
    "product_category":   "sn_product_category",
    "order_amount":       "sn_order_amount",
    "order_date":         "sn_order_date",
    "payment_status":     "sn_payment_status",
    "purchase_source":    "sn_purchase_source",
    "membership_billing_cadence": "sn_membership_cadence",
    "membership_tier":    "sn_membership_tier",
    "mem_brand":          "sn_mem_brand",
    "mem_start_date":     "sn_mem_start_date",
    "mem_end_date":       "sn_mem_end_date",
    "mem_status":         "sn_membership_status",
    "channel":            "sn_channel",
    "consent_status":     "sn_consent_status",
    "consent_brand":      "sn_consent_brand",
    "consent_timestamp":  "sn_consent_timestamp",
    "ce_period":          "sn_ce_period",
    "credits_completed":  "sn_credits_completed",
    "ce_status":          "sn_ce_status",
    "period_end_date":    "sn_ce_period_end_date",
    "send_channel":       "sn_send_channel",
    "send_brand":         "sn_send_brand",
    "send_date":          "sn_send_date",
    "creative_version":   "sn_creative_version",
    "book_title_sent":    "sn_book_title_sent",
    "book_sent_date":     "sn_book_sent_date",
    "speciality":         "sn_specialty",
    "nurse_professions":  "sn_nurse_professions",
}

with open(_csv_file(), newline="") as f:
    rows = list(csv.reader(f))
field_names = rows[1]
records = [dict(zip(field_names, r)) for r in rows[2:]]

# Per-contact: which CSV fields have data vs which sn_ is empty in HS
print("\n=== ALL 20 CONTACTS: CSV vs HubSpot field fill ===\n")
print("%-45s | %-10s | %-11s | sn_ gaps" % ("Email", "CSV filled", "HS filled"))
print("-"*100)

gap_summary = {}  # sn_field -> how many contacts missing it
for r in records:
    email = r.get("person_email","").strip().lower()
    csv_filled = {k: v for k, v in r.items() if v and v.strip()}

    hs_r = requests.get(
        f"{HS_BASE}/crm/v3/objects/contacts/{email}",
        headers=HS_H,
        params={"idProperty": "email", "properties": ",".join(ALL_SN)},
        timeout=15
    )
    p = hs_r.json().get("properties", {})
    hs_filled = [k for k, v in p.items() if v and not k.startswith("hs_") and k not in ["createdate","lastmodifieddate"]]

    # Find sn_ fields that are empty in HS but HAD data in CSV
    gaps_with_data = []
    gaps_no_data   = []
    for csv_field, sn_field in MAPPING.items():
        if not p.get(sn_field):
            if csv_filled.get(csv_field):
                gaps_with_data.append(f"{csv_field}->{sn_field}")
            else:
                gaps_no_data.append(sn_field)

    gap_note = ""
    if gaps_with_data:
        gap_note = f"DATA MISSING: {gaps_with_data}"
    else:
        gap_note = f"{len(gaps_no_data)} empty (no CSV data)"

    for g in gaps_no_data:
        gap_summary[g] = gap_summary.get(g, 0) + 1

    print("%-45s | %-10d | %-11d | %s" % (email, len(csv_filled), len(hs_filled), gap_note))

print("\n\n=== CSV HEADER  →  HubSpot Property Name mapping ===\n")
print("%-35s → %s" % ("CSV Header (source)", "HubSpot Property Name"))
print("-"*75)
for csv_f, hs_f in MAPPING.items():
    print("%-35s → %s" % (csv_f, hs_f))

print("\n\n=== sn_ properties empty on ALL 20 contacts (CSV also empty — no data) ===")
for f, count in sorted(gap_summary.items(), key=lambda x: -x[1]):
    if count == 20:
        print(f"  {f} (no data in CSV for any contact)")
