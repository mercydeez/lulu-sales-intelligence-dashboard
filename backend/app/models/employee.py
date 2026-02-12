"""
Employee Models - Complete Employee Management System
Handles employee biodata, performance tracking, and transaction attribution
"""
from sqlalchemy import (
    Column, Integer, String, Date, Boolean, Float, ForeignKey, 
    DateTime, Text, Numeric, Time, Enum, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.ext.hybrid import hybrid_property
import enum
from datetime import date

from app.models.sales import Base


# =============================================================================
# ENUMS
# =============================================================================

class EmployeeStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    TERMINATED = "terminated"
    ON_LEAVE = "on_leave"


class EmployeeDepartment(str, enum.Enum):
    MANAGEMENT = "management"
    SALES = "sales"
    INVENTORY = "inventory"
    CUSTOMER_SERVICE = "customer_service"
    FINANCE = "finance"
    HR = "hr"
    IT = "it"
    LOGISTICS = "logistics"
    MARKETING = "marketing"


class TransactionType(str, enum.Enum):
    SALE = "sale"
    RETURN = "return"
    VOID = "void"
    EXCHANGE = "exchange"
    REFUND = "refund"


class PerformancePeriod(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    HALF_DAY = "half_day"
    LEAVE = "leave"


# =============================================================================
# EMPLOYEE MODEL
# =============================================================================

class Employee(Base):
    """Complete employee biodata and status tracking"""
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_code = Column(String(20), unique=True, nullable=False)  # LLU-DXB-001
    
    # Personal Information
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(20))
    date_of_birth = Column(Date)
    gender = Column(String(10))
    nationality = Column(String(50))
    
    # Employment Details
    date_of_joining = Column(Date, nullable=False)
    date_of_resignation = Column(Date, nullable=True)
    date_of_termination = Column(Date, nullable=True)
    
    # Role & Assignment
    role = Column(String(50), nullable=False, default="sales_executive")
    department = Column(String(50), nullable=False, default="sales")
    designation = Column(String(100))
    store_id = Column(Integer, ForeignKey("stores.id"))
    region_id = Column(Integer)
    reports_to_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    
    # Status
    status = Column(String(20), nullable=False, default="active")
    
    # Additional Info
    photo_url = Column(String(500))
    emergency_contact_name = Column(String(100))
    emergency_contact_phone = Column(String(20))
    address = Column(Text)
    salary_grade = Column(String(10))
    
    # Link to Auth User
    user_id = Column(Integer, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    store = relationship("Store", foreign_keys=[store_id])
    manager = relationship("Employee", remote_side=[id], foreign_keys=[reports_to_id])
    subordinates = relationship("Employee", back_populates="manager", foreign_keys=[reports_to_id])
    performance_records = relationship("EmployeePerformance", back_populates="employee", foreign_keys="EmployeePerformance.employee_id", cascade="all, delete-orphan")
    transactions = relationship("EmployeeTransaction", back_populates="employee", foreign_keys="EmployeeTransaction.employee_id")
    attendance_records = relationship("EmployeeAttendance", back_populates="employee", cascade="all, delete-orphan")
    certifications = relationship("EmployeeCertification", back_populates="employee", cascade="all, delete-orphan")
    
    @hybrid_property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
    
    @hybrid_property
    def is_active(self) -> bool:
        return self.status == "active"
    
    @hybrid_property
    def tenure_days(self) -> int:
        end_date = self.date_of_resignation or self.date_of_termination or date.today()
        return (end_date - self.date_of_joining).days
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_code": self.employee_code,
            "full_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "role": self.role,
            "department": self.department,
            "designation": self.designation,
            "store_id": self.store_id,
            "status": self.status,
            "date_of_joining": self.date_of_joining.isoformat() if self.date_of_joining else None,
            "date_of_resignation": self.date_of_resignation.isoformat() if self.date_of_resignation else None,
            "tenure_days": self.tenure_days,
            "photo_url": self.photo_url
        }


# =============================================================================
# EMPLOYEE PERFORMANCE MODEL
# =============================================================================

class EmployeePerformance(Base):
    """Performance tracking with KPIs for each period"""
    __tablename__ = "employee_performance"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    
    # Period
    period_type = Column(String(20), nullable=False, default="monthly")
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    
    # Sales Metrics
    sales_target = Column(Numeric(12, 2), default=0)
    sales_achieved = Column(Numeric(12, 2), default=0)
    
    # Transaction Metrics
    transactions_count = Column(Integer, default=0)
    returns_count = Column(Integer, default=0)
    voids_count = Column(Integer, default=0)
    avg_transaction_value = Column(Numeric(10, 2), default=0)
    items_sold = Column(Integer, default=0)
    
    # Customer Metrics
    customers_served = Column(Integer, default=0)
    customer_rating = Column(Numeric(3, 2), default=0)  # 0.00 to 5.00
    complaints_received = Column(Integer, default=0)
    compliments_received = Column(Integer, default=0)
    
    # Attendance Metrics
    days_present = Column(Integer, default=0)
    days_absent = Column(Integer, default=0)
    days_late = Column(Integer, default=0)
    overtime_hours = Column(Numeric(6, 2), default=0)
    attendance_percentage = Column(Numeric(5, 2), default=100)
    
    # Overall Score
    performance_score = Column(Numeric(5, 2), default=0)
    performance_grade = Column(String(2))  # A+, A, B+, B, C, D, F
    
    # Manager Review
    manager_comments = Column(Text)
    reviewed_by = Column(Integer, ForeignKey("employees.id"))
    reviewed_at = Column(DateTime(timezone=True))
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    employee = relationship("Employee", back_populates="performance_records", foreign_keys=[employee_id])
    reviewer = relationship("Employee", foreign_keys=[reviewed_by])
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('employee_id', 'period_type', 'period_start', name='unique_employee_period'),
    )
    
    @hybrid_property
    def sales_achievement_pct(self) -> float:
        if self.sales_target and self.sales_target > 0:
            return float(self.sales_achieved / self.sales_target * 100)
        return 0.0
    
    @hybrid_property
    def return_rate(self) -> float:
        if self.transactions_count and self.transactions_count > 0:
            return float(self.returns_count / self.transactions_count * 100)
        return 0.0
    
    def calculate_score(self) -> float:
        """Calculate weighted performance score"""
        # Weights: Sales 40%, Customer Rating 25%, Attendance 25%, Low Returns 10%
        sales_score = min(self.sales_achievement_pct, 150) / 150 * 40
        rating_score = float(self.customer_rating or 0) / 5 * 25
        attendance_score = float(self.attendance_percentage or 0) / 100 * 25
        return_score = (100 - min(self.return_rate, 100)) / 100 * 10
        
        return round(sales_score + rating_score + attendance_score + return_score, 2)
    
    def calculate_grade(self) -> str:
        """Calculate performance grade from score"""
        score = self.performance_score or self.calculate_score()
        if score >= 95: return "A+"
        elif score >= 90: return "A"
        elif score >= 85: return "B+"
        elif score >= 80: return "B"
        elif score >= 70: return "C"
        elif score >= 60: return "D"
        else: return "F"
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "period_type": self.period_type,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "sales_target": float(self.sales_target or 0),
            "sales_achieved": float(self.sales_achieved or 0),
            "sales_achievement_pct": self.sales_achievement_pct,
            "transactions_count": self.transactions_count,
            "returns_count": self.returns_count,
            "customer_rating": float(self.customer_rating or 0),
            "attendance_percentage": float(self.attendance_percentage or 0),
            "performance_score": float(self.performance_score or 0),
            "performance_grade": self.performance_grade
        }


# =============================================================================
# EMPLOYEE TRANSACTION MODEL
# =============================================================================

class EmployeeTransaction(Base):
    """Transaction attribution to employees"""
    __tablename__ = "employee_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_code = Column(String(50), unique=True, nullable=False)
    
    # Employee Attribution
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    
    # Transaction Details
    transaction_type = Column(String(20), nullable=False, default="sale")
    transaction_date = Column(Date, nullable=False)
    transaction_time = Column(Time, nullable=False)
    
    # Financial
    gross_amount = Column(Numeric(12, 2), nullable=False)
    discount_amount = Column(Numeric(10, 2), default=0)
    net_amount = Column(Numeric(12, 2), nullable=False)
    
    # Items
    items_count = Column(Integer, default=1)
    
    # Store Context
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    register_id = Column(String(20))
    
    # Customer
    customer_id = Column(String(50))
    payment_method = Column(String(20))
    
    # Status
    is_completed = Column(Boolean, default=True)
    is_voided = Column(Boolean, default=False)
    void_reason = Column(Text)
    voided_by = Column(Integer, ForeignKey("employees.id"))
    
    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    employee = relationship("Employee", back_populates="transactions", foreign_keys=[employee_id])
    store = relationship("Store")
    voided_by_employee = relationship("Employee", foreign_keys=[voided_by])
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "transaction_code": self.transaction_code,
            "employee_id": self.employee_id,
            "transaction_type": self.transaction_type,
            "transaction_date": self.transaction_date.isoformat() if self.transaction_date else None,
            "gross_amount": float(self.gross_amount or 0),
            "net_amount": float(self.net_amount or 0),
            "items_count": self.items_count,
            "store_id": self.store_id
        }


# =============================================================================
# EMPLOYEE ATTENDANCE MODEL
# =============================================================================

class EmployeeAttendance(Base):
    """Daily attendance tracking"""
    __tablename__ = "employee_attendance"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    
    attendance_date = Column(Date, nullable=False)
    check_in_time = Column(DateTime(timezone=True))
    check_out_time = Column(DateTime(timezone=True))
    
    status = Column(String(20), nullable=False, default="present")
    shift = Column(String(20), default="morning")
    
    hours_worked = Column(Numeric(4, 2))
    overtime_hours = Column(Numeric(4, 2), default=0)
    
    notes = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    employee = relationship("Employee", back_populates="attendance_records")
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('employee_id', 'attendance_date', name='unique_employee_attendance'),
    )


# =============================================================================
# EMPLOYEE CERTIFICATION MODEL
# =============================================================================

class EmployeeCertification(Base):
    """Training and certifications tracking"""
    __tablename__ = "employee_certifications"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    
    certification_name = Column(String(200), nullable=False)
    issuing_authority = Column(String(200))
    issue_date = Column(Date, nullable=False)
    expiry_date = Column(Date)
    certificate_url = Column(String(500))
    status = Column(String(20), default="active")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    employee = relationship("Employee", back_populates="certifications")
