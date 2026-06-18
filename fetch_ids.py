import csv, requests

import os
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
HS_TOKEN = os.environ["HUBSPOT_API_KEY"]
HS_H = {"Authorization": f"Bearer {HS_TOKEN}", "Content-Type": "application/json"}
HS_BASE = "https://api.hubapi.com"

with open("/Users/anmolsam/Downloads/HC_CE_Renewal_Nursing_Specialty_3(Nursing_Flat_File).csv", newline="") as f:
    rows = list(csv.reader(f))
field_names = rows[1]
records = [dict(zip(field_names, r)) for r in rows[2:]]
emails = [r.get("person_email","").strip().lower() for r in records]

print("Fetching HubSpot IDs for all 20 contacts...")
id_map = {}
for email in emails:
    r = requests.get(
        f"{HS_BASE}/crm/v3/objects/contacts/{email}",
        headers=HS_H, params={"idProperty": "email", "properties": "email"}, timeout=15
    )
    if r.status_code == 200:
        hs_id = r.json().get("id")
        id_map[email] = hs_id
        print(f"  ✓ {email:45} → {hs_id}")
    else:
        print(f"  ✗ {email:45} → {r.status_code}")

print(f"\nFound {len(id_map)}/20")
