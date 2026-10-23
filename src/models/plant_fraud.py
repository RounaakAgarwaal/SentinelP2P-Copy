import csv
import random
from datetime import datetime, timedelta

random.seed(42)

# ============================================================
# READ ALL EXISTING DATA FIRST
# ============================================================

with open("../../data/employees.csv", "r", encoding="utf-8") as f:
    employees = list(csv.DictReader(f))

with open("../../data/vendors.csv", "r", encoding="utf-8") as f:
    vendors = list(csv.DictReader(f))

with open("../../data/purchase_orders.csv", "r", encoding="utf-8") as f:
    pos = list(csv.DictReader(f))

with open("../../data/invoices.csv", "r", encoding="utf-8") as f:
    invoices = list(csv.DictReader(f))

with open("../../data/contracts.csv", "r", encoding="utf-8") as f:
    contracts = list(csv.DictReader(f))

# ============================================================
# FRAUD TYPE 1: SHELL VENDOR (scaled up to 15 cases)
# ============================================================

next_vendor_num = len(vendors) + 1
shell_vendor_names = [f"Shell Vendor {i}" for i in range(1, 16)]

for case in range(15):
    employee = random.choice(employees)
    vendor_id = f"VEN{next_vendor_num:03d}"

    vendors.append({
        "vendor_id": vendor_id,
        "vendor_name": shell_vendor_names[case],
        "email": employee["email"],  # exact same email as the employee - strong shell signal
        "phone": employee["phone"],
        "address": "Unit 4B, Industrial Estate, Remote City",
        "bank_account": f"GB00FAKE0000000000{case}",
        "registration_number": "UNVERIFIED",
        "vendor_category": random.choice(["IT Hardware", "Office Supplies", "Catering"]),
        "onboarding_date": (datetime(2026, 1, 1) + timedelta(days=case)).strftime("%Y-%m-%d"),
        "has_contract": "No",
        "created_by_employee_id": employee["employee_id"]
    })
    next_vendor_num += 1

print("Planted 15 shell-vendor fraud cases")

# ============================================================
# FRAUD TYPE 2: SPLIT PURCHASE ORDERS (scaled up to 15 pairs)
# ============================================================

next_po_num = len(pos) + 1

for case in range(15):
    vendor = random.choice(vendors)
    employee = random.choice(employees)
    same_date = datetime(2026, 3, 1) + timedelta(days=case * 5)
    total_amount = random.choice([16000, 18000, 20000])

    for half in range(2):
        po_id = f"PO{next_po_num:04d}"
        pos.append({
            "po_id": po_id,
            "vendor_id": vendor["vendor_id"],
            "amount": str(total_amount / 2),
            "item_category": vendor["vendor_category"],
            "date": same_date.strftime("%Y-%m-%d"),
            "created_by_employee_id": employee["employee_id"],
            "approved_by_employee_id": random.choice(employees)["employee_id"],
            "payment_terms": "Net 30"
        })
        next_po_num += 1

print("Planted 15 split-PO fraud cases")

# ============================================================
# FRAUD TYPE 3: DUPLICATE INVOICE (scaled up to 15 cases)
# ============================================================

next_invoice_num = len(invoices) + 1

def reword(description):
    return description + " (resubmitted)"

originals_to_duplicate = random.sample(invoices, 15)

for original in originals_to_duplicate:
    new_invoice_id = f"INV{next_invoice_num:04d}"
    invoices.append({
        "invoice_id": new_invoice_id,
        "po_id": original["po_id"],
        "amount": original["amount"],
        "item_category": original["item_category"],
        "description": reword(original["description"]),
        "date": original["date"],
        "payment_status": "Pending",
        "submitted_by_employee_id": random.choice(employees)["employee_id"]
    })
    next_invoice_num += 1

print("Planted 15 duplicate-invoice fraud cases")

# ============================================================
# FRAUD TYPE 4: SAME EMPLOYEE CREATED AND APPROVED PO (15 cases)
# ============================================================

for case in range(15):
    po_id = f"PO{next_po_num:04d}"
    vendor = random.choice(vendors)
    employee = random.choice(employees)  # SAME employee for both roles

    pos.append({
        "po_id": po_id,
        "vendor_id": vendor["vendor_id"],
        "amount": round(random.uniform(5000, 20000), 2),
        "item_category": vendor["vendor_category"],
        "date": (datetime(2026, 5, 1) + timedelta(days=case)).strftime("%Y-%m-%d"),
        "created_by_employee_id": employee["employee_id"],
        "approved_by_employee_id": employee["employee_id"],  # same person - fraud signal
        "payment_terms": "Net 30"
    })
    next_po_num += 1

print("Planted 15 same-creator-approver fraud cases")

# ============================================================
# FRAUD TYPE 5: NEW VENDOR + HIGH-VALUE PO SOON AFTER ONBOARDING (15 cases)
# ============================================================

for case in range(15):
    po_id = f"PO{next_po_num:04d}"
    employee = random.choice(employees)
    onboarding = datetime(2026, 6, 1) + timedelta(days=case)
    vendor_id = f"VEN{next_vendor_num:03d}"

    # create a brand-new vendor
    vendors.append({
        "vendor_id": vendor_id,
        "vendor_name": f"NewCo Traders {case}",
        "email": f"contact@newco{case}.com",
        "phone": "0000000000",
        "address": "Unregistered Address",
        "bank_account": f"GB00NEWCO00000000{case}",
        "registration_number": "PENDING",
        "vendor_category": "IT Hardware",
        "onboarding_date": onboarding.strftime("%Y-%m-%d"),
        "has_contract": "No",
        "created_by_employee_id": employee["employee_id"]
    })
    next_vendor_num += 1

    # immediately a large PO, just 2 days after onboarding
    pos.append({
        "po_id": po_id,
        "vendor_id": vendor_id,
        "amount": round(random.uniform(20000, 25000), 2),  # deliberately high
        "item_category": "IT Hardware",
        "date": (onboarding + timedelta(days=2)).strftime("%Y-%m-%d"),
        "created_by_employee_id": employee["employee_id"],
        "approved_by_employee_id": random.choice(employees)["employee_id"],
        "payment_terms": "Net 30"
    })
    next_po_num += 1

print("Planted 15 new-vendor-high-value-PO fraud cases")

# ============================================================
# FRAUD TYPE 6: INVOICE AMOUNT DOESN'T MATCH CONTRACT RATE (15 cases)
# ============================================================

contract_vendor_ids = [c["vendor_id"] for c in contracts]
matching_pos = [po for po in pos if po["vendor_id"] in contract_vendor_ids]

if len(matching_pos) >= 15:
    selected = random.sample(matching_pos, 15)
    for po in selected:
        contract = next(c for c in contracts if c["vendor_id"] == po["vendor_id"])
        new_invoice_id = f"INV{next_invoice_num:04d}"
        wrong_amount = float(contract["agreed_rate"]) * random.uniform(1.5, 2.5)  # way above agreed rate

        invoices.append({
            "invoice_id": new_invoice_id,
            "po_id": po["po_id"],
            "amount": round(wrong_amount, 2),
            "item_category": po["item_category"],
            "description": "Contract rate mismatch case",
            "date": po["date"],
            "payment_status": "Pending",
            "submitted_by_employee_id": random.choice(employees)["employee_id"]
        })
        next_invoice_num += 1

print("Planted contract-rate-mismatch fraud cases")

# ============================================================
# FRAUD TYPE 7: VENDOR EMAIL MATCHES EMPLOYEE EMAIL (15 cases)
# ============================================================

for case in range(15):
    vendor_id = f"VEN{next_vendor_num:03d}"
    employee = random.choice(employees)

    vendors.append({
        "vendor_id": vendor_id,
        "vendor_name": f"Independent Supplier {case}",
        "email": employee["email"],  # exact match - the fraud signal
        "phone": f"999000{case:04d}",
        "address": "Freelance Office Space",
        "bank_account": f"GB00INDEP0000000{case}",
        "registration_number": "REG-UNKNOWN",
        "vendor_category": "Office Supplies",
        "onboarding_date": (datetime(2026, 4, 1) + timedelta(days=case)).strftime("%Y-%m-%d"),
        "has_contract": "No",
        "created_by_employee_id": random.choice(employees)["employee_id"]  # different creator, but same email
    })
    next_vendor_num += 1

print("Planted 15 email-match fraud cases")

# ============================================================
# FRAUD TYPE 8: PO CATEGORY DOESN'T MATCH INVOICE CATEGORY (15 cases)
# ============================================================

mismatch_categories = ["IT Hardware", "Office Supplies", "Catering", "Logistics"]
sampled_invoices = random.sample(invoices, 15)

for inv in sampled_invoices:
    wrong_category = random.choice([c for c in mismatch_categories if c != inv["item_category"]])
    inv["item_category"] = wrong_category  # deliberately mismatch it

print("Planted 15 category-mismatch fraud cases")

# ============================================================
# SAVE EVERYTHING
# ============================================================

with open("../../data/vendors.csv", "w", newline="", encoding="utf-8") as f:
    fieldnames = ["vendor_id", "vendor_name", "email", "phone", "address", "bank_account",
                  "registration_number", "vendor_category", "onboarding_date", "has_contract",
                  "created_by_employee_id"]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(vendors)

with open("../../data/purchase_orders.csv", "w", newline="", encoding="utf-8") as f:
    fieldnames = ["po_id", "vendor_id", "amount", "item_category", "date",
                  "created_by_employee_id", "approved_by_employee_id", "payment_terms"]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(pos)

with open("../../data/invoices.csv", "w", newline="", encoding="utf-8") as f:
    fieldnames = ["invoice_id", "po_id", "amount", "item_category", "description",
                  "date", "payment_status", "submitted_by_employee_id"]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(invoices)

print("All fraud cases planted and saved successfully!")