"""
Alert Service — persisted alerts with a task workflow (Phase 2.3) and
batch-expiry detection (Phase 2.2).

Detection runs against live data (low stock / anomalies via DataSyncService,
expiry via inventory_batches) and the results are UPSERTED into the alerts
table keyed by dedupe_key, so an open alert is never duplicated but the same
condition can re-alert after being resolved. All reads and the
acknowledge/assign/resolve mutations operate on the table.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger
from app.services.data_sync import DataSyncService

# Days ahead an active batch's expiry date triggers an alert
EXPIRY_ALERT_WINDOW_DAYS = 7
# Within this many days the expiry alert escalates to critical
EXPIRY_CRITICAL_DAYS = 2

OPEN_STATUSES = ("active", "acknowledged")


# =============================================================================
# Pure helpers (unit-testable)
# =============================================================================

def db_alert_type(candidate: Dict) -> str:
    """Map a generated candidate to the alerts.alert_type enum."""
    t = candidate.get("alert_type")
    if t == "inventory":
        return "stockout" if candidate.get("title", "").startswith("Out of Stock") else "low_stock"
    if t == "sales":
        return "sales_anomaly"
    if t == "expiry":
        return "expiry_risk"
    return "system_health"


def category_for(db_type: str) -> str:
    """Coarse frontend-facing category for an alerts.alert_type value."""
    if db_type in ("low_stock", "stockout", "overstock", "dead_stock"):
        return "inventory"
    if db_type == "expiry_risk":
        return "expiry"
    if db_type in ("sales_anomaly", "returns_anomaly", "forecast_deviation"):
        return "sales"
    return "system"


def make_dedupe_key(db_type: str, store_id: Optional[int], item_id: Optional[int],
                    extra: Optional[str] = None) -> str:
    key = f"{db_type}:{store_id or 'all'}:{item_id or 'all'}"
    return f"{key}:{extra}" if extra else key


def expiry_severity(days_to_expiry: int) -> str:
    return "critical" if days_to_expiry <= EXPIRY_CRITICAL_DAYS else "warning"


# =============================================================================
# Service
# =============================================================================

class AlertService:

    # -------------------------------------------------------------------------
    # Detection & persistence
    # -------------------------------------------------------------------------

    @staticmethod
    async def _expiry_candidates(session: AsyncSession,
                                 accessible_stores: List[int] = None) -> List[Dict]:
        """Active batches expiring within the alert window."""
        store_filter = ""
        params: Dict = {"window": EXPIRY_ALERT_WINDOW_DAYS}
        if accessible_stores:
            store_filter = "AND b.store_id = ANY(:stores)"
            params["stores"] = accessible_stores

        result = await session.execute(text(f"""
            SELECT b.id, b.store_id, st.name AS store_name, b.item_id,
                   i.name AS item_name, b.batch_number, b.quantity,
                   b.expiry_date, (b.expiry_date - CURRENT_DATE) AS days_left
            FROM inventory_batches b
            JOIN stores st ON b.store_id = st.id
            JOIN items i ON b.item_id = i.id
            WHERE b.status = 'active'
              AND b.quantity > 0
              AND b.expiry_date IS NOT NULL
              AND b.expiry_date <= CURRENT_DATE + make_interval(days => :window)
              {store_filter}
            ORDER BY b.expiry_date
        """), params)

        candidates = []
        for row in result.fetchall():
            days_left = int(row.days_left)
            expired = days_left < 0
            candidates.append({
                "alert_type": "expiry",
                "severity": "critical" if expired else expiry_severity(days_left),
                "title": (f"Expired Stock: {row.item_name}" if expired
                          else f"Expiry Risk: {row.item_name}"),
                "message": (
                    f"Batch {row.batch_number} of {row.item_name} at {row.store_name} "
                    + (f"expired {-days_left} day(s) ago" if expired
                       else f"expires in {days_left} day(s)")
                    + f" with {row.quantity} units remaining"
                ),
                "store_id": row.store_id,
                "item_id": row.item_id,
                "dedupe_extra": f"batch{row.id}",
                "actual_value": row.quantity,
                "threshold_value": EXPIRY_ALERT_WINDOW_DAYS,
            })
        return candidates

    @staticmethod
    async def sync_alerts(session: AsyncSession,
                          accessible_stores: List[int] = None) -> int:
        """Detect current conditions and persist any alert not already open.
        Returns the number of newly created alerts (each also published to
        the alerts:stream Redis channel)."""
        candidates = await DataSyncService.generate_alerts_from_sales(
            session, accessible_stores=accessible_stores
        )
        candidates += await AlertService._expiry_candidates(
            session, accessible_stores=accessible_stores
        )

        created = 0
        for c in candidates:
            dtype = db_alert_type(c)
            key = make_dedupe_key(dtype, c.get("store_id"), c.get("item_id"),
                                  c.get("dedupe_extra"))
            result = await session.execute(text("""
                INSERT INTO alerts (alert_type, severity, status, store_id, item_id,
                                    title, message, threshold_value, actual_value,
                                    dedupe_key)
                VALUES (CAST(:alert_type AS alert_type),
                        CAST(:severity AS alert_severity),
                        'active', :store_id, :item_id, :title, :message,
                        :threshold_value, :actual_value, :dedupe_key)
                ON CONFLICT (dedupe_key)
                    WHERE status IN ('active', 'acknowledged') AND dedupe_key IS NOT NULL
                    DO NOTHING
                RETURNING id, title, severity, store_id
            """), {
                "alert_type": dtype,
                "severity": c["severity"],
                "store_id": c.get("store_id"),
                "item_id": c.get("item_id"),
                "title": c["title"],
                "message": c["message"],
                "threshold_value": c.get("threshold_value"),
                "actual_value": c.get("actual_value"),
                "dedupe_key": key,
            })
            row = result.fetchone()
            if row:
                created += 1
                try:
                    from app.services.redis_client import publish_alert
                    await publish_alert({
                        "id": row.id,
                        "title": row.title,
                        "severity": str(row.severity),
                        "store_id": row.store_id,
                        "alert_type": dtype,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as e:
                    logger.warning(f"Failed to publish alert to Redis: {e}")

        await session.commit()
        return created

    # -------------------------------------------------------------------------
    # Reads
    # -------------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row) -> Dict:
        dtype = str(row.alert_type)
        return {
            "id": row.id,
            "title": row.title,
            "message": row.message,
            "alert_type": category_for(dtype),
            "db_type": dtype,
            "severity": str(row.severity),
            "status": str(row.status),
            "store_id": row.store_id,
            "store_name": row.store_name,
            "item_id": row.item_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
            "acknowledged_by": row.acknowledged_by,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            "resolved_by": row.resolved_by,
            "resolution_notes": row.resolution_notes,
            "assigned_to": row.assigned_to,
            "assigned_to_name": row.assigned_to_name,
            "assigned_at": row.assigned_at.isoformat() if row.assigned_at else None,
        }

    _SELECT = """
        SELECT a.id, a.alert_type, a.severity, a.status, a.store_id, a.item_id,
               a.title, a.message, a.created_at,
               a.acknowledged_at, a.acknowledged_by,
               a.resolved_at, a.resolved_by, a.resolution_notes,
               a.assigned_to, a.assigned_at,
               st.name AS store_name,
               (u.first_name || ' ' || u.last_name) AS assigned_to_name
        FROM alerts a
        LEFT JOIN stores st ON a.store_id = st.id
        LEFT JOIN users u ON a.assigned_to = u.id
    """

    @staticmethod
    async def list_alerts(session: AsyncSession,
                          accessible_stores: List[int] = None,
                          status: Optional[str] = None,
                          severity: Optional[str] = None,
                          category: Optional[str] = None,
                          store_id: Optional[int] = None,
                          assigned_to: Optional[int] = None,
                          page: int = 1, limit: int = 20) -> Dict:
        filters = ["1=1"]
        params: Dict = {"limit": limit, "offset": (page - 1) * limit}

        if store_id:
            filters.append("a.store_id = :store_id")
            params["store_id"] = store_id
        elif accessible_stores:
            filters.append("(a.store_id = ANY(:stores) OR a.store_id IS NULL)")
            params["stores"] = accessible_stores
        if status:
            filters.append("a.status = CAST(:status AS alert_status)")
            params["status"] = status
        if severity:
            filters.append("a.severity = CAST(:severity AS alert_severity)")
            params["severity"] = severity
        if assigned_to:
            filters.append("a.assigned_to = :assigned_to")
            params["assigned_to"] = assigned_to

        where = " AND ".join(filters)
        rows = (await session.execute(text(
            AlertService._SELECT + f"""
            WHERE {where}
            ORDER BY (a.status IN ('active', 'acknowledged')) DESC,
                     a.severity DESC, a.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params)).fetchall()

        alerts = [AlertService._row_to_dict(r) for r in rows]
        if category:
            alerts = [a for a in alerts if a["alert_type"] == category]

        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        total = (await session.execute(
            text(f"SELECT COUNT(*) FROM alerts a WHERE {where}"), count_params
        )).scalar() or 0

        return {
            "alerts": alerts,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": max(1, (total + limit - 1) // limit),
        }

    @staticmethod
    async def summary(session: AsyncSession,
                      accessible_stores: List[int] = None) -> Dict:
        store_filter = ""
        params: Dict = {}
        if accessible_stores:
            store_filter = "AND (store_id = ANY(:stores) OR store_id IS NULL)"
            params["stores"] = accessible_stores

        row = (await session.execute(text(f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'active' AND severity = 'critical') AS critical,
                COUNT(*) FILTER (WHERE status = 'active' AND severity = 'warning') AS warnings,
                COUNT(*) FILTER (WHERE status = 'active' AND severity = 'info') AS info,
                COUNT(*) FILTER (WHERE status = 'acknowledged') AS acknowledged,
                COUNT(*) FILTER (WHERE status = 'resolved'
                                 AND resolved_at >= CURRENT_DATE) AS resolved_today
            FROM alerts
            WHERE 1=1 {store_filter}
        """), params)).fetchone()

        return {
            "critical_alerts": row.critical or 0,
            "warning_alerts": row.warnings or 0,
            "info_alerts": row.info or 0,
            "acknowledged": row.acknowledged or 0,
            "resolved_today": row.resolved_today or 0,
            "total_active": (row.critical or 0) + (row.warnings or 0) + (row.info or 0),
        }

    # -------------------------------------------------------------------------
    # Task workflow mutations
    # -------------------------------------------------------------------------

    @staticmethod
    async def _get_alert_store(session: AsyncSession, alert_id: int) -> Optional[Dict]:
        row = (await session.execute(
            text("SELECT id, store_id, status FROM alerts WHERE id = :id"),
            {"id": alert_id}
        )).fetchone()
        return dict(row._mapping) if row else None

    @staticmethod
    def _check_access(alert: Dict, user: Dict) -> bool:
        if user["role"] == "super_admin" or alert["store_id"] is None:
            return True
        accessible = user.get("permissions", {}).get("accessible_stores", [])
        return alert["store_id"] in accessible

    @staticmethod
    async def acknowledge(session: AsyncSession, alert_id: int, user: Dict) -> Optional[Dict]:
        alert = await AlertService._get_alert_store(session, alert_id)
        if not alert:
            return None
        if not AlertService._check_access(alert, user):
            raise PermissionError("Access denied to this alert")

        row = (await session.execute(text("""
            UPDATE alerts
            SET status = 'acknowledged',
                acknowledged_by = :user_id,
                acknowledged_at = :now,
                updated_at = :now
            WHERE id = :id AND status = 'active'
            RETURNING id
        """), {"id": alert_id, "user_id": user["id"],
               "now": datetime.now(timezone.utc)})).fetchone()
        await session.commit()
        return {"alert_id": alert_id, "updated": row is not None}

    @staticmethod
    async def assign(session: AsyncSession, alert_id: int,
                     assignee_id: int, user: Dict) -> Optional[Dict]:
        alert = await AlertService._get_alert_store(session, alert_id)
        if not alert:
            return None
        if not AlertService._check_access(alert, user):
            raise PermissionError("Access denied to this alert")

        assignee = (await session.execute(
            text("SELECT id FROM users WHERE id = :id AND status = 'active'"),
            {"id": assignee_id}
        )).fetchone()
        if not assignee:
            raise ValueError("Assignee not found or inactive")

        row = (await session.execute(text("""
            UPDATE alerts
            SET assigned_to = :assignee_id,
                assigned_by = :user_id,
                assigned_at = :now,
                updated_at = :now
            WHERE id = :id AND status IN ('active', 'acknowledged')
            RETURNING id
        """), {"id": alert_id, "assignee_id": assignee_id,
               "user_id": user["id"], "now": datetime.now(timezone.utc)})).fetchone()
        await session.commit()
        return {"alert_id": alert_id, "updated": row is not None}

    @staticmethod
    async def resolve(session: AsyncSession, alert_id: int, user: Dict,
                      notes: Optional[str] = None) -> Optional[Dict]:
        alert = await AlertService._get_alert_store(session, alert_id)
        if not alert:
            return None
        if not AlertService._check_access(alert, user):
            raise PermissionError("Access denied to this alert")

        row = (await session.execute(text("""
            UPDATE alerts
            SET status = 'resolved',
                resolved_by = :user_id,
                resolved_at = :now,
                resolution_notes = :notes,
                updated_at = :now
            WHERE id = :id AND status IN ('active', 'acknowledged')
            RETURNING id
        """), {"id": alert_id, "user_id": user["id"], "notes": notes,
               "now": datetime.now(timezone.utc)})).fetchone()
        await session.commit()
        return {"alert_id": alert_id, "updated": row is not None}
