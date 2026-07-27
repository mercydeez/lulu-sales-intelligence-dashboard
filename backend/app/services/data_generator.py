import asyncio
import random
from datetime import datetime, timedelta
import numpy as np
from sqlalchemy import select, func
from app.services.database import async_session
from app.services.redis_client import publish_sale
import uuid
from app.models.sales import Sale, SalesStreamRaw, STREAM_ID_OFFSET
from app.config import get_settings

settings = get_settings()


class DemoScopeError(RuntimeError):
    """The generator cannot prove its writes are confined to the demo tenant."""


class DataGenerator:
    """
    Generates realistic streaming sales data with volatility, returns, and market fluctuations.
    Simulates real-world retail scenarios including:
    - Product returns (negative sales)
    - Market volatility and demand shocks
    - Seasonal patterns and time-of-day effects
    - Random promotional bursts and slow periods

    Tenant confinement (E0-8). Every row this class writes is stamped with
    `tenant_id = settings.demo_tenant_id` and `is_synthetic = True`, and the
    store/item ids it draws from are loaded from that tenant only — never a
    hardcoded 1..10 range that could collide with a real tenant's stores.
    Three independent layers must all agree before a fake sale exists:

      1. config: `validate_security()` refuses LIVE_GENERATOR_ENABLED outside DEMO_MODE
      2. this class: `start()` refuses to run, and refuses an empty demo scope
      3. postgres: migration 057's trigger rejects a synthetic row on any other tenant

    Layer 3 is the one that actually holds — 1 and 2 are process-level and a
    future writer could bypass them.
    """

    # Transaction type weights - Realistic retail return rates (10-15%)
    TRANSACTION_TYPES = {
        'regular_sale': 0.65,       # Normal sales (majority of transactions)
        'promotional_sale': 0.10,   # Higher volume promotional sales
        'return': 0.12,             # Customer returns (negative) - realistic 10-15% rate
        'bulk_purchase': 0.08,      # Large orders
        'slow_period': 0.05         # Very low sales during slow times
    }
    
    # Return reasons for realism
    RETURN_REASONS = [
        'defective', 'wrong_item', 'changed_mind', 
        'expired', 'quality_issue', 'duplicate_purchase'
    ]
    
    def __init__(self, tenant_id: int | None = None):
        self.historical_stats = {}
        self.is_running = False
        self.market_sentiment = 1.0  # Fluctuates between 0.5 and 1.5
        self.last_sentiment_update = datetime.now()
        self.consecutive_returns = 0
        self.volatility_factor = 1.0
        # The only tenant this generator may ever write to.
        self.tenant_id = settings.demo_tenant_id if tenant_id is None else tenant_id
        # Populated by _load_tenant_scope(); empty until then, which start() treats
        # as fatal rather than falling back to a guessed id range.
        self.store_ids: list[int] = []
        self.item_ids: list[int] = []

    async def _load_tenant_scope(self):
        """Load the demo tenant's store/item ids — the only ids we may write.

        Replaces the old `random.randint(1, 10)` / `randint(1, 50)`, which assumed
        the demo tenant owns stores 1-10 and items 1-50. That held for the seeded
        volume and nothing else: the moment a real tenant is provisioned, those id
        ranges stop meaning what the generator thought they meant.
        """
        from app.models.sales import Store, Item

        async with async_session() as session:
            stores = await session.execute(
                select(Store.id).where(Store.tenant_id == self.tenant_id).order_by(Store.id)
            )
            items = await session.execute(
                select(Item.id).where(Item.tenant_id == self.tenant_id).order_by(Item.id)
            )
            self.store_ids = [r[0] for r in stores.fetchall()]
            self.item_ids = [r[0] for r in items.fetchall()]

        if not self.store_ids or not self.item_ids:
            raise DemoScopeError(
                f"demo tenant {self.tenant_id} owns "
                f"{len(self.store_ids)} stores / {len(self.item_ids)} items — "
                "refusing to generate synthetic sales with nothing safe to write to."
            )

    async def _load_historical_stats(self):
        """Load statistical properties from the demo tenant's historical data"""
        async with async_session() as session:
            # Get historical sales statistics
            result = await session.execute(
                select(
                    Sale.store_id,
                    Sale.item_id,
                    func.avg(Sale.sales).label('mean_sales'),
                    func.stddev(Sale.sales).label('std_sales'),
                    func.min(Sale.sales).label('min_sales'),
                    func.max(Sale.sales).label('max_sales')
                )
                .where(Sale.is_streaming == False)
                .where(Sale.tenant_id == self.tenant_id)
                .group_by(Sale.store_id, Sale.item_id)
            )

            for row in result.fetchall():
                key = (row.store_id, row.item_id)
                self.historical_stats[key] = {
                    'mean': float(row.mean_sales) if row.mean_sales else 15,
                    'std': float(row.std_sales) if row.std_sales else 5,
                    'min': int(row.min_sales) if row.min_sales else 0,
                    'max': int(row.max_sales) if row.max_sales else 100
                }

    def _update_market_conditions(self):
        """Update market sentiment and volatility - simulates real-world fluctuations"""
        now = datetime.now()
        
        # Update market sentiment every 30-90 seconds
        if (now - self.last_sentiment_update).seconds > random.randint(30, 90):
            # Random walk for market sentiment
            sentiment_change = np.random.normal(0, 0.15)
            self.market_sentiment = max(0.4, min(1.6, self.market_sentiment + sentiment_change))
            
            # Occasionally trigger market shocks (sudden changes)
            if random.random() < 0.1:  # 10% chance of shock
                shock = random.choice([-0.3, -0.2, 0.2, 0.3, 0.4])
                self.market_sentiment = max(0.3, min(1.8, self.market_sentiment + shock))
                print(f"📊 Market shock! Sentiment changed to {self.market_sentiment:.2f}")
            
            # Update volatility factor
            self.volatility_factor = 0.8 + random.random() * 0.8  # 0.8 to 1.6
            self.last_sentiment_update = now
    
    def _get_transaction_type(self) -> str:
        """Determine transaction type with weighted random selection"""
        rand = random.random()
        
        # Realistic occasional forced return (simulates real-world patterns)
        if random.random() < 0.08:  # ~8% additional chance for return (total ~10-15%)
            return 'return'
        
        cumulative = 0
        
        # Adjust weights based on market conditions
        adjusted_weights = self.TRANSACTION_TYPES.copy()
        
        # Slightly higher returns during bad market sentiment (realistic)
        if self.market_sentiment < 0.8:
            adjusted_weights['return'] = 0.18  # Up to 18% in bad times
            adjusted_weights['regular_sale'] = 0.55
            adjusted_weights['slow_period'] = 0.12
        
        # Good sentiment - slightly fewer returns
        elif self.market_sentiment > 1.3:
            adjusted_weights['bulk_purchase'] = 0.12
            adjusted_weights['promotional_sale'] = 0.15
            adjusted_weights['return'] = 0.08  # Lower returns in good times
        
        for trans_type, weight in adjusted_weights.items():
            cumulative += weight
            if rand <= cumulative:
                return trans_type
        
        return 'regular_sale'
    
    def _get_time_of_day_factor(self) -> float:
        """Get sales multiplier based on time of day"""
        hour = datetime.now().hour
        
        # Retail patterns: slower early morning, peak at lunch/evening
        if 6 <= hour < 9:
            return 0.5 + random.random() * 0.2  # Morning slow start
        elif 9 <= hour < 12:
            return 0.8 + random.random() * 0.3  # Building up
        elif 12 <= hour < 14:
            return 1.1 + random.random() * 0.3  # Lunch rush
        elif 14 <= hour < 17:
            return 0.9 + random.random() * 0.2  # Afternoon lull
        elif 17 <= hour < 21:
            return 1.2 + random.random() * 0.4  # Evening peak
        elif 21 <= hour < 23:
            return 0.7 + random.random() * 0.2  # Late evening decline
        else:
            return 0.3 + random.random() * 0.2  # Night (minimal)
    
    def _generate_sale_value(self, store_id: int, item_id: int, transaction_type: str) -> int:
        """Generate a realistic sale value with volatility and returns"""
        key = (store_id, item_id)
        stats = self.historical_stats.get(key, {'mean': 15, 'std': 5, 'min': 0, 'max': 100})
        
        # Base factors
        day_of_week = datetime.now().weekday()
        weekend_factor = 1.2 if day_of_week >= 5 else 1.0  # Higher on weekends
        seasonality_factor = 1.0 + 0.15 * np.sin(2 * np.pi * day_of_week / 7)
        time_factor = self._get_time_of_day_factor()
        
        # Calculate base value with increased volatility
        adjusted_std = stats['std'] * self.volatility_factor * 1.5  # Increased variance
        base_value = np.random.normal(
            stats['mean'] * seasonality_factor * weekend_factor * time_factor * self.market_sentiment,
            adjusted_std
        )
        
        # Apply transaction type modifiers
        if transaction_type == 'return':
            # Returns are NEGATIVE - customer returning items
            return_magnitude = abs(np.random.normal(stats['mean'] * 0.6, stats['std'] * 0.5))
            value = -int(max(1, min(return_magnitude, stats['max'] * 0.8)))
            self.consecutive_returns += 1
            return value
        
        elif transaction_type == 'promotional_sale':
            # Higher than normal - promotional pricing drives volume
            promo_boost = 1.5 + random.random() * 1.0  # 1.5x to 2.5x
            value = base_value * promo_boost
        
        elif transaction_type == 'bulk_purchase':
            # Much higher - business or wholesale purchase
            bulk_multiplier = 3.0 + random.random() * 4.0  # 3x to 7x
            value = base_value * bulk_multiplier
        
        elif transaction_type == 'slow_period':
            # Very low sales during slow times
            value = base_value * (0.1 + random.random() * 0.3)  # 10% to 40%
        
        else:  # regular_sale
            # Add random noise for natural variation
            noise = np.random.normal(0, stats['std'] * 0.3)
            value = base_value + noise
        
        # Reset consecutive returns counter on successful sale
        if transaction_type != 'return':
            self.consecutive_returns = 0
        
        # Ensure bounds (but allow small negatives for returns already handled)
        if transaction_type != 'return':
            value = max(1, min(stats['max'] * 2, int(value)))  # Allow up to 2x max for bulk
        
        return int(value)
    
    def _pick_store_item(self) -> tuple[int, int]:
        """Draw a (store_id, item_id) from the demo tenant's own ids."""
        if not self.store_ids or not self.item_ids:
            raise DemoScopeError("tenant scope not loaded — call _load_tenant_scope() first")
        return random.choice(self.store_ids), random.choice(self.item_ids)

    def _new_stream_row(self, store_id: int, item_id: int, sales_value: int) -> SalesStreamRaw:
        """Build the row. tenant_id and is_synthetic are not optional here — the
        DB trigger from migration 057 rejects the insert if they disagree."""
        if store_id not in self.store_ids or item_id not in self.item_ids:
            raise DemoScopeError(
                f"refusing to write store={store_id} item={item_id}: outside demo tenant "
                f"{self.tenant_id}'s scope"
            )
        return SalesStreamRaw(
            event_id=uuid.uuid4(),
            store_id=store_id,
            item_id=item_id,
            sales=sales_value,
            tenant_id=self.tenant_id,
            is_synthetic=True,
        )

    async def _generate_and_store_sale(self):
        """Generate a new sale with realistic volatility and store it"""
        from app.models.sales import Store, Item

        # Update market conditions
        self._update_market_conditions()

        # Determine transaction type
        transaction_type = self._get_transaction_type()

        # Limit consecutive returns for realistic patterns
        if self.consecutive_returns >= 3 and transaction_type == 'return':
            transaction_type = 'regular_sale'  # Realistic: rarely more than 3 returns in a row

        async with async_session() as session:
            store_id, item_id = self._pick_store_item()

            # Certain items have higher return rates (electronics, perishables) - realistic 20-25%
            high_return_items = [1, 5, 12, 25, 38, 50]  # Problem items (electronics, perishables)
            if item_id in high_return_items and random.random() < 0.20:  # 20% return rate for problem items
                transaction_type = 'return'

            # Fetch store and item names
            store_result = await session.execute(
                select(Store).where(Store.id == store_id)
            )
            store = store_result.scalar_one_or_none()

            item_result = await session.execute(
                select(Item).where(Item.id == item_id)
            )
            item = item_result.scalar_one_or_none()

            # Generate sale value with volatility
            sales_value = self._generate_sale_value(store_id, item_id, transaction_type)

            sale = self._new_stream_row(store_id, item_id, sales_value)

            session.add(sale)
            await session.commit()
            await session.refresh(sale)
            
            # Determine transaction label for display
            if sales_value < 0:
                transaction_label = '🔄 RETURN'
                return_reason = random.choice(self.RETURN_REASONS)
            elif transaction_type == 'promotional_sale':
                transaction_label = '🏷️ PROMO'
                return_reason = None
            elif transaction_type == 'bulk_purchase':
                transaction_label = '📦 BULK'
                return_reason = None
            elif transaction_type == 'slow_period':
                transaction_label = '🕐 SLOW'
                return_reason = None
            else:
                transaction_label = '💰 SALE'
                return_reason = None
            
            # Publish to Redis with enriched data
            sale_data = {
                'id': sale.id + STREAM_ID_OFFSET,  # match sales_fact_view id space
                'date': sale.timestamp.date().isoformat(),
                'store_id': sale.store_id,
                'store_name': store.name if store else f'Store {store_id}',
                'item_id': sale.item_id,
                'item_name': item.name if item else f'Item {item_id}',
                'category': item.category if item else 'General',
                'sales': sale.sales,
                'is_streaming': True,
                'tenant_id': self.tenant_id,
                'is_synthetic': True,
                'created_at': sale.created_at.isoformat(),
                'timestamp': sale.created_at.isoformat(),
                'transaction_type': transaction_type,
                'transaction_label': transaction_label,
                'return_reason': return_reason,
                'market_sentiment': round(self.market_sentiment, 2),
                'is_return': sales_value < 0
            }
            await publish_sale(sale_data)
            
            return sale_data
    
    async def start(self):
        """Start the data generation loop with variable intervals.

        Refuses to run outside demo mode. `main.py` already gates the call site;
        this repeats the check so a future caller cannot skip it by accident.
        """
        if not (settings.demo_mode and settings.live_generator_enabled):
            raise DemoScopeError(
                "synthetic sale generator requires DEMO_MODE and LIVE_GENERATOR_ENABLED"
            )

        await self._load_tenant_scope()
        await self._load_historical_stats()
        print(
            f"🎲 Synthetic generator confined to tenant {self.tenant_id}: "
            f"{len(self.store_ids)} stores, {len(self.item_ids)} items"
        )

        self.is_running = True
        while self.is_running:
            try:
                sale_data = await self._generate_and_store_sale()
                
                # Color-coded logging
                if sale_data.get('is_return'):
                    print(f"🔄 RETURN: {sale_data['item_name']} at {sale_data['store_name']}: {sale_data['sales']} units (Reason: {sale_data.get('return_reason', 'N/A')})")
                elif sale_data.get('transaction_type') == 'bulk_purchase':
                    print(f"📦 BULK: {sale_data['item_name']} at {sale_data['store_name']}: {sale_data['sales']} units")
                elif sale_data.get('transaction_type') == 'promotional_sale':
                    print(f"🏷️ PROMO: {sale_data['item_name']} at {sale_data['store_name']}: {sale_data['sales']} units")
                else:
                    print(f"💰 SALE: {sale_data['item_name']} at {sale_data['store_name']}: {sale_data['sales']} units")
                
            except Exception as e:
                print(f"Error generating sale: {e}")
            
            # Variable interval for more realistic patterns (5-15 seconds)
            base_interval = settings.streaming_interval_seconds
            variation = random.uniform(-0.3, 0.5) * base_interval
            await asyncio.sleep(max(3, base_interval + variation))
    
    def stop(self):
        """Stop the data generation loop"""
        self.is_running = False
