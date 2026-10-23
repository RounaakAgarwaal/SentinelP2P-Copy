import argparse
import csv
import json
import random
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[2]

REF_DATE = date(2026, 9, 30)          # "today" inside the synthetic world
APPROVAL_LIMIT = 15000                # POs above this need senior approval (split-PO rule)
RATE_TOLERANCE = 1.3                  # invoice > rate * 1.3  => rate mismatch rule
NEW_VENDOR_DAYS = 7                   # new-vendor rule window

CATEGORIES = ["IT Hardware", "Office Supplies", "Catering", "Logistics",
              "Software Licensing", "Cleaning Services", "Printing & Packaging"]

# canonical description first (the RAG / contract wording is built around it)
DESCRIPTIONS = {
    "IT Hardware": ["IT hardware procurement", "Laptop and peripheral purchase", "Networking equipment supply"],
    "Office Supplies": ["Office stationery supply", "Office consumables restock", "Desk and filing supplies"],
    "Catering": ["Catering services", "Event catering and refreshments", "Staff meal service"],
    "Logistics": ["Logistics and courier services", "Freight and delivery charges", "Warehouse transport service"],
    "Software Licensing": ["Software license renewal", "Annual software subscription", "Licence seat extension"],
    "Cleaning Services": ["Cleaning services", "Monthly housekeeping service", "Facility sanitation service"],
    "Printing & Packaging": ["Printing and packaging materials", "Brochure printing and packing", "Packaging stock supply"],
}

CLAUSE_TEMPLATES = {
    "IT Hardware": "The vendor shall supply IT hardware equipment at an agreed rate of ₹{rate} per unit/order, with delivery within 15 business days of order confirmation.",
    "Office Supplies": "The vendor shall provide office supplies at an agreed rate of ₹{rate} per order, payable within the agreed payment terms.",
    "Catering": "The vendor shall provide catering services at an agreed rate of ₹{rate} per event, inclusive of setup and service charges.",
    "Logistics": "The vendor shall provide logistics and courier services at an agreed rate of ₹{rate} per shipment.",
    "Software Licensing": "The vendor shall provide software licenses at an agreed rate of ₹{rate} per license renewal cycle.",
    "Cleaning Services": "The vendor shall provide cleaning services at an agreed rate of ₹{rate} per month.",
    "Printing & Packaging": "The vendor shall provide printing and packaging materials at an agreed rate of ₹{rate} per order.",
}

PAYMENT_TERMS = ["Net 15", "Net 30", "Net 45", "Net 60"]

DEPARTMENTS = [("Procurement", 30), ("Finance", 25), ("Operations", 20), ("IT", 15), ("Sales", 10)]
ROLES = {
    "Procurement": (["Procurement Officer", "Procurement Intern"], "Procurement Manager"),
    "Finance": (["Finance Executive", "Accountant"], "Finance Manager"),
    "Operations": (["Operations Executive"], "Operations Manager"),
    "IT": (["IT Support"], "IT Manager"),
    "Sales": (["Sales Executive"], "Sales Manager"),
}

FRAUD_TYPES = ["shell_vendor", "split_po", "duplicate_invoice", "same_creator_approver",
               "new_vendor_high_value", "contract_rate_mismatch", "vendor_employee_email",
               "category_mismatch"]


def iso(d):
    return d.strftime("%Y-%m-%d")


def build(seed, cases, n_employees, n_vendors, n_clean_pos, evasive_share, traps):
    rng = random.Random(seed)
    Faker.seed(seed)
    fake = Faker("en_IN")

    # ------------------------------------------------------------------ employees
    used_names, used_emp_email, used_phones = set(), set(), set()

    def new_phone():
        while True:
            p = f"+91-{rng.randint(6, 9)}{rng.randint(0, 9999):04d}-{rng.randint(0, 99999):05d}"
            if p not in used_phones:
                used_phones.add(p)
                return p

    employees = []
    plan = []
    for dept, n in DEPARTMENTS:
        plan += [dept] * round(n * n_employees / 100)
    while len(plan) < n_employees:
        plan.append("Procurement")
    plan = plan[:n_employees]
    rng.shuffle(plan)
    for i, dept in enumerate(plan, start=1):
        while True:
            name = fake.name()
            if name not in used_names:
                used_names.add(name)
                break
        base = re.sub(r"[^a-z.]", "", name.lower().replace(" ", "."))
        email = f"{base}@sentinelcorp.com"
        k = 2
        while email in used_emp_email:
            email = f"{base}{k}@sentinelcorp.com"
            k += 1
        used_emp_email.add(email)
        normal_roles, manager_role = ROLES[dept]
        role = manager_role if rng.random() < 0.35 else rng.choice(normal_roles)
        employees.append({
            "employee_id": f"EMP{i:03d}", "name": name, "email": email, "phone": new_phone(),
            "department": dept, "role": role,
            "join_date": iso(date(2021, 1, 1) + timedelta(days=rng.randint(0, 1368))),  # <= 2024-09-30
        })
    emp_by_id = {e["employee_id"]: e for e in employees}
    procurement = [e for e in employees if e["department"] == "Procurement"]
    finance = [e for e in employees if e["department"] == "Finance"]
    managers = [e for e in employees if "Manager" in e["role"]]

    # ------------------------------------------------------------------ containers
    vendors, contracts, pos, invoices = {}, {}, {}, {}   # keyed by temp ids
    busy = defaultdict(set)                              # vendor tmp -> PO dates
    used_vendor_names, used_vendor_email = set(), set()
    counters = defaultdict(int)
    case_log = []

    def tmp(kind):
        counters[kind] += 1
        return f"{kind}{counters[kind]}"

    # ------------------------------------------------------------------ helpers
    def add_vendor(onb, category, has_contract, creator, email=None, phone=None):
        while True:
            name = fake.company()
            if name not in used_vendor_names:
                used_vendor_names.add(name)
                break
        if email is None:
            slug = re.sub(r"[^a-z0-9]", "", name.lower())[:18] or "vendor"
            email = f"contact@{slug}.com"
            k = 2
            while email in used_vendor_email:
                email = f"contact@{slug}{k}.com"
                k += 1
        used_vendor_email.add(email)
        v = tmp("V")
        vendors[v] = {
            "vendor_name": name, "email": email, "phone": phone or new_phone(),
            "address": fake.address().replace("\n", ", "),
            "bank_account": "".join(str(rng.randint(0, 9)) for _ in range(12)),
            "registration_number": f"REG-{rng.randint(10**7, 10**8 - 1)}",
            "vendor_category": category, "onboarding_date": onb,
            "has_contract": "Yes" if has_contract else "No",
            "created_by_employee_id": creator["employee_id"], "_rate": None,
        }
        if has_contract:
            start = onb + timedelta(days=rng.randint(0, 30))
            rate = round(rng.uniform(500, 25000), 2)
            c = tmp("C")
            contracts[c] = {
                "vendor": v, "contract_text": CLAUSE_TEMPLATES[category].format(rate=rate),
                "agreed_rate": rate, "start_date": iso(start), "end_date": iso(start + timedelta(days=730)),
            }
            vendors[v]["_rate"] = rate
        return v

    def date_ok(v, d):
        return all((d + timedelta(days=k)) not in busy[v] for k in (-1, 0, 1))

    def pick_date(v, lo=None, hi=None, span=1):
        onb = vendors[v]["onboarding_date"]
        lo = lo or max(onb + timedelta(days=30), date(2025, 1, 1))
        hi = hi or (REF_DATE - timedelta(days=25 + span))
        for _ in range(500):
            d = lo + timedelta(days=rng.randint(0, (hi - lo).days))
            if all(date_ok(v, d + timedelta(days=k)) for k in range(span + 1)):
                return d
        raise RuntimeError("no free date for vendor")

    def add_po(v, d, amount, creator, approver, category=None, terms=None):
        p = tmp("P")
        busy[v].add(d)
        pos[p] = {"vendor": v, "amount": round(amount, 2), "item_category": category or vendors[v]["vendor_category"],
                  "date": d, "created_by_employee_id": creator["employee_id"],
                  "approved_by_employee_id": approver["employee_id"],
                  "payment_terms": terms or rng.choice(PAYMENT_TERMS)}
        return p

    def status_for(inv_date, terms):
        due = inv_date + timedelta(days=int(terms.split()[1]))
        if due < REF_DATE - timedelta(days=30):
            return "Paid" if rng.random() < 0.92 else "Overdue"
        if due < REF_DATE:
            return "Paid" if rng.random() < 0.6 else "Overdue"
        return "Pending" if rng.random() < 0.8 else "Paid"

    def add_invoice(p, amount=None, d=None, category=None, description=None, status=None, submitter=None):
        po = pos[p]
        d = d or (po["date"] + timedelta(days=rng.randint(1, 20)))
        cat = category or po["item_category"]
        i = tmp("I")
        invoices[i] = {
            "po": p, "amount": round(po["amount"] * rng.choice([1.0, 1.0, rng.uniform(0.99, 1.01)]), 2) if amount is None else round(amount, 2),
            "item_category": cat, "description": description or rng.choice(DESCRIPTIONS[cat][:1] * 2 + DESCRIPTIONS[cat]),
            "date": d, "payment_status": status or status_for(d, po["payment_terms"]),
            "submitted_by_employee_id": (submitter or rng.choice(finance))["employee_id"],
        }
        return i

    def pick_approver(creator):
        return rng.choice([m for m in managers if m["employee_id"] != creator["employee_id"]])

    def log_case(ftype, variant, vendors_=(), pos_=(), invs_=(), note=""):
        case_log.append({"case_id": f"CASE{len(case_log) + 1:03d}", "fraud_type": ftype, "variant": variant,
                         "vendors": list(vendors_), "pos": list(pos_), "fraud_invoices": list(invs_), "note": note})

    n_evasive = lambda: round(cases * evasive_share)

    # ------------------------------------------------------------------ clean vendors
    clean_vendors = []
    for _ in range(n_vendors):
        onb = date(2024, 10, 1) + timedelta(days=rng.randint(0, 637))     # up to 2026-06-30
        clean_vendors.append(add_vendor(onb, rng.choice(CATEGORIES), rng.random() < 0.5, rng.choice(procurement)))

    # ------------------------------------------------------------------ clean POs + invoices
    clean_invoices = []
    for _ in range(n_clean_pos):
        v = rng.choice(clean_vendors)
        d = pick_date(v)
        if vendors[v]["_rate"]:
            amount = vendors[v]["_rate"] * rng.uniform(0.95, 1.10)
        else:
            amount = min(25000, max(500, rng.lognormvariate(8.9, 0.7)))
        creator = rng.choice(procurement)
        p = add_po(v, d, amount, creator, pick_approver(creator))
        if rng.random() < 0.93:                       # ~7% of POs not yet invoiced
            clean_invoices.append(add_invoice(p))

    clean_vendor_ids = list(clean_vendors)
    noncontract = [v for v in clean_vendor_ids if not vendors[v]["_rate"]]
    contract_v = [v for v in clean_vendor_ids if vendors[v]["_rate"]]
    pool = list(clean_invoices)
    rng.shuffle(pool)                                  # disjoint picks for in-place frauds
    taken = set()

    def take_invoice(pred=lambda i: True):
        # random pick among still-free invoices (picking "first free" in the shuffled pool
        # would bias later fraud types away from the invoices earlier types already used)
        candidates = [i for i in pool if i not in taken and pred(i)]
        if not candidates:
            raise RuntimeError("not enough clean invoices")
        i = rng.choice(candidates)
        taken.add(i)
        return i

    # ================================================================== FRAUD
    # 1. shell vendor: vendor phone == phone of the employee who created it
    for _ in range(cases):
        insider = rng.choice(procurement + finance)
        cat = rng.choice(CATEGORIES)
        onb = date(2025, 1, 1) + timedelta(days=rng.randint(0, 520))
        v = add_vendor(onb, cat, False, insider, phone=insider["phone"])
        ps, fi = [], []
        for _k in range(2):
            d = pick_date(v)
            p = add_po(v, d, rng.uniform(8000, 14500), insider, pick_approver(insider))
            ps.append(p)
            fi.append(add_invoice(p))
        log_case("shell_vendor", "standard", [v], ps, fi, "vendor phone equals creator's phone")

    # 2. split POs (same vendor, same day, each <= limit, together > limit)
    for k in range(cases):
        evasive = k < n_evasive()
        v = rng.choice(noncontract)
        d = pick_date(v, span=1)
        creator = rng.choice(procurement)
        total = rng.uniform(16000, 24000)
        a = total * rng.uniform(0.45, 0.55)
        ps, fi = [], []
        for part, d_ in zip((a, total - a), (d, d + timedelta(days=1 if evasive else 0))):
            p = add_po(v, d_, part, creator, pick_approver(creator))
            ps.append(p)
            fi.append(add_invoice(p))
        log_case("split_po", "evasive" if evasive else "standard", [v], ps, fi,
                 "two POs 1 day apart" if evasive else "two POs same day, total above limit")
    for _ in range(traps):                              # benign look-alike: same day, small, sum < limit
        v = rng.choice(noncontract)
        d = pick_date(v)
        creator = rng.choice(procurement)
        ps = [add_po(v, d, rng.uniform(2500, 5500), creator, pick_approver(creator)) for _k in range(2)]
        for p in ps:
            add_invoice(p)
        log_case("benign_same_day_pos", "benign", [v], ps, [], "same-day small POs below limit (not fraud)")

    # 3. duplicate invoice (same PO, same amount)
    for k in range(cases):
        evasive = k < n_evasive()
        base = take_invoice()
        b = invoices[base]
        amt = b["amount"] * (rng.uniform(1.006, 1.02) if evasive else 1.0)
        dup = add_invoice(b["po"], amount=amt, d=b["date"] + timedelta(days=rng.randint(2, 12)),
                          category=b["item_category"], description=b["description"], status="Pending")
        log_case("duplicate_invoice", "evasive" if evasive else "standard", [], [b["po"]], [dup],
                 "amount differs slightly" if evasive else "same PO, same amount")

    # 4. same employee raises and approves the PO
    for _ in range(cases):
        v = rng.choice(noncontract)
        d = pick_date(v)
        e = rng.choice(procurement)
        p = add_po(v, d, rng.uniform(6000, 14500), e, e)
        i = add_invoice(p)
        log_case("same_creator_approver", "standard", [], [p], [i], "creator == approver")

    # 5. brand-new vendor + high value PO right after onboarding
    for k in range(cases):
        evasive = k < n_evasive()
        creator = rng.choice(procurement)
        onb = date(2025, 3, 1) + timedelta(days=rng.randint(0, 520))     # <= 2026-08-04
        v = add_vendor(onb, rng.choice(CATEGORIES), False, creator)
        d = onb + timedelta(days=rng.randint(9, 14) if evasive else rng.randint(1, 6))
        p = add_po(v, d, rng.uniform(16000, 24500), creator, pick_approver(creator))
        i = add_invoice(p)
        log_case("new_vendor_high_value", "evasive" if evasive else "standard", [v], [p], [i],
                 "PO on day 9-14 after onboarding" if evasive else "PO within 7 days of onboarding")

    # 6. invoice above contract rate
    for k in range(cases):
        evasive = k < n_evasive()
        i = take_invoice(lambda x: vendors[pos[invoices[x]["po"]]["vendor"]]["_rate"] is not None)
        rate = vendors[pos[invoices[i]["po"]]["vendor"]]["_rate"]
        invoices[i]["amount"] = round(rate * (rng.uniform(1.12, 1.27) if evasive else rng.uniform(1.4, 2.3)), 2)
        log_case("contract_rate_mismatch", "evasive" if evasive else "standard", [], [invoices[i]["po"]], [i],
                 "inflated but under 1.3x" if evasive else "inflated 1.4x-2.3x")

    # 7. vendor email == an employee's email (vendor not created by that employee)
    for _ in range(cases):
        e = rng.choice(employees)
        creator = rng.choice([x for x in procurement if x["employee_id"] != e["employee_id"]])
        onb = date(2025, 1, 1) + timedelta(days=rng.randint(0, 520))
        v = add_vendor(onb, rng.choice(CATEGORIES), False, creator, email=e["email"])
        ps, fi = [], []
        for _k in range(2):
            c2 = rng.choice(procurement)
            p = add_po(v, pick_date(v), rng.uniform(4000, 14000), c2, pick_approver(c2))
            ps.append(p)
            fi.append(add_invoice(p))
        log_case("vendor_employee_email", "standard", [v], ps, fi, "vendor email equals an employee email")

    # 8. invoice category differs from PO category
    for k in range(cases):
        # half of these sit on contract vendors so the contract-RAG check can be tested on them
        i = take_invoice((lambda x: vendors[pos[invoices[x]["po"]]["vendor"]]["_rate"] is not None) if k % 2 == 0 else (lambda x: True))
        wrong = rng.choice([c for c in CATEGORIES if c != invoices[i]["item_category"]])
        invoices[i]["item_category"] = wrong
        invoices[i]["description"] = rng.choice(DESCRIPTIONS[wrong])
        log_case("category_mismatch", "standard", [], [invoices[i]["po"]], [i], "invoice category != PO category")

    # ================================================================== renumber (by date, not by fraud type)
    v_order = sorted(vendors, key=lambda k: (vendors[k]["onboarding_date"], int(k[1:])))
    vmap = {k: f"VEN{n:03d}" for n, k in enumerate(v_order, start=1)}
    p_order = sorted(pos, key=lambda k: (pos[k]["date"], int(k[1:])))
    pmap = {k: f"PO{n:04d}" for n, k in enumerate(p_order, start=1)}
    i_order = sorted(invoices, key=lambda k: (invoices[k]["date"], int(k[1:])))
    imap = {k: f"INV{n:04d}" for n, k in enumerate(i_order, start=1)}

    vendor_rows = [{"vendor_id": vmap[k], **{f: vendors[k][f] for f in (
        "vendor_name", "email", "phone", "address", "bank_account", "registration_number", "vendor_category",
        "onboarding_date", "has_contract", "created_by_employee_id")}} for k in v_order]
    for r in vendor_rows:
        r["onboarding_date"] = iso(r["onboarding_date"])

    c_order = sorted(contracts, key=lambda k: vmap[contracts[k]["vendor"]])
    contract_rows = [{"contract_id": f"CON{n:03d}", "vendor_id": vmap[contracts[k]["vendor"]],
                      "contract_text": contracts[k]["contract_text"], "agreed_rate": contracts[k]["agreed_rate"],
                      "start_date": contracts[k]["start_date"], "end_date": contracts[k]["end_date"]}
                     for n, k in enumerate(c_order, start=1)]

    po_rows = [{"po_id": pmap[k], "vendor_id": vmap[pos[k]["vendor"]], "amount": pos[k]["amount"],
                "item_category": pos[k]["item_category"], "date": iso(pos[k]["date"]),
                "created_by_employee_id": pos[k]["created_by_employee_id"],
                "approved_by_employee_id": pos[k]["approved_by_employee_id"],
                "payment_terms": pos[k]["payment_terms"]} for k in p_order]

    inv_rows = [{"invoice_id": imap[k], "po_id": pmap[invoices[k]["po"]], "amount": invoices[k]["amount"],
                 "item_category": invoices[k]["item_category"], "description": invoices[k]["description"],
                 "date": iso(invoices[k]["date"]), "payment_status": invoices[k]["payment_status"],
                 "submitted_by_employee_id": invoices[k]["submitted_by_employee_id"]} for k in i_order]

    # ---- answer key
    truth = {}
    for c in case_log:
        for i in c["fraud_invoices"]:
            truth[imap[i]] = c
    gt_rows = [{"invoice_id": r["invoice_id"], "is_fraud": int(r["invoice_id"] in truth),
                "fraud_type": truth[r["invoice_id"]]["fraud_type"] if r["invoice_id"] in truth else "",
                "variant": truth[r["invoice_id"]]["variant"] if r["invoice_id"] in truth else "",
                "case_id": truth[r["invoice_id"]]["case_id"] if r["invoice_id"] in truth else ""} for r in inv_rows]
    case_rows = [{"case_id": c["case_id"], "fraud_type": c["fraud_type"], "variant": c["variant"],
                  "vendor_ids": ";".join(vmap[x] for x in c["vendors"]), "po_ids": ";".join(pmap[x] for x in c["pos"]),
                  "fraud_invoice_ids": ";".join(imap[x] for x in c["fraud_invoices"]), "note": c["note"]}
                 for c in case_log]

    return {"employees": employees, "vendors": vendor_rows, "contracts": contract_rows,
            "purchase_orders": po_rows, "invoices": inv_rows, "ground_truth": gt_rows,
            "ground_truth_cases": case_rows}


def validate(t):
    emp = {e["employee_id"] for e in t["employees"]}
    ven = {v["vendor_id"] for v in t["vendors"]}
    po = {p["po_id"] for p in t["purchase_orders"]}
    for name, rows in t.items():
        key = list(rows[0].keys())[0]
        ids = [r[key] for r in rows]
        assert len(ids) == len(set(ids)), f"duplicate ids in {name}"
    assert all(v["created_by_employee_id"] in emp for v in t["vendors"])
    assert all(p["vendor_id"] in ven and p["created_by_employee_id"] in emp and p["approved_by_employee_id"] in emp
               for p in t["purchase_orders"])
    assert all(i["po_id"] in po and i["submitted_by_employee_id"] in emp for i in t["invoices"])
    assert all(c["vendor_id"] in ven for c in t["contracts"])
    assert {v["vendor_id"] for v in t["vendors"] if v["has_contract"] == "Yes"} == {c["vendor_id"] for c in t["contracts"]}


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="SentinelP2P Phase 1 data generator")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(REPO_ROOT / "data"), help="output folder (default: <repo>/data)")
    ap.add_argument("--cases", type=int, default=8, help="planted cases per fraud type")
    ap.add_argument("--employees", type=int, default=100)
    ap.add_argument("--vendors", type=int, default=280, help="legitimate vendors (fraud vendors are added on top)")
    ap.add_argument("--clean_pos", type=int, default=600)
    ap.add_argument("--evasive_share", type=float, default=0.25, help="share of cases built to dodge the plain rules")
    ap.add_argument("--traps", type=int, default=5, help="benign look-alike cases")
    a = ap.parse_args()

    t = build(a.seed, a.cases, a.employees, a.vendors, a.clean_pos, a.evasive_share, a.traps)
    validate(t)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in t.items():
        write_csv(out / f"{name}.csv", rows)

    n_fraud = sum(r["is_fraud"] for r in t["ground_truth"])
    manifest = {"seed": a.seed, "reference_date": iso(REF_DATE), "approval_limit": APPROVAL_LIMIT,
                "rate_tolerance": RATE_TOLERANCE, "cases_per_type": a.cases, "evasive_share": a.evasive_share,
                "benign_traps": a.traps, "fraud_types": FRAUD_TYPES,
                "counts": {k: len(v) for k, v in t.items()}, "fraud_invoices": n_fraud,
                "fraud_rate": round(n_fraud / len(t["invoices"]), 4)}
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest["counts"]), f"| fraud invoices: {n_fraud} ({manifest['fraud_rate']:.1%})")
    print(f"Written to {out}   (ground_truth*.csv is the hidden answer key - never load it into Neo4j or the GNN)")


if __name__ == "__main__":
    main()
