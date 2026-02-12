"""
Employee Performance Streaming Service
Generates real-time employee performance metrics and syncs with Redis
"""
import asyncio
import random
from datetime import datetime, date, timedelta
from decimal import Decimal
import json
from typing import Optional

from sqlalchemy import select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import async_session
from app.services.redis_client import get_redis
from app.models.employee import Employee, EmployeePerformance, EmployeeTransaction
from app.config import get_settings, logger

settings = get_settings()


class EmployeePerformanceStreamer:
    """
    Real-time employee performance streaming service.
    Updates metrics as new transactions come in and publishes to Redis.
    """
    
    REDIS_CHANNEL = "employee_performance"
    CACHE_TTL = 300  # 5 minutes cache
    
    def __init__(self):
        self.is_running = False
        self.update_interval = 30  # Update every 30 seconds
    
    async def start(self):
        """Start the performance streaming service"""
        self.is_running = True
        logger.info("Employee Performance Streamer started")
        
        while self.is_running:
            try:
                await self._update_live_metrics()
                await asyncio.sleep(self.update_interval)
            except Exception as e:
                logger.error(f"Error in performance streamer: {e}")
                await asyncio.sleep(5)
    
    async def stop(self):
        """Stop the streaming service"""
        self.is_running = False
        logger.info("Employee Performance Streamer stopped")
    
    async def _update_live_metrics(self):
        """Update live performance metrics for all active employees"""
        try:
            async with async_session() as session:
                # Get active employees with sales roles
                query = select(Employee).where(
                    and_(
                        Employee.status == "active",
                        Employee.role.in_(["sales_executive", "customer_service", "store_manager", "inventory_manager", "cashier"])
                    )
                )
                result = await session.execute(query)
                employees = result.scalars().all()
                
                today = date.today()
                live_metrics = []
                
                for emp in employees:
                    # Calculate today's metrics
                    txn_query = select(
                        func.count(EmployeeTransaction.id).label("transactions"),
                        func.sum(EmployeeTransaction.net_amount).label("sales"),
                        func.avg(EmployeeTransaction.net_amount).label("avg_value")
                    ).where(
                        and_(
                            EmployeeTransaction.employee_id == emp.id,
                            EmployeeTransaction.transaction_date == today,
                            EmployeeTransaction.is_voided == False
                        )
                    )
                    txn_result = await session.execute(txn_query)
                    txn_stats = txn_result.one()
                    
                    # Get returns count
                    returns_query = select(func.count(EmployeeTransaction.id)).where(
                        and_(
                            EmployeeTransaction.employee_id == emp.id,
                            EmployeeTransaction.transaction_date == today,
                            EmployeeTransaction.transaction_type == "return"
                        )
                    )
                    returns_count = await session.scalar(returns_query)
                    
                    # Calculate live performance score
                    transactions = txn_stats.transactions or 0
                    sales = float(txn_stats.sales or 0)
                    avg_value = float(txn_stats.avg_value or 0)
                    
                    # Simulate customer rating for today (weighted average)
                    base_rating = 4.0 + random.uniform(-0.5, 0.8)
                    
                    metric = {
                        "employee_id": emp.id,
                        "employee_code": emp.employee_code,
                        "full_name": f"{emp.first_name} {emp.last_name}",
                        "role": emp.role,
                        "store_id": emp.store_id,
                        "today": {
                            "transactions": transactions,
                            "sales": round(sales, 2),
                            "avg_transaction": round(avg_value, 2),
                            "returns": returns_count or 0,
                            "customer_rating": round(min(5.0, base_rating), 2)
                        },
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    live_metrics.append(metric)
                
                # Publish to Redis
                await self._publish_metrics(live_metrics)
                
                # Cache aggregated metrics
                await self._cache_aggregated_metrics(live_metrics)
                
        except Exception as e:
            logger.error(f"Error updating live metrics: {e}")
    
    async def _publish_metrics(self, metrics: list):
        """Publish metrics to Redis pub/sub"""
        try:
            redis = await get_redis()
            
            message = {
                "type": "employee_performance_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": metrics
            }
            
            await redis.publish(self.REDIS_CHANNEL, json.dumps(message))
            
        except Exception as e:
            logger.error(f"Error publishing to Redis: {e}")
    
    async def _cache_aggregated_metrics(self, metrics: list):
        """Cache aggregated performance metrics"""
        try:
            redis = await get_redis()
            
            # Aggregate by role
            role_aggregates = {}
            for m in metrics:
                role = m["role"]
                if role not in role_aggregates:
                    role_aggregates[role] = {
                        "count": 0,
                        "total_sales": 0,
                        "total_transactions": 0,
                        "total_rating": 0
                    }
                role_aggregates[role]["count"] += 1
                role_aggregates[role]["total_sales"] += m["today"]["sales"]
                role_aggregates[role]["total_transactions"] += m["today"]["transactions"]
                role_aggregates[role]["total_rating"] += m["today"]["customer_rating"]
            
            # Calculate averages
            for role, data in role_aggregates.items():
                if data["count"] > 0:
                    data["avg_sales"] = round(data["total_sales"] / data["count"], 2)
                    data["avg_transactions"] = round(data["total_transactions"] / data["count"], 2)
                    data["avg_rating"] = round(data["total_rating"] / data["count"], 2)
            
            # Cache
            await redis.setex(
                "employee:live:by_role",
                self.CACHE_TTL,
                json.dumps(role_aggregates)
            )
            
            # Aggregate by store
            store_aggregates = {}
            for m in metrics:
                store_id = m["store_id"]
                if store_id:
                    if store_id not in store_aggregates:
                        store_aggregates[store_id] = {
                            "count": 0,
                            "total_sales": 0,
                            "total_transactions": 0
                        }
                    store_aggregates[store_id]["count"] += 1
                    store_aggregates[store_id]["total_sales"] += m["today"]["sales"]
                    store_aggregates[store_id]["total_transactions"] += m["today"]["transactions"]
            
            await redis.setex(
                "employee:live:by_store",
                self.CACHE_TTL,
                json.dumps(store_aggregates)
            )
            
            # Top performers today
            sorted_by_sales = sorted(metrics, key=lambda x: x["today"]["sales"], reverse=True)[:10]
            await redis.setex(
                "employee:live:top_performers",
                self.CACHE_TTL,
                json.dumps(sorted_by_sales)
            )
            
        except Exception as e:
            logger.error(f"Error caching aggregated metrics: {e}")


async def get_live_employee_metrics() -> dict:
    """Get cached live employee metrics"""
    try:
        redis = await get_redis()
        
        by_role = await redis.get("employee:live:by_role")
        by_store = await redis.get("employee:live:by_store")
        top_performers = await redis.get("employee:live:top_performers")
        
        return {
            "by_role": json.loads(by_role) if by_role else {},
            "by_store": json.loads(by_store) if by_store else {},
            "top_performers": json.loads(top_performers) if top_performers else [],
            "cached_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting live metrics: {e}")
        return {}


async def simulate_employee_transaction(employee_id: int, store_id: int) -> Optional[dict]:
    """
    Simulate a new transaction for an employee.
    Called by the data generator to attribute transactions.
    """
    try:
        import uuid
        from datetime import time as dt_time
        
        now = datetime.now()
        
        # Transaction details
        txn_type = random.choices(
            ["sale", "return", "void"],
            weights=[0.90, 0.08, 0.02]
        )[0]
        
        if txn_type == "sale":
            gross_amount = random.uniform(20, 500)
            discount = gross_amount * random.uniform(0, 0.15)
        elif txn_type == "return":
            gross_amount = random.uniform(20, 200)
            discount = 0
        else:
            gross_amount = 0
            discount = 0
        
        net_amount = gross_amount - discount
        
        transaction = EmployeeTransaction(
            transaction_code=f"TXN-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}",
            employee_id=employee_id,
            transaction_type=txn_type,
            transaction_date=now.date(),
            transaction_time=now.time(),
            gross_amount=Decimal(str(round(abs(gross_amount), 2))),
            discount_amount=Decimal(str(round(discount, 2))),
            net_amount=Decimal(str(round(net_amount, 2))),
            items_count=random.randint(1, 15),
            store_id=store_id,
            register_id=f"REG-{random.randint(1, 10):02d}",
            payment_method=random.choice(["cash", "card", "mobile"]),
            is_completed=txn_type != "void",
            is_voided=txn_type == "void"
        )
        
        async with async_session() as session:
            session.add(transaction)
            await session.commit()
            
            return transaction.to_dict()
            
    except Exception as e:
        logger.error(f"Error simulating transaction: {e}")
        return None


# Singleton instance
_streamer_instance: Optional[EmployeePerformanceStreamer] = None


def get_performance_streamer() -> EmployeePerformanceStreamer:
    """Get or create the performance streamer instance"""
    global _streamer_instance
    if _streamer_instance is None:
        _streamer_instance = EmployeePerformanceStreamer()
    return _streamer_instance
