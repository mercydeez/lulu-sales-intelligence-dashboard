"""
CSV import — real-data ingestion for pilots (the demo→pilot unlock).

A retailer uploads a CSV, maps their columns to our canonical model, we validate
every row, then commit. The parse / mapping / validation core here is PURE (no I/O)
so it unit-tests in isolation and runs identically in preview and commit. Persistence
+ name→id resolution live in async helpers at the bottom.

Sacred rule (repo-wide): VOLUME in units, VALUE in AED, never mixed. Sales rows are
UNITS; only *_aed / cost fields are money. The validators enforce the right type per
field so a unit count can never be silently treated as money.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

# Canonical schema per import type. `key` = canonical field; `kind` drives validation.
# kind: text | int | units | aed | date | id-ref(store|item)
SCHEMAS: Dict[str, Dict] = {
    "stores": {
        "target": "stores",
        "fields": {
            "name":     {"required": True,  "kind": "text",  "hint": "Store name (unique)"},
            "location": {"required": False, "kind": "text",  "hint": "Emirate / area"},
        },
    },
    "items": {
        "target": "items",
        "fields": {
            "name":           {"required": True,  "kind": "text", "hint": "Product / SKU name (unique)"},
            "category":       {"required": False, "kind": "text", "hint": "Category"},
            "unit_price_aed": {"required": False, "kind": "aed",  "hint": "Retail price in AED"},
            # E2-3: cost unlocks margin / GMROI. Recorded as an effective-dated
            # period in item_costs (valid from cost_from, or today) — not a scalar.
            "unit_cost_aed":  {"required": False, "kind": "aed",  "hint": "Cost per unit in AED (unlocks margin)"},
            "cost_from":      {"required": False, "kind": "date", "hint": "Date this cost took effect (YYYY-MM-DD)"},
        },
    },
    "sales": {
        "target": "sales_historical",
        "fields": {
            "date":  {"required": True, "kind": "date",  "hint": "YYYY-MM-DD"},
            "store": {"required": True, "kind": "ref_store", "hint": "Store name (must already exist)"},
            "item":  {"required": True, "kind": "ref_item",  "hint": "Product name (must already exist)"},
            "units": {"required": True, "kind": "units", "hint": "Units sold (whole number)"},
        },
    },
    "suppliers": {
        "target": "suppliers",
        "fields": {
            "name":           {"required": True,  "kind": "text", "hint": "Supplier name (unique)"},
            "contact_email":  {"required": False, "kind": "text", "hint": "Contact email"},
            "contact_phone":  {"required": False, "kind": "text", "hint": "Contact phone"},
            "lead_time_days": {"required": False, "kind": "int",  "hint": "Lead time in days"},
        },
    },
    "inventory": {
        "target": "inventory",
        "fields": {
            "store":             {"required": True,  "kind": "ref_store", "hint": "Store name"},
            "item":              {"required": True,  "kind": "ref_item",  "hint": "Product name"},
            "current_stock":     {"required": True,  "kind": "units", "hint": "On-hand units"},
            "unit_cost":         {"required": False, "kind": "aed",   "hint": "Cost per unit in AED"},
            "reorder_point":     {"required": False, "kind": "units", "hint": "Reorder trigger (units)"},
            "average_daily_sales": {"required": False, "kind": "units_f", "hint": "Avg units sold/day"},
            "last_sale_date":    {"required": False, "kind": "date",  "hint": "YYYY-MM-DD of last sale"},
        },
    },
}

MAX_ROWS = 50_000

# UAE-flavoured sample CSVs so a prospect can try the wizard before their own data
# (pilot-in-a-box). Headers deliberately differ from canonical keys to exercise mapping.
SAMPLES: Dict[str, str] = {
    "stores": (
        "Store Name,Emirate\n"
        "Dubai Marina Store,Dubai\n"
        "Deira City Store,Dubai\n"
        "Abu Dhabi Corniche,Abu Dhabi\n"
        "Sharjah Mega Mall,Sharjah\n"
    ),
    "items": (
        "Product,Category,Retail Price (AED)\n"
        "Fresh Milk 1L,Dairy,6.50\n"
        "Arabic Bread,Bakery,3.00\n"
        "Basmati Rice 5kg,Grains,28.00\n"
        "Mineral Water 1.5L,Beverages,2.00\n"
        "Dates Khalas 500g,Produce,22.00\n"
    ),
    "sales": (
        "Date,Store,Product,Units Sold\n"
        "2026-06-28,Dubai Marina Store,Fresh Milk 1L,42\n"
        "2026-06-28,Dubai Marina Store,Arabic Bread,80\n"
        "2026-06-29,Deira City Store,Basmati Rice 5kg,12\n"
        "2026-06-29,Abu Dhabi Corniche,Dates Khalas 500g,18\n"
        "2026-06-30,Sharjah Mega Mall,Mineral Water 1.5L,150\n"
    ),
    "suppliers": (
        "Supplier,Email,Phone,Lead Time (days)\n"
        "Emirates Fresh Supply Co,sales@emiratesfresh.ae,+97142000000,3\n"
        "Gulf Distribution LLC,orders@gulfdist.ae,+97143000000,7\n"
        "Al Madina Wholesale,info@almadina.ae,+97165000000,5\n"
    ),
    "inventory": (
        "Store,Product,On Hand,Unit Cost,Reorder At,Avg Daily Sales,Last Sale\n"
        "Dubai Marina Store,Fresh Milk 1L,120,4.20,50,40,2026-06-29\n"
        "Dubai Marina Store,Arabic Bread,0,1.90,60,75,2026-06-30\n"
        "Deira City Store,Basmati Rice 5kg,240,18.00,40,12,2026-06-29\n"
        "Abu Dhabi Corniche,Dates Khalas 500g,310,14.50,30,4,2026-04-02\n"
        "Sharjah Mega Mall,Mineral Water 1.5L,900,1.10,200,150,2026-06-30\n"
    ),
}


def sample_csv(import_type: str) -> Optional[str]:
    return SAMPLES.get(import_type)


def import_types() -> List[str]:
    return list(SCHEMAS.keys())


def schema_for(import_type: str) -> Optional[Dict]:
    s = SCHEMAS.get(import_type)
    if not s:
        return None
    return {
        "import_type": import_type,
        "target": s["target"],
        "fields": [
            {"key": k, "required": v["required"], "kind": v["kind"], "hint": v["hint"]}
            for k, v in s["fields"].items()
        ],
    }


def parse_csv(text: str, sample: Optional[int] = None) -> Tuple[List[str], List[Dict[str, str]]]:
    """Parse CSV text → (headers, rows-as-dicts). Tolerates a BOM and quoted fields.
    `sample` caps the number of rows returned (for preview)."""
    if text and text[0] == "﻿":
        text = text[1:]
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    headers = [h.strip() for h in rows[0]]
    out: List[Dict[str, str]] = []
    for r in rows[1:]:
        if not any(cell.strip() for cell in r):
            continue  # skip blank lines
        record = {headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))}
        out.append(record)
        if sample and len(out) >= sample:
            break
    return headers, out


def _coerce(kind: str, raw: str) -> Tuple[object, Optional[str]]:
    """Validate + coerce a single value by kind. Returns (value, error)."""
    v = (raw or "").strip()
    if kind == "text":
        return (None, "empty") if v == "" else (v, None)
    if v == "":
        return None, "empty"
    if kind in ("int", "units"):
        try:
            n = int(float(v))  # tolerate "12.0"
        except ValueError:
            return None, f"'{raw}' is not a whole number"
        if n < 0 and kind == "units":
            return None, "units cannot be negative"
        return n, None
    if kind == "units_f":
        try:
            f = float(v)
        except ValueError:
            return None, f"'{raw}' is not a number"
        return (None, "cannot be negative") if f < 0 else (round(f, 2), None)
    if kind == "aed":
        try:
            f = float(v.replace(",", "").replace("AED", "").strip())
        except ValueError:
            return None, f"'{raw}' is not a valid AED amount"
        return (None, "AED amount cannot be negative") if f < 0 else (round(f, 2), None)
    if kind == "date":
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(v, fmt).date().isoformat(), None
            except ValueError:
                continue
        return None, f"'{raw}' is not a recognised date (use YYYY-MM-DD)"
    if kind in ("ref_store", "ref_item"):
        return v, None  # resolved to an id at commit time
    return v, None


def validate_rows(import_type: str, headers: List[str], rows: List[Dict[str, str]],
                  mapping: Dict[str, str]) -> Dict:
    """Validate mapped rows. `mapping` maps canonical field -> source column.
    Returns {valid: [...cleaned dicts...], errors: [{row, field, message}], summary}."""
    schema = SCHEMAS.get(import_type)
    if not schema:
        return {"valid": [], "errors": [{"row": 0, "field": "", "message": "Unknown import type"}],
                "summary": {"total": 0, "valid": 0, "errors": 1}}

    # Every required canonical field must be mapped to a present column.
    missing = [k for k, f in schema["fields"].items()
               if f["required"] and (mapping.get(k) not in headers)]
    if missing:
        return {"valid": [], "errors": [{"row": 0, "field": m, "message": f"Required field '{m}' is not mapped"} for m in missing],
                "summary": {"total": len(rows), "valid": 0, "errors": len(missing)}}

    valid: List[Dict] = []
    errors: List[Dict] = []
    for i, row in enumerate(rows, start=1):
        cleaned: Dict[str, object] = {}
        row_errors: List[Dict] = []
        for field, spec in schema["fields"].items():
            src = mapping.get(field)
            raw = row.get(src, "") if src else ""
            if not src or src not in headers:
                if spec["required"]:
                    row_errors.append({"row": i, "field": field, "message": "not mapped"})
                continue
            val, err = _coerce(spec["kind"], raw)
            if err == "empty":
                if spec["required"]:
                    row_errors.append({"row": i, "field": field, "message": "is required but empty"})
                else:
                    cleaned[field] = None
            elif err:
                row_errors.append({"row": i, "field": field, "message": err})
            else:
                cleaned[field] = val
        if row_errors:
            errors.extend(row_errors)
        else:
            valid.append(cleaned)

    return {
        "valid": valid,
        "errors": errors[:200],  # cap returned errors; summary keeps the true count
        "summary": {"total": len(rows), "valid": len(valid),
                    "errors": len(rows) - len(valid), "error_fields": len(errors)},
    }


# --- persistence (async; tenant-scoped) ------------------------------------
from sqlalchemy import text as _sql  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402


async def _resolve_maps(db: AsyncSession, tenant_id: int) -> Tuple[Dict[str, int], Dict[str, int]]:
    stores = (await db.execute(_sql(
        "SELECT id, lower(name) AS n FROM stores WHERE tenant_id = :t"), {"t": tenant_id})).fetchall()
    items = (await db.execute(_sql(
        "SELECT id, lower(name) AS n FROM items WHERE tenant_id = :t"), {"t": tenant_id})).fetchall()
    return ({r.n: r.id for r in stores}, {r.n: r.id for r in items})


async def commit_import(db: AsyncSession, tenant_id: int, import_type: str,
                        valid_rows: List[Dict]) -> Dict:
    """Persist validated rows into the canonical tables, tenant-scoped. Upserts
    stores/items by name; resolves store/item names → ids for sales/inventory
    (unresolved rows are skipped and reported). Caller commits."""
    imported, skipped, skip_reasons = 0, 0, []

    if import_type == "stores":
        for r in valid_rows:
            await db.execute(_sql("""
                INSERT INTO stores (name, location, tenant_id) VALUES (:name, :loc, :t)
                ON CONFLICT DO NOTHING
            """), {"name": r["name"], "loc": r.get("location"), "t": tenant_id})
            imported += 1

    elif import_type == "items":
        for r in valid_rows:
            item_id = (await db.execute(_sql("""
                INSERT INTO items (name, category, unit_price_aed, tenant_id)
                VALUES (:name, :cat, COALESCE(:price, 10.00), :t)
                RETURNING id
            """), {"name": r["name"], "cat": r.get("category"),
                   "price": r.get("unit_price_aed"), "t": tenant_id})).scalar()

            # E2-3: a supplied cost opens an effective-dated period in item_costs.
            # set_item_cost closes the straddling period first — a plain INSERT would
            # always collide with the open-ended current period. The trigger mirrors
            # the result onto items.unit_cost_aed. No cost => the item simply has
            # none, and every margin metric keeps saying `needs: cost`.
            cost = r.get("unit_cost_aed")
            if item_id and cost is not None:
                await db.execute(_sql("""
                    SELECT set_item_cost(:t, :iid, :cost, COALESCE(:vf, CURRENT_DATE), 'import')
                """), {"t": tenant_id, "iid": item_id, "cost": cost,
                       "vf": r.get("cost_from")})
            imported += 1

    elif import_type == "suppliers":
        for r in valid_rows:
            await db.execute(_sql("""
                INSERT INTO suppliers (name, contact_email, contact_phone, lead_time_days, tenant_id)
                VALUES (:name, :email, :phone, COALESCE(:lead, 7), :t)
            """), {"name": r["name"], "email": r.get("contact_email"),
                   "phone": r.get("contact_phone"), "lead": r.get("lead_time_days"), "t": tenant_id})
            imported += 1

    elif import_type == "sales":
        store_map, item_map = await _resolve_maps(db, tenant_id)
        for r in valid_rows:
            sid = store_map.get(str(r["store"]).lower())
            iid = item_map.get(str(r["item"]).lower())
            if not sid or not iid:
                skipped += 1
                if len(skip_reasons) < 50:
                    skip_reasons.append(f"unresolved {'store' if not sid else 'item'}: "
                                        f"{r['store'] if not sid else r['item']}")
                continue
            await db.execute(_sql("""
                INSERT INTO sales_historical (date, store_id, item_id, sales, tenant_id)
                VALUES (:d, :s, :i, :u, :t)
            """), {"d": r["date"], "s": sid, "i": iid, "u": r["units"], "t": tenant_id})
            imported += 1

    elif import_type == "inventory":
        store_map, item_map = await _resolve_maps(db, tenant_id)
        for r in valid_rows:
            sid = store_map.get(str(r["store"]).lower())
            iid = item_map.get(str(r["item"]).lower())
            if not sid or not iid:
                skipped += 1
                if len(skip_reasons) < 50:
                    skip_reasons.append(f"unresolved {'store' if not sid else 'item'}")
                continue
            await db.execute(_sql("""
                INSERT INTO inventory (store_id, item_id, current_stock, unit_cost,
                    reorder_point, average_daily_sales, last_sale_date)
                VALUES (:s, :i, :cs, COALESCE(:uc, 0), COALESCE(:rp, 50),
                        COALESCE(:ads, 0), :lsd)
                ON CONFLICT (store_id, item_id) DO UPDATE SET
                    current_stock = EXCLUDED.current_stock,
                    unit_cost = EXCLUDED.unit_cost,
                    reorder_point = EXCLUDED.reorder_point,
                    average_daily_sales = EXCLUDED.average_daily_sales,
                    last_sale_date = EXCLUDED.last_sale_date
            """), {"s": sid, "i": iid, "cs": r["current_stock"],
                   "uc": r.get("unit_cost"), "rp": r.get("reorder_point"),
                   "ads": r.get("average_daily_sales"), "lsd": r.get("last_sale_date")})
            imported += 1

    return {"imported": imported, "skipped": skipped, "skip_reasons": skip_reasons[:50]}
