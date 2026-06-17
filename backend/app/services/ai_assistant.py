"""
AI Assistant Service - Enhanced with Real-Time Data Integration
Handles chatbot conversations with actual database queries and intelligent responses
"""
import asyncio
from typing import Optional, List, Dict, AsyncGenerator
from datetime import datetime, date, timedelta
from pydantic import BaseModel
from sqlalchemy import select, func, and_, desc
from app.services.database import async_session
from app.models.sales import Sale, Store, Item
from app.services.llm import get_provider_chain, LLMError


class Message(BaseModel):
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: Optional[str] = None


class ConversationContext:
    """Maintains conversation history and context for multi-turn conversations"""
    
    def __init__(self, max_history: int = 20):
        self.messages: List[Dict[str, str]] = []
        self.max_history = max_history
        self.user_preferences: Dict = {}
        self.detected_intents: List[str] = []
        self.cached_data: Dict = {}  # Cache for real-time data
    
    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.max_history:
            self.messages = self.messages[:1] + self.messages[-(self.max_history-1):]
    
    def get_messages(self) -> List[Dict[str, str]]:
        return self.messages
    
    def clear(self):
        self.messages = []
        self.detected_intents = []
        self.cached_data = {}


# Store conversation contexts per session
MAX_CONTEXTS = 1000
conversation_store: Dict[str, ConversationContext] = {}


def _evict_oldest_contexts() -> None:
    """Evict oldest conversation contexts when the store exceeds MAX_CONTEXTS."""
    while len(conversation_store) >= MAX_CONTEXTS:
        oldest_key = next(iter(conversation_store))
        del conversation_store[oldest_key]


def get_or_create_context(session_id: str) -> ConversationContext:
    """Get or create a conversation context for a session"""
    if session_id not in conversation_store:
        _evict_oldest_contexts()
        context = ConversationContext()
        context.add_message("system", get_system_prompt())
        conversation_store[session_id] = context
    return conversation_store[session_id]


# =============================================================================
# REAL-TIME DATA FETCHING FUNCTIONS
# =============================================================================

async def get_real_time_kpis() -> Dict:
    """Fetch real-time KPIs from database"""
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    async with async_session() as session:
        # Today's sales
        today_result = await session.execute(
            select(func.coalesce(func.sum(Sale.sales), 0))
            .where(Sale.date == today)
        )
        total_sales_today = today_result.scalar() or 0
        
        # Count positive and negative (returns) for today
        returns_result = await session.execute(
            select(func.coalesce(func.sum(Sale.sales), 0))
            .where(and_(Sale.date == today, Sale.sales < 0))
        )
        total_returns_today = abs(returns_result.scalar() or 0)
        
        # Week's sales
        week_result = await session.execute(
            select(func.coalesce(func.sum(Sale.sales), 0))
            .where(Sale.date >= week_ago)
        )
        total_sales_week = week_result.scalar() or 0
        
        # Month's sales
        month_result = await session.execute(
            select(func.coalesce(func.sum(Sale.sales), 0))
            .where(Sale.date >= month_ago)
        )
        total_sales_month = month_result.scalar() or 0
        
        # Transaction count today
        trans_result = await session.execute(
            select(func.count(Sale.id))
            .where(Sale.date == today)
        )
        transactions_today = trans_result.scalar() or 0
        
        # Streaming count (live transactions)
        stream_result = await session.execute(
            select(func.count(Sale.id))
            .where(Sale.is_streaming == True)
        )
        streaming_count = stream_result.scalar() or 0
        
        # Historical count
        hist_result = await session.execute(
            select(func.count(Sale.id))
            .where(Sale.is_streaming == False)
        )
        historical_count = hist_result.scalar() or 0
        
        return {
            'total_sales_today': total_sales_today,
            'total_returns_today': total_returns_today,
            'net_sales_today': total_sales_today - total_returns_today,
            'total_sales_week': total_sales_week,
            'total_sales_month': total_sales_month,
            'transactions_today': transactions_today,
            'streaming_records': streaming_count,
            'historical_records': historical_count,
            'total_records': streaming_count + historical_count
        }


async def get_store_sales(store_name: Optional[str] = None) -> Dict:
    """Fetch store-specific sales data"""
    async with async_session() as session:
        if store_name:
            # Search for specific store
            store_result = await session.execute(
                select(Store).where(Store.name.ilike(f'%{store_name}%'))
            )
            store = store_result.scalar_one_or_none()
            
            if store:
                # Get total sales for this store
                sales_result = await session.execute(
                    select(func.coalesce(func.sum(Sale.sales), 0))
                    .where(Sale.store_id == store.id)
                )
                total_sales = sales_result.scalar() or 0
                
                # Get today's sales
                today_result = await session.execute(
                    select(func.coalesce(func.sum(Sale.sales), 0))
                    .where(and_(Sale.store_id == store.id, Sale.date == date.today()))
                )
                today_sales = today_result.scalar() or 0
                
                # Get returns
                returns_result = await session.execute(
                    select(func.coalesce(func.sum(Sale.sales), 0))
                    .where(and_(Sale.store_id == store.id, Sale.sales < 0))
                )
                total_returns = abs(returns_result.scalar() or 0)
                
                return {
                    'found': True,
                    'store_name': store.name,
                    'location': store.location,
                    'total_sales': total_sales,
                    'today_sales': today_sales,
                    'total_returns': total_returns,
                    'net_sales': total_sales
                }
            return {'found': False, 'store_name': store_name}
        
        # Get all stores performance
        query = select(
            Store.id,
            Store.name,
            Store.location,
            func.coalesce(func.sum(Sale.sales), 0).label('total_sales')
        ).outerjoin(Sale, Sale.store_id == Store.id).group_by(
            Store.id, Store.name, Store.location
        ).order_by(desc('total_sales'))
        
        result = await session.execute(query)
        stores = result.fetchall()
        
        total = sum(s.total_sales for s in stores)
        
        return {
            'stores': [
                {
                    'name': s.name,
                    'location': s.location,
                    'total_sales': s.total_sales,
                    'percentage': round((s.total_sales / total * 100) if total > 0 else 0, 1)
                }
                for s in stores
            ],
            'total': total
        }


async def get_category_sales() -> Dict:
    """Fetch sales by category"""
    async with async_session() as session:
        query = select(
            Item.category,
            func.coalesce(func.sum(Sale.sales), 0).label('total_sales'),
            func.count(Sale.id).label('transaction_count')
        ).join(Item, Sale.item_id == Item.id).group_by(
            Item.category
        ).order_by(desc('total_sales'))
        
        result = await session.execute(query)
        categories = result.fetchall()
        
        total = sum(c.total_sales for c in categories)
        
        return {
            'categories': [
                {
                    'name': c.category,
                    'total_sales': c.total_sales,
                    'transactions': c.transaction_count,
                    'percentage': round((c.total_sales / total * 100) if total > 0 else 0, 1)
                }
                for c in categories
            ],
            'total': total
        }


async def get_top_items(limit: int = 10) -> Dict:
    """Fetch top selling items"""
    async with async_session() as session:
        query = select(
            Item.name,
            Item.category,
            func.coalesce(func.sum(Sale.sales), 0).label('total_sales')
        ).join(Item, Sale.item_id == Item.id).group_by(
            Item.id, Item.name, Item.category
        ).order_by(desc('total_sales')).limit(limit)
        
        result = await session.execute(query)
        items = result.fetchall()
        
        return {
            'items': [
                {
                    'name': i.name,
                    'category': i.category,
                    'total_sales': i.total_sales
                }
                for i in items
            ]
        }


async def get_recent_transactions(limit: int = 10) -> Dict:
    """Fetch recent streaming transactions"""
    async with async_session() as session:
        query = select(
            Sale, Store.name.label('store_name'), Item.name.label('item_name'), Item.category
        ).join(Store, Sale.store_id == Store.id).join(
            Item, Sale.item_id == Item.id
        ).where(Sale.is_streaming == True).order_by(
            desc(Sale.created_at)
        ).limit(limit)
        
        result = await session.execute(query)
        transactions = result.fetchall()
        
        return {
            'transactions': [
                {
                    'id': t.Sale.id,
                    'store': t.store_name,
                    'item': t.item_name,
                    'category': t.category,
                    'sales': t.Sale.sales,
                    'is_return': t.Sale.sales < 0,
                    'timestamp': t.Sale.created_at.isoformat() if t.Sale.created_at else None
                }
                for t in transactions
            ]
        }


async def get_returns_data(store_name: Optional[str] = None) -> Dict:
    """Fetch detailed returns data - items with negative sales values"""
    today = date.today()
    
    async with async_session() as session:
        # Base query for returns (negative sales)
        base_filter = Sale.sales < 0
        
        # Today's returns
        today_returns_query = select(
            Sale, Store.name.label('store_name'), Item.name.label('item_name'), Item.category
        ).join(Store, Sale.store_id == Store.id).join(
            Item, Sale.item_id == Item.id
        ).where(and_(base_filter, Sale.date == today)).order_by(desc(Sale.created_at))
        
        today_result = await session.execute(today_returns_query)
        today_returns = today_result.fetchall()
        
        # All returns (streaming)
        all_returns_query = select(
            Sale, Store.name.label('store_name'), Item.name.label('item_name'), Item.category
        ).join(Store, Sale.store_id == Store.id).join(
            Item, Sale.item_id == Item.id
        ).where(and_(base_filter, Sale.is_streaming == True)).order_by(desc(Sale.created_at)).limit(50)
        
        all_result = await session.execute(all_returns_query)
        all_returns = all_result.fetchall()
        
        # Total returns count and value today
        today_stats = await session.execute(
            select(
                func.count(Sale.id).label('count'),
                func.coalesce(func.sum(Sale.sales), 0).label('total')
            ).where(and_(Sale.sales < 0, Sale.date == today))
        )
        today_stat = today_stats.fetchone()
        
        # Total returns all time (streaming)
        all_stats = await session.execute(
            select(
                func.count(Sale.id).label('count'),
                func.coalesce(func.sum(Sale.sales), 0).label('total')
            ).where(and_(Sale.sales < 0, Sale.is_streaming == True))
        )
        all_stat = all_stats.fetchone()
        
        # Returns by store
        by_store_query = select(
            Store.name,
            func.count(Sale.id).label('return_count'),
            func.coalesce(func.sum(Sale.sales), 0).label('return_value')
        ).join(Store, Sale.store_id == Store.id).where(
            and_(Sale.sales < 0, Sale.is_streaming == True)
        ).group_by(Store.name).order_by(desc('return_count'))
        
        by_store_result = await session.execute(by_store_query)
        returns_by_store = by_store_result.fetchall()
        
        # Returns by category
        by_category_query = select(
            Item.category,
            func.count(Sale.id).label('return_count'),
            func.coalesce(func.sum(Sale.sales), 0).label('return_value')
        ).join(Item, Sale.item_id == Item.id).where(
            and_(Sale.sales < 0, Sale.is_streaming == True)
        ).group_by(Item.category).order_by(desc('return_count'))
        
        by_category_result = await session.execute(by_category_query)
        returns_by_category = by_category_result.fetchall()
        
        return {
            'today': {
                'count': today_stat.count if today_stat else 0,
                'total_value': abs(today_stat.total) if today_stat else 0,
                'items': [
                    {
                        'store': t.store_name,
                        'item': t.item_name,
                        'category': t.category,
                        'quantity': abs(t.Sale.sales),
                        'timestamp': t.Sale.created_at.isoformat() if t.Sale.created_at else None
                    }
                    for t in today_returns
                ]
            },
            'all_time': {
                'count': all_stat.count if all_stat else 0,
                'total_value': abs(all_stat.total) if all_stat else 0,
                'recent_items': [
                    {
                        'store': t.store_name,
                        'item': t.item_name,
                        'category': t.category,
                        'quantity': abs(t.Sale.sales),
                        'timestamp': t.Sale.created_at.isoformat() if t.Sale.created_at else None
                    }
                    for t in all_returns[:20]
                ]
            },
            'by_store': [
                {
                    'store': s.name,
                    'count': s.return_count,
                    'value': abs(s.return_value)
                }
                for s in returns_by_store
            ],
            'by_category': [
                {
                    'category': c.category,
                    'count': c.return_count,
                    'value': abs(c.return_value)
                }
                for c in returns_by_category
            ]
        }


async def get_dashboard_summary() -> str:
    """Generate a comprehensive dashboard summary with real data"""
    kpis = await get_real_time_kpis()
    stores = await get_store_sales()
    categories = await get_category_sales()
    top_items = await get_top_items(5)
    recent = await get_recent_transactions(5)
    
    # Find top performing store
    top_store = stores['stores'][0] if stores.get('stores') else None
    
    # Find top category
    top_category = categories['categories'][0] if categories.get('categories') else None
    
    summary = f"""📊 **Real-Time Dashboard Summary**

**Today's Performance:**
• Total Sales: **{kpis['total_sales_today']:,}** units
• Returns: **{kpis['total_returns_today']:,}** units  
• Net Sales: **{kpis['net_sales_today']:,}** units
• Transactions: **{kpis['transactions_today']:,}**

**Period Totals:**
• This Week: **{kpis['total_sales_week']:,}** units
• This Month: **{kpis['total_sales_month']:,}** units

**Top Performing Store:**
• {top_store['name']} - **{top_store['total_sales']:,}** units ({top_store['percentage']}% of total)

**Top Category:**
• {top_category['name']} - **{top_category['total_sales']:,}** units ({top_category['percentage']}% of total)

**Top 5 Products:**
"""
    for i, item in enumerate(top_items['items'][:5], 1):
        summary += f"{i}. {item['name']} ({item['category']}): **{item['total_sales']:,}** units\n"
    
    summary += f"""
**Database Status:**
• Historical Records: {kpis['historical_records']:,}
• Live Streaming Records: {kpis['streaming_records']:,}
• Total Records: {kpis['total_records']:,}

**Recent Transactions:**
"""
    for t in recent['transactions'][:5]:
        status = "🔄 RETURN" if t['is_return'] else "💰 SALE"
        summary += f"• {status} {t['item']} at {t['store']}: {t['sales']} units\n"
    
    return summary


# =============================================================================
# INTENT DETECTION AND RESPONSE GENERATION
# =============================================================================

def get_system_prompt() -> str:
    """Get the system prompt for the AI assistant"""
    return """You are Lulu AI, an intelligent sales analytics assistant for the Lulu Hypermarket dashboard.

CRITICAL INSTRUCTIONS:
1. When users ask for specific data (sales, store info, etc.), you MUST use the ACTUAL DATA provided in the context
2. NEVER say "I don't have access to real-time data" - you DO have access through the data context
3. Format numbers with commas (e.g., 47,700,000 not 47700000)
4. Be specific and data-driven in responses
5. Highlight key insights and comparisons
6. Use emojis for visual appeal: 📊 📈 📉 💰 🏪 🛒

STORES (10 Lulu Hypermarket locations):
1. Lulu Hypermarket Al Barsha (Dubai)
2. Lulu Hypermarket Deira City Centre (Dubai)  
3. Lulu Hypermarket Karama (Dubai)
4. Lulu Hypermarket Silicon Oasis (Dubai)
5. Lulu Hypermarket Mall of the Emirates (Dubai)
6. Lulu Hypermarket Sharjah
7. Lulu Hypermarket Ajman
8. Lulu Hypermarket Fujairah
9. Lulu Hypermarket Al Ain (Abu Dhabi)
10. Lulu Hypermarket Ras Al Khaimah

PRODUCT CATEGORIES:
Dairy, Beverages, Bakery, Personal Care, Household, Snacks, Rice & Grains, 
Vegetables, Frozen, Condiments, Deli, Meat & Poultry, Seafood

DATA FEATURES:
- Real-time streaming sales every 5-15 seconds
- Product returns (negative sales values)
- Market volatility and demand fluctuations
- Historical data from 2013-2017 (913,000+ records)

Response Guidelines:
- Be concise but thorough
- Use bullet points for lists
- Highlight key metrics in **bold**
- Provide actionable insights when relevant"""


def detect_intent(message: str) -> Dict:
    """Detect user intent from message"""
    message_lower = message.lower()
    
    # CRITICAL: Check for returns query FIRST - it has priority!
    # Returns keywords - check these first as they're specific
    return_keywords = ["return", "returns", "returned", "refund", "refunds", "refunded", "negative", "loss", "losses"]
    is_returns_query = any(kw in message_lower for kw in return_keywords)
    
    # If it's a returns query, return ONLY returns_query intent to avoid confusion
    if is_returns_query:
        return {
            "intents": ["returns_query"],
            "mentioned_store": None,
            "is_returns": True
        }
    
    intents = {
        "dashboard_summary": ["summary", "overview", "dashboard", "how is", "what's happening", "status"],
        "sales_query": ["sales", "revenue", "sold", "selling", "performance", "total"],
        "store_query": ["store", "location", "branch", "outlet", "karama", "barsha", "deira", "ajman", "sharjah", "fujairah", "al ain", "ras al khaimah"],
        "category_query": ["category", "categories", "product", "item", "dairy", "beverages", "bakery", "vegetables"],
        "trend_analysis": ["trend", "pattern", "growth", "decline", "compare", "comparison", "change"],
        "top_items": ["top", "best", "highest", "most popular", "best selling"],
        "recent_activity": ["recent", "latest", "last", "new", "live", "streaming"],
        "prediction": ["predict", "forecast", "future", "expect", "projection", "tomorrow"],
        "help": ["help", "how to", "what can", "guide", "tutorial"],
        "greeting": ["hello", "hi", "hey", "good morning", "good afternoon"],
    }
    
    detected = []
    for intent, keywords in intents.items():
        if any(kw in message_lower for kw in keywords):
            detected.append(intent)
    
    # Extract store name if mentioned
    store_keywords = {
        'karama': 'Karama', 'barsha': 'Al Barsha', 'deira': 'Deira',
        'ajman': 'Ajman', 'sharjah': 'Sharjah', 'fujairah': 'Fujairah',
        'al ain': 'Al Ain', 'ras al khaimah': 'Ras Al Khaimah',
        'silicon': 'Silicon Oasis', 'mall of emirates': 'Mall of the Emirates'
    }
    
    mentioned_store = None
    for keyword, store_name in store_keywords.items():
        if keyword in message_lower:
            mentioned_store = store_name
            break
    
    return {
        "intents": detected if detected else ["general"],
        "mentioned_store": mentioned_store
    }


async def build_data_context(intent_info: Dict, message: str) -> str:
    """Build real-time data context based on detected intent"""
    intents = intent_info.get("intents", [])
    mentioned_store = intent_info.get("mentioned_store")
    
    context_parts = []
    
    # Always include KPIs for context
    kpis = await get_real_time_kpis()
    context_parts.append(f"""
CURRENT KPIs:
- Today's Sales: {kpis['total_sales_today']:,} units
- Today's Returns: {kpis['total_returns_today']:,} units
- Today's Transactions: {kpis['transactions_today']}
- This Week: {kpis['total_sales_week']:,} units
- This Month: {kpis['total_sales_month']:,} units
- Total Records: {kpis['total_records']:,}
""")
    
    # Add specific data based on intent
    if "dashboard_summary" in intents:
        summary = await get_dashboard_summary()
        context_parts.append(f"\nDASHBOARD SUMMARY:\n{summary}")
    
    if "store_query" in intents or mentioned_store:
        if mentioned_store:
            store_data = await get_store_sales(mentioned_store)
            if store_data.get('found'):
                context_parts.append(f"""
STORE DATA FOR {store_data['store_name'].upper()}:
- Location: {store_data['location']}
- Total Historical Sales: {store_data['total_sales']:,} units
- Today's Sales: {store_data['today_sales']:,} units
- Total Returns: {store_data['total_returns']:,} units
""")
        else:
            stores = await get_store_sales()
            context_parts.append("\nALL STORES PERFORMANCE:")
            for s in stores['stores']:
                context_parts.append(f"- {s['name']}: {s['total_sales']:,} units ({s['percentage']}%)")
    
    if "category_query" in intents or "top_items" in intents:
        categories = await get_category_sales()
        context_parts.append("\nCATEGORY BREAKDOWN:")
        for c in categories['categories']:
            context_parts.append(f"- {c['name']}: {c['total_sales']:,} units ({c['percentage']}%)")
        
        items = await get_top_items(10)
        context_parts.append("\nTOP 10 PRODUCTS:")
        for i, item in enumerate(items['items'], 1):
            context_parts.append(f"{i}. {item['name']} ({item['category']}): {item['total_sales']:,} units")
    
    if "recent_activity" in intents:
        recent = await get_recent_transactions(10)
        context_parts.append("\nRECENT LIVE TRANSACTIONS:")
        for t in recent['transactions']:
            status = "RETURN" if t['is_return'] else "SALE"
            context_parts.append(f"- [{status}] {t['item']} at {t['store']}: {t['sales']} units")
    
    if "returns_query" in intents:
        returns_data = await get_returns_data()
        context_parts.append(f"""
RETURNS DATA (DETAILED):
TODAY'S RETURNS:
- Count: {returns_data['today']['count']} returns
- Total Value: {returns_data['today']['total_value']:,} units returned

ALL-TIME RETURNS (Live/Streaming):
- Count: {returns_data['all_time']['count']} returns  
- Total Value: {returns_data['all_time']['total_value']:,} units returned

RETURNS BY STORE:""")
        for s in returns_data['by_store'][:10]:
            context_parts.append(f"- {s['store']}: {s['count']} returns ({s['value']:,} units)")
        
        context_parts.append("\nRETURNS BY CATEGORY:")
        for c in returns_data['by_category'][:10]:
            context_parts.append(f"- {c['category']}: {c['count']} returns ({c['value']:,} units)")
        
        context_parts.append("\nTODAY'S RETURN ITEMS:")
        for item in returns_data['today']['items'][:10]:
            context_parts.append(f"- {item['item']} ({item['category']}) from {item['store']}: {item['quantity']} units")
    
    return "\n".join(context_parts)


async def get_intelligent_fallback(message: str, intent_info: Dict) -> str:
    """Generate intelligent fallback response with REAL DATA when API unavailable"""
    intents = intent_info.get("intents", [])
    mentioned_store = intent_info.get("mentioned_store")
    is_returns = intent_info.get("is_returns", False)
    
    try:
        # Fetch real data for the response
        kpis = await get_real_time_kpis()
        
        # CRITICAL: Check returns query FIRST - highest priority!
        if "returns_query" in intents or is_returns:
            returns_data = await get_returns_data()
            
            response = f"""🔄 **Returns Analysis - All Stores**

📅 **Today's Returns:**
• Total Returns: **{returns_data['today']['count']}** items
• Total Value: **{returns_data['today']['total_value']:,}** units returned

📊 **All-Time Returns (Live Data):**
• Total Returns: **{returns_data['all_time']['count']}** items
• Total Value: **{returns_data['all_time']['total_value']:,}** units returned

"""
            
            # Returns by store
            if returns_data['by_store']:
                response += "🏪 **Returns by Store:**\n"
                for s in returns_data['by_store'][:5]:
                    response += f"• **{s['store']}**: {s['count']} returns ({s['value']:,} units)\n"
                response += "\n"
            
            # Returns by category
            if returns_data['by_category']:
                response += "📦 **Returns by Category:**\n"
                for c in returns_data['by_category'][:5]:
                    response += f"• **{c['category']}**: {c['count']} returns ({c['value']:,} units)\n"
                response += "\n"
            
            # Today's return items
            if returns_data['today']['items']:
                response += "📋 **Today's Returned Items:**\n"
                for item in returns_data['today']['items'][:10]:
                    response += f"• **{item['item']}** ({item['category']}) from {item['store']}: {item['quantity']} units\n"
            else:
                response += "📋 **Today's Returned Items:** No returns recorded today yet.\n"
            
            # Recent returns if no today items
            if not returns_data['today']['items'] and returns_data['all_time']['recent_items']:
                response += "\n📋 **Recent Returned Items:**\n"
                for item in returns_data['all_time']['recent_items'][:10]:
                    response += f"• **{item['item']}** ({item['category']}) from {item['store']}: {item['quantity']} units\n"
            
            return response
        
        # Greeting response
        if "greeting" in intents:
            return f"""👋 Hello! I'm **Lulu AI**, your sales analytics assistant.

📊 **Quick Stats Right Now:**
• Today's Sales: **{kpis['total_sales_today']:,}** units
• Today's Returns: **{kpis['total_returns_today']:,}** units
• Transactions: **{kpis['transactions_today']:,}**
• Live Records: **{kpis['streaming_records']:,}**

How can I help you analyze your sales data today?"""
        
        # Dashboard summary
        if "dashboard_summary" in intents:
            return await get_dashboard_summary()
        
        # Store-specific query
        if "store_query" in intents or mentioned_store:
            if mentioned_store:
                store_data = await get_store_sales(mentioned_store)
                if store_data.get('found'):
                    return f"""🏪 **{store_data['store_name']}**

📍 Location: {store_data['location']}

📊 **Performance Metrics:**
• Total Sales: **{store_data['total_sales']:,}** units
• Today's Sales: **{store_data['today_sales']:,}** units
• Returns: **{store_data['total_returns']:,}** units

This store is performing well in the network!"""
                else:
                    return f"I couldn't find a store matching '{mentioned_store}'. Try: Karama, Barsha, Deira, Ajman, Sharjah, Fujairah, Al Ain, or Ras Al Khaimah."
            else:
                stores = await get_store_sales()
                response = "🏪 **Store Performance Overview:**\n\n"
                for i, s in enumerate(stores['stores'][:5], 1):
                    response += f"{i}. **{s['name']}**: {s['total_sales']:,} units ({s['percentage']}%)\n"
                response += f"\n📊 Total Network Sales: **{stores['total']:,}** units"
                return response
        
        # Category query
        if "category_query" in intents:
            categories = await get_category_sales()
            response = "🛒 **Sales by Category:**\n\n"
            for c in categories['categories'][:8]:
                response += f"• **{c['name']}**: {c['total_sales']:,} units ({c['percentage']}%)\n"
            return response
        
        # Top items
        if "top_items" in intents:
            items = await get_top_items(10)
            response = "🏆 **Top 10 Best-Selling Products:**\n\n"
            for i, item in enumerate(items['items'], 1):
                response += f"{i}. **{item['name']}** ({item['category']}): {item['total_sales']:,} units\n"
            return response
        
        # Sales query
        if "sales_query" in intents:
            return f"""📊 **Sales Overview:**

**Today ({datetime.now().strftime('%B %d, %Y')}):**
• Total Sales: **{kpis['total_sales_today']:,}** units
• Returns: **{kpis['total_returns_today']:,}** units
• Net Sales: **{kpis['net_sales_today']:,}** units
• Transactions: **{kpis['transactions_today']:,}**

**Period Totals:**
• This Week: **{kpis['total_sales_week']:,}** units
• This Month: **{kpis['total_sales_month']:,}** units

**Database:**
• Historical Records: {kpis['historical_records']:,}
• Live Streaming: {kpis['streaming_records']:,}"""
        
        # Recent activity
        if "recent_activity" in intents:
            recent = await get_recent_transactions(10)
            response = "📡 **Recent Live Transactions:**\n\n"
            for t in recent['transactions']:
                emoji = "🔄" if t['is_return'] else "💰"
                response += f"{emoji} **{t['item']}** at {t['store']}: {t['sales']} units\n"
            return response
        
        # Help
        if "help" in intents:
            return """📖 **Lulu AI Help Guide:**

**Ask me about:**
• 📊 "What are today's sales?" - Current sales figures
• 🏪 "Show me Karama store performance" - Store-specific data
• 🛒 "What are the top categories?" - Category breakdown
• 🏆 "Top selling products" - Best performers
• 🔄 "How many returns today?" - Returns analysis
• 📡 "Show recent transactions" - Live feed

**Quick Commands:**
• "Dashboard summary" - Full overview
• "Compare stores" - Store comparison
• "Sales this week/month" - Period totals

The data updates in real-time every few seconds!"""
        
        # Default with actual data
        return f"""👋 I'm **Lulu AI**, your sales analytics assistant.

📊 **Current Status:**
• Today's Sales: **{kpis['total_sales_today']:,}** units
• Returns: **{kpis['total_returns_today']:,}** units  
• Total Records: **{kpis['total_records']:,}**

**Try asking:**
• "What are today's sales?"
• "Show me Karama store performance"
• "What are the top categories?"
• "Dashboard summary"

How can I help you?"""
    
    except Exception as e:
        return f"I encountered an error fetching data: {str(e)}. Please try again."


async def stream_chat_response(
    session_id: str,
    user_message: str
) -> AsyncGenerator[str, None]:
    """Stream chat response with real-time data integration"""
    
    context = get_or_create_context(session_id)
    
    # Detect intent
    intent_info = detect_intent(user_message)
    context.detected_intents.extend(intent_info["intents"])
    
    # Build real-time data context
    data_context = await build_data_context(intent_info, user_message)
    
    # Add user message with data context to conversation
    enhanced_message = f"""User Question: {user_message}

REAL-TIME DATA CONTEXT (use this data to answer):
{data_context}

INSTRUCTIONS: Answer the user's question using the ACTUAL DATA above. Be specific with numbers and percentages. Format large numbers with commas."""
    
    context.add_message("user", enhanced_message)
    
    # Try providers in priority order (Ollama → OpenAI → rule-based fallback)
    for provider in get_provider_chain():
        full_response = ""
        try:
            async for chunk in provider.stream(context.get_messages()):
                full_response += chunk
                yield chunk
            if full_response:
                context.add_message("assistant", full_response)
                return
        except LLMError:
            continue  # next provider

    # Rule-based fallback — always works, data-driven
    fallback = await get_intelligent_fallback(user_message, intent_info)
    context.add_message("assistant", fallback)
    words = fallback.split(' ')
    for i, word in enumerate(words):
        yield word + (' ' if i < len(words) - 1 else '')
        await asyncio.sleep(0.015)


async def get_chat_response(
    session_id: str,
    user_message: str
) -> str:
    """Get non-streaming chat response with real data"""
    
    context = get_or_create_context(session_id)
    intent_info = detect_intent(user_message)
    
    # Build data context
    data_context = await build_data_context(intent_info, user_message)
    
    enhanced_message = f"""User Question: {user_message}

REAL-TIME DATA CONTEXT:
{data_context}

Answer using the actual data above. Be specific with numbers."""
    
    context.add_message("user", enhanced_message)
    
    # Try providers in priority order (Ollama → OpenAI → rule-based fallback)
    for provider in get_provider_chain():
        try:
            response = await provider.complete(context.get_messages())
            if response:
                context.add_message("assistant", response)
                return response
        except LLMError:
            continue  # next provider

    # Rule-based fallback — always works, data-driven
    fallback = await get_intelligent_fallback(user_message, intent_info)
    context.add_message("assistant", fallback)
    return fallback


def clear_conversation(session_id: str):
    """Clear conversation history for a session"""
    if session_id in conversation_store:
        conversation_store[session_id].clear()
        conversation_store[session_id].add_message("system", get_system_prompt())


def get_conversation_summary(session_id: str) -> Dict:
    """Get summary of conversation for a session"""
    if session_id not in conversation_store:
        return {"message_count": 0, "intents": [], "active": False}
    
    context = conversation_store[session_id]
    return {
        "message_count": len(context.messages),
        "intents": list(set(context.detected_intents)),
        "active": True
    }
