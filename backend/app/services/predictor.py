from datetime import datetime
from typing import List, Dict
from sqlalchemy import select
from app.services.database import async_session
from app.services.redis_client import cache_get, cache_set
from app.models.sales import Sale
from app.config import get_settings

settings = get_settings()


class SalesPredictor:
    """
    Time-series forecasting for sales predictions.
    Uses simple moving average and trend analysis for predictions.
    Can be extended to use Prophet for more accurate forecasting.
    """
    
    MODEL_VERSION = "simple_v1.0"
    CACHE_KEY_PREFIX = "prediction"
    CACHE_TTL = 3600  # 1 hour
    
    async def _get_historical_data(self, store_id: int, item_id: int) -> List[Dict]:
        """Fetch historical sales data for training"""
        async with async_session() as session:
            result = await session.execute(
                select(Sale.date, Sale.sales)
                .where(Sale.store_id == store_id)
                .where(Sale.item_id == item_id)
                .order_by(Sale.date)
            )
            
            data = result.fetchall()
            
            if not data:
                return []
            
            return [{'date': row.date, 'sales': row.sales} for row in data]
    
    def _calculate_predictions(self, data: List[Dict], days: int) -> List[Dict]:
        """Calculate predictions using simple moving average"""
        if len(data) < 7:
            return []
        
        # Calculate 7-day moving average
        recent_sales = [d['sales'] for d in data[-30:]]
        avg_sales = sum(recent_sales) / len(recent_sales)
        
        # Calculate trend
        if len(recent_sales) >= 14:
            first_half = sum(recent_sales[:len(recent_sales)//2]) / (len(recent_sales)//2)
            second_half = sum(recent_sales[len(recent_sales)//2:]) / (len(recent_sales)//2)
            trend = (second_half - first_half) / first_half if first_half > 0 else 0
        else:
            trend = 0
        
        # Calculate standard deviation for confidence intervals
        std_sales = (sum((s - avg_sales) ** 2 for s in recent_sales) / len(recent_sales)) ** 0.5
        
        predictions = []
        last_date = data[-1]['date']
        
        for i in range(1, days + 1):
            from datetime import timedelta
            pred_date = last_date + timedelta(days=i)
            
            # Apply trend
            predicted_sales = avg_sales * (1 + trend * i / 30)
            
            # Add day-of-week seasonality
            import math
            day_of_week = pred_date.weekday()
            seasonality = 1.0 + 0.1 * math.sin(2 * math.pi * day_of_week / 7)
            predicted_sales *= seasonality
            
            predictions.append({
                'prediction_date': pred_date.isoformat(),
                'predicted_sales': max(0, round(predicted_sales, 2)),
                'confidence_lower': max(0, round(predicted_sales - 1.96 * std_sales, 2)),
                'confidence_upper': round(predicted_sales + 1.96 * std_sales, 2)
            })
        
        return predictions
    
    async def predict(
        self, 
        store_id: int, 
        item_id: int, 
        days: int = None
    ) -> List[Dict]:
        """Generate sales predictions"""
        days = days or settings.forecast_days
        cache_key = f"{self.CACHE_KEY_PREFIX}:{store_id}:{item_id}:{days}"
        
        # Check cache first
        cached = await cache_get(cache_key)
        if cached:
            return cached
        
        # Get historical data
        data = await self._get_historical_data(store_id, item_id)
        
        if not data or len(data) < 7:
            return []
        
        # Calculate predictions
        predictions = self._calculate_predictions(data, days)
        
        if predictions:
            # Cache results
            await cache_set(cache_key, predictions, self.CACHE_TTL)
        
        return predictions
