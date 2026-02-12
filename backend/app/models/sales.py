from sqlalchemy import Column, Integer, String, Date, Boolean, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
import uuid

Base = declarative_base()


class Store(Base):
    __tablename__ = "stores"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    location = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    sales = relationship("Sale", back_populates="store")
    historical_sales = relationship("SalesHistorical", back_populates="store")
    streaming_sales = relationship("SalesStreamRaw", back_populates="store")


class Item(Base):
    __tablename__ = "items"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    sales = relationship("Sale", back_populates="item")
    historical_sales = relationship("SalesHistorical", back_populates="item")
    streaming_sales = relationship("SalesStreamRaw", back_populates="item")


# =============================================================================
# LEGACY TABLE (for backward compatibility)
# =============================================================================
class Sale(Base):
    __tablename__ = "sales"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    sales = Column(Integer, nullable=False)
    is_streaming = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    store = relationship("Store", back_populates="sales")
    item = relationship("Item", back_populates="sales")


# =============================================================================
# NEW TABLES (as per README architecture)
# =============================================================================
class SalesHistorical(Base):
    """Historical sales data - immutable, bulk loaded from CSV"""
    __tablename__ = "sales_historical"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    sales = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    store = relationship("Store", back_populates="historical_sales")
    item = relationship("Item", back_populates="historical_sales")


class SalesStreamRaw(Base):
    """Streaming sales data - append-only with UUID deduplication"""
    __tablename__ = "sales_stream_raw"
    
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    sales = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    store = relationship("Store", back_populates="streaming_sales")
    item = relationship("Item", back_populates="streaming_sales")


class Prediction(Base):
    __tablename__ = "predictions"
    
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    prediction_date = Column(Date, nullable=False)
    predicted_sales = Column(Float, nullable=False)
    confidence_lower = Column(Float)
    confidence_upper = Column(Float)
    model_version = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
