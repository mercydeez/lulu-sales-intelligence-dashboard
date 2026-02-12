"""
Stream API Routes - SSE Streaming and Latest Data
Matches README: GET /stream/sales, GET /api/latest, GET /stream/alerts
"""
from fastapi import APIRouter, Request, Depends, Query
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from typing import List
from pydantic import BaseModel
import asyncio
import json
import random

from app.services.database import get_db
from app.services.redis_client import get_redis, CHANNEL_SALES_STREAM, CHANNEL_ALERTS_STREAM, CHANNEL_INVENTORY_STREAM, publish_alert, publish_inventory_update
from app.models.sales import Sale, Store, Item

router = APIRouter()


class LatestSaleResponse(BaseModel):
    id: int
    event_id: str | None = None
    timestamp: datetime
    store_id: int
    store_name: str | None = None
    item_id: int
    item_name: str | None = None
    sales: int
    is_streaming: bool
    
    class Config:
        from_attributes = True


@router.get("/latest", response_model=List[LatestSaleResponse])
async def get_latest(
    limit: int = Query(20, le=100, description="Number of records to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get latest sales records (both historical and streaming).
    
    Example: GET /api/latest?limit=20
    """
    # Get stores and items for name lookup
    stores_result = await db.execute(select(Store))
    stores = {s.id: s.name for s in stores_result.scalars().all()}
    
    items_result = await db.execute(select(Item))
    items = {i.id: i.name for i in items_result.scalars().all()}
    
    # Get latest records
    query = select(Sale).order_by(Sale.created_at.desc()).limit(limit)
    result = await db.execute(query)
    records = result.scalars().all()
    
    return [
        LatestSaleResponse(
            id=r.id,
            event_id=None,
            timestamp=r.created_at,
            store_id=r.store_id,
            store_name=stores.get(r.store_id),
            item_id=r.item_id,
            item_name=items.get(r.item_id),
            sales=r.sales,
            is_streaming=r.is_streaming
        )
        for r in records
    ]


async def event_generator(request: Request):
    """Generate SSE events from Redis pub/sub"""
    redis = await get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL_SALES_STREAM)
    
    # Send initial connection event
    yield {
        "event": "connected",
        "data": json.dumps({"message": "Connected to sales stream"})
    }
    
    try:
        while True:
            if await request.is_disconnected():
                break
            
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0
            )
            
            if message and message['type'] == 'message':
                data = message['data']
                yield {
                    "event": "sales",
                    "data": data
                }
            
            await asyncio.sleep(0.1)
    finally:
        await pubsub.unsubscribe(CHANNEL_SALES_STREAM)
        await pubsub.close()


@router.get("/sales")
async def stream_sales(request: Request):
    """
    SSE endpoint for real-time sales streaming.
    
    Example: GET /stream/sales
    
    Returns events:
    - event: connected - Initial connection confirmation
    - event: sales - New sale data
    """
    return EventSourceResponse(event_generator(request))


@router.post("/generate-returns")
async def generate_returns(
    count: int = Query(50, ge=10, le=200, description="Number of returns to generate"),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate bulk return records immediately for visibility in charts.
    This creates immediate return data that will show in all return graphs.
    """
    import random
    from datetime import date, timedelta
    from app.services.redis_client import publish_sale
    
    # Get stores and items
    stores_result = await db.execute(select(Store))
    stores = list(stores_result.scalars().all())
    
    items_result = await db.execute(select(Item))
    items = list(items_result.scalars().all())
    
    if not stores or not items:
        return {"error": "No stores or items found", "generated": 0}
    
    generated_returns = []
    today = date.today()
    
    for i in range(count):
        store = random.choice(stores)
        item = random.choice(items)
        
        # Generate return value (negative, between -5 and -50)
        return_value = -random.randint(5, 50)
        
        # Random date in the last 7 days (some today, some recent)
        days_ago = random.choices([0, 0, 0, 1, 1, 2, 3, 4, 5, 6], k=1)[0]  # Weighted toward today
        return_date = today - timedelta(days=days_ago)
        
        sale = Sale(
            date=return_date,
            store_id=store.id,
            item_id=item.id,
            sales=return_value,
            is_streaming=True
        )
        
        db.add(sale)
        await db.flush()  # Get the ID
        
        return_data = {
            'id': sale.id,
            'date': sale.date.isoformat(),
            'store_id': sale.store_id,
            'store_name': store.name,
            'item_id': sale.item_id,
            'item_name': item.name,
            'category': item.category,
            'sales': sale.sales,
            'is_streaming': True,
            'created_at': sale.created_at.isoformat() if sale.created_at else datetime.now().isoformat(),
            'timestamp': datetime.now().isoformat(),
            'transaction_type': 'return',
            'transaction_label': '🔄 RETURN',
            'return_reason': random.choice(['defective', 'wrong_item', 'changed_mind', 'expired', 'quality_issue']),
            'is_return': True
        }
        
        generated_returns.append(return_data)
        
        # Publish to Redis for live updates
        await publish_sale(return_data)
    
    await db.commit()
    
    return {
        "message": f"Generated {count} return records for visibility",
        "generated": count,
        "sample_returns": generated_returns[:5]
    }


# =============================================================================
# ALERTS & INVENTORY STREAMING
# =============================================================================

# Mock inventory data for live alerts
MOCK_ITEMS = [
    {"id": 1, "name": "Fresh Milk 1L", "category": "Dairy"},
    {"id": 2, "name": "Bananas", "category": "Fruits"},
    {"id": 3, "name": "Greek Yogurt", "category": "Dairy"},
    {"id": 4, "name": "Mineral Water 1.5L", "category": "Beverages"},
    {"id": 5, "name": "Whole Wheat Bread", "category": "Bakery"},
    {"id": 6, "name": "Chicken Breast", "category": "Meat"},
    {"id": 7, "name": "Tomatoes", "category": "Vegetables"},
    {"id": 8, "name": "Orange Juice", "category": "Beverages"},
    {"id": 9, "name": "Cheddar Cheese", "category": "Dairy"},
    {"id": 10, "name": "Ice Cream", "category": "Frozen Foods"},
]

MOCK_STORES = [
    {"id": 1, "name": "Al Barsha"},
    {"id": 2, "name": "Deira City Centre"},
    {"id": 3, "name": "Karama"},
    {"id": 4, "name": "Mushrif Mall"},
    {"id": 5, "name": "Al Wahda"},
]

ALERT_TYPES = [
    {"type": "out_of_stock", "severity": "critical", "title": "Out of Stock Alert"},
    {"type": "low_stock", "severity": "warning", "title": "Low Stock Warning"},
    {"type": "overstocked", "severity": "info", "title": "Overstocked Notice"},
    {"type": "reorder", "severity": "warning", "title": "Reorder Required"},
    {"type": "high_sales", "severity": "success", "title": "High Sales Alert"},
    {"type": "price_change", "severity": "info", "title": "Price Update"},
]


def generate_live_alert():
    """Generate a random live alert for demonstration"""
    item = random.choice(MOCK_ITEMS)
    store = random.choice(MOCK_STORES)
    alert_type = random.choice(ALERT_TYPES)
    
    quantity = random.randint(0, 500)
    reorder_level = random.randint(30, 80)
    
    if alert_type["type"] == "out_of_stock":
        message = f"{item['name']} is out of stock at {store['name']}. Immediate reorder required!"
        quantity = 0
    elif alert_type["type"] == "low_stock":
        quantity = random.randint(5, reorder_level - 1)
        message = f"{item['name']} is running low at {store['name']}. Current: {quantity} (Reorder: {reorder_level})"
    elif alert_type["type"] == "overstocked":
        max_stock = random.randint(300, 400)
        quantity = random.randint(max_stock + 50, max_stock + 200)
        message = f"{item['name']} is overstocked at {store['name']}. Current: {quantity} (Max: {max_stock})"
    elif alert_type["type"] == "reorder":
        message = f"{item['name']} needs reordering at {store['name']}. Multiple stores affected."
    elif alert_type["type"] == "high_sales":
        sales_increase = random.randint(20, 80)
        message = f"{item['name']} sales up {sales_increase}% at {store['name']}. Consider increasing stock."
    else:
        price_change = random.choice(["+5%", "-10%", "+15%", "-8%"])
        message = f"{item['name']} price adjusted by {price_change} at {store['name']}"
    
    return {
        "id": int(datetime.now().timestamp() * 1000) + random.randint(1, 1000),
        "title": alert_type["title"],
        "message": message,
        "type": alert_type["type"],
        "severity": alert_type["severity"],
        "category": "inventory" if alert_type["type"] in ["out_of_stock", "low_stock", "overstocked", "reorder"] else "sales",
        "item_id": item["id"],
        "item_name": item["name"],
        "item_category": item["category"],
        "store_id": store["id"],
        "store_name": store["name"],
        "quantity": quantity,
        "timestamp": datetime.now().isoformat(),
        "read": False,
    }


def generate_inventory_update():
    """Generate a random inventory update"""
    item = random.choice(MOCK_ITEMS)
    store = random.choice(MOCK_STORES)
    
    quantity = random.randint(0, 500)
    reorder_level = random.randint(30, 80)
    max_stock = random.randint(300, 400)
    
    if quantity <= 0:
        status = "out_of_stock"
    elif quantity <= reorder_level:
        status = "low_stock"
    elif quantity > max_stock:
        status = "overstocked"
    else:
        status = "in_stock"
    
    return {
        "id": int(datetime.now().timestamp() * 1000) + random.randint(1, 1000),
        "item_id": item["id"],
        "item_name": item["name"],
        "category": item["category"],
        "store_id": store["id"],
        "store_name": store["name"],
        "quantity": quantity,
        "reorder_level": reorder_level,
        "max_stock": max_stock,
        "status": status,
        "unit_cost": round(random.uniform(10, 100), 2),
        "timestamp": datetime.now().isoformat(),
    }


async def alerts_event_generator(request: Request):
    """Generate SSE events for live alerts"""
    redis = await get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL_ALERTS_STREAM)
    
    # Send initial connection event
    yield {
        "event": "connected",
        "data": json.dumps({"message": "Connected to alerts stream"})
    }
    
    # Send initial batch of alerts
    initial_alerts = [generate_live_alert() for _ in range(3)]
    for alert in initial_alerts:
        yield {
            "event": "alert",
            "data": json.dumps(alert)
        }
    
    alert_counter = 0
    
    try:
        while True:
            if await request.is_disconnected():
                break
            
            # Check for published alerts from Redis
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=0.5
            )
            
            if message and message['type'] == 'message':
                yield {
                    "event": "alert",
                    "data": message['data']
                }
            
            # Generate random alerts periodically (every 8-15 seconds)
            alert_counter += 1
            if alert_counter >= random.randint(80, 150):  # ~8-15 seconds at 0.1s sleep
                alert_counter = 0
                new_alert = generate_live_alert()
                
                # Publish to Redis for other subscribers
                await publish_alert(new_alert)
                
                yield {
                    "event": "alert",
                    "data": json.dumps(new_alert)
                }
            
            await asyncio.sleep(0.1)
    finally:
        await pubsub.unsubscribe(CHANNEL_ALERTS_STREAM)
        await pubsub.close()


async def inventory_event_generator(request: Request):
    """Generate SSE events for inventory updates"""
    redis = await get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL_INVENTORY_STREAM)
    
    # Send initial connection event
    yield {
        "event": "connected",
        "data": json.dumps({"message": "Connected to inventory stream"})
    }
    
    update_counter = 0
    
    try:
        while True:
            if await request.is_disconnected():
                break
            
            # Check for published updates from Redis
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=0.5
            )
            
            if message and message['type'] == 'message':
                yield {
                    "event": "inventory_update",
                    "data": message['data']
                }
            
            # Generate random inventory updates periodically (every 5-10 seconds)
            update_counter += 1
            if update_counter >= random.randint(50, 100):
                update_counter = 0
                update = generate_inventory_update()
                
                # Publish to Redis
                await publish_inventory_update(update)
                
                yield {
                    "event": "inventory_update",
                    "data": json.dumps(update)
                }
                
                # If status changed to critical, also generate an alert
                if update["status"] in ["out_of_stock", "low_stock"]:
                    alert = {
                        "id": int(datetime.now().timestamp() * 1000),
                        "title": "Out of Stock Alert" if update["status"] == "out_of_stock" else "Low Stock Warning",
                        "message": f"{update['item_name']} {'is out of stock' if update['status'] == 'out_of_stock' else 'is running low'} at {update['store_name']}",
                        "type": update["status"],
                        "severity": "critical" if update["status"] == "out_of_stock" else "warning",
                        "category": "inventory",
                        "item_id": update["item_id"],
                        "item_name": update["item_name"],
                        "store_id": update["store_id"],
                        "store_name": update["store_name"],
                        "quantity": update["quantity"],
                        "timestamp": datetime.now().isoformat(),
                        "read": False,
                    }
                    await publish_alert(alert)
            
            await asyncio.sleep(0.1)
    finally:
        await pubsub.unsubscribe(CHANNEL_INVENTORY_STREAM)
        await pubsub.close()


@router.get("/alerts")
async def stream_alerts(request: Request):
    """
    SSE endpoint for real-time alerts streaming.
    
    Example: GET /stream/alerts
    
    Returns events:
    - event: connected - Initial connection confirmation
    - event: alert - New alert notification (inventory, sales, system)
    """
    return EventSourceResponse(alerts_event_generator(request))


@router.get("/inventory")
async def stream_inventory(request: Request):
    """
    SSE endpoint for real-time inventory updates streaming.
    
    Example: GET /stream/inventory
    
    Returns events:
    - event: connected - Initial connection confirmation
    - event: inventory_update - Inventory level change
    """
    return EventSourceResponse(inventory_event_generator(request))
