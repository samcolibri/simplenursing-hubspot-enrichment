import csv, requests

import os
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
HS_TOKEN = os.environ["HUBSPOT_API_KEY"]
HS_H = {"Authorization": f"Bearer {HS_TOKEN}", "Content-Type": "application/json"}
HS_BASE = "https://api.hubapi.com"

CSV_IN  = _csv_file()
CSV_OUT = _csv_file()

# Exact CSV col index -> HubSpot property name (57 columns, in order)
HS_PROP_ROW = [
    "sn_person_id",           # resolved_person_id
    "firstname + lastname",   # person_name  (split on write)
    "email",                  # person_email
    "address",                # person_address
    "phone",                  # person_phone
    "sn_created_at",          # created_at
    "sn_source_name",         # source_name
    "sn_source_platform",     # source_platform
    "sn_native_id",           # native_person_id
    "sn_brand",               # brand
    "sn_license_id",          # resolved_license_id
    "sn_license_number",      # license_number
    "sn_license_state",       # state
    "sn_profession",          # profession
    "sn_license_issued_date", # license_issued_date
    "sn_est_renewal_date",    # est_renewal_date
    "sn_course_id",           # course_id
    "sn_course_title",        # course_title
    "sn_lms_completion_status", # completion_status
    "sn_credits_earned",      # credits_earned
    "(no data)",              # score
    "sn_last_activity_date",  # last_activity_date
    "sn_lms_source",          # lms_source
    "sn_order_id",            # order_id
    "sn_product_name",        # product_name
    "sn_product_category",    # product_category
    "sn_order_amount",        # order_amount
    "sn_order_date",          # order_date
    "sn_payment_status",      # payment_status
    "sn_purchase_source",     # purchase_source
    "sn_membership_cadence",  # membership_billing_cadence
    "sn_membership_tier",     # membership_tier
    "sn_mem_brand",           # mem_brand
    "sn_mem_start_date",      # mem_start_date
    "sn_mem_end_date",        # mem_end_date
    "sn_membership_status",   # mem_status
    "sn_channel",             # channel
    "sn_consent_status",      # consent_status
    "sn_consent_brand",       # consent_brand
    "sn_consent_timestamp",   # consent_timestamp
    "sn_ce_period",           # ce_period
    "(no data)",              # credits_required
    "sn_credits_completed",   # credits_completed
    "sn_ce_status",           # ce_status
    "sn_ce_period_end_date",  # period_end_date
    "(no data)",              # send_id
    "(no data)",              # campaign_name
    "sn_send_channel",        # send_channel
    "sn_send_brand",          # send_brand
    "sn_send_date",           # send_date
    "sn_creative_version",    # creative_version
    "sn_book_title_sent",     # book_title_sent
    "sn_book_sent_date",      # book_sent_date
    "(no data)",              # response_flag
    "(no data)",              # response_date
    "(no data)",              # speciality
    "(no data)",              # nurse_professions
]

# Read original CSV
with open(CSV_IN, newline="", encoding="utf-8-sig") as f:
    raw = list(csv.reader(f))

section_row = raw[0]   # row 0: PERSON, PERSON SOURCE, etc.
field_row   = raw[1]   # row 1: resolved_person_id, person_name, etc.
data_rows   = raw[2:]  # row 2+: actual data

# Fetch HubSpot IDs for all contacts
print("Fetching HubSpot IDs...")
id_map = {}
for row in data_rows:
    if len(row) < 3: continue
    email = row[2].strip().lower()
    if not email: continue
    r = requests.get(
        f"{HS_BASE}/crm/v3/objects/contacts/{email}",
        headers=HS_H, params={"idProperty": "email", "properties": "email"}, timeout=15
    )
    if r.status_code == 200:
        hs_id = r.json().get("id", "")
        id_map[email] = hs_id
        print(f"  ✓ {email:45} → {hs_id}")
    else:
        id_map[email] = ""
        print(f"  ✗ {email} not found")

# Build new CSV rows — HubSpot ID as LAST column
new_section_row = section_row + ["HUBSPOT"]
new_field_row   = field_row   + ["hubspot_id"]
new_hs_prop_row = HS_PROP_ROW + ["hs_object_id"]

new_data_rows = []
for row in data_rows:
    email = row[2].strip().lower() if len(row) > 2 else ""
    hs_id = id_map.get(email, "")
    new_data_rows.append(row + [hs_id])

# Write updated CSV
with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(new_section_row)  # row 1: section headers
    writer.writerow(new_field_row)    # row 2: csv field names
    writer.writerow(new_hs_prop_row)  # row 3: hubspot property names  ← NEW
    writer.writerows(new_data_rows)   # row 4+: data with hs_id appended

print(f"\n✓ CSV written to: {CSV_OUT}")
print(f"  Rows: {len(new_data_rows)} data rows")
print(f"  Cols: {len(new_section_row)} (added hubspot_id as last column)")
print(f"  Row 3 (new HS property row): {len(new_hs_prop_row)} entries")
