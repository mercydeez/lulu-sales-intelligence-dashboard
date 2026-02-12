"""
Employee Routes - Employee Management, Performance, and Analytics API
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.orm import selectinload
import asyncio
import json

from app.services.database import async_session
from app.models.employee import (
    Employee, EmployeePerformance, EmployeeTransaction, 
    EmployeeAttendance, EmployeeCertification
)
from app.models.sales import Store
from app.services.employee_performance_streamer import get_live_employee_metrics
from app.config import logger

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class EmployeeBase(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    role: str = "sales_executive"
    department: str = "sales"
    designation: Optional[str] = None
    store_id: Optional[int] = None
    date_of_joining: date


class EmployeeCreate(EmployeeBase):
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    reports_to_id: Optional[int] = None


class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    store_id: Optional[int] = None
    status: Optional[str] = None
    date_of_resignation: Optional[date] = None


class PerformanceResponse(BaseModel):
    id: int
    employee_id: int
    period_type: str
    period_start: date
    period_end: date
    sales_target: float
    sales_achieved: float
    sales_achievement_pct: float
    transactions_count: int
    returns_count: int
    customer_rating: float
    attendance_percentage: float
    performance_score: float
    performance_grade: Optional[str]


class EmployeeResponse(BaseModel):
    id: int
    employee_code: str
    full_name: str
    first_name: str
    last_name: str
    email: str
    phone: Optional[str]
    role: str
    department: str
    designation: Optional[str]
    store_id: Optional[int]
    store_name: Optional[str]
    status: str
    date_of_joining: date
    date_of_resignation: Optional[date]
    tenure_days: int
    photo_url: Optional[str]
    latest_performance_score: Optional[float]
    latest_performance_grade: Optional[str]


# =============================================================================
# EMPLOYEE CRUD ENDPOINTS
# =============================================================================

@router.get("/employees", response_model=Dict[str, Any])
async def get_employees(
    store_id: Optional[int] = Query(None, description="Filter by store"),
    role: Optional[str] = Query(None, description="Filter by role"),
    department: Optional[str] = Query(None, description="Filter by department"),
    status: Optional[str] = Query("active", description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """Get paginated list of employees with filters"""
    try:
        async with async_session() as session:
            # Base query
            query = select(Employee).options(selectinload(Employee.store))
            
            # Apply filters
            conditions = []
            if store_id:
                conditions.append(Employee.store_id == store_id)
            if role:
                conditions.append(Employee.role == role)
            if department:
                conditions.append(Employee.department == department)
            if status:
                conditions.append(Employee.status == status)
            if search:
                search_term = f"%{search}%"
                conditions.append(
                    or_(
                        Employee.first_name.ilike(search_term),
                        Employee.last_name.ilike(search_term),
                        Employee.email.ilike(search_term),
                        Employee.employee_code.ilike(search_term)
                    )
                )
            
            if conditions:
                query = query.where(and_(*conditions))
            
            # Get total count
            count_query = select(func.count(Employee.id))
            if conditions:
                count_query = count_query.where(and_(*conditions))
            total = await session.scalar(count_query)
            
            # Apply pagination
            offset = (page - 1) * page_size
            query = query.order_by(Employee.employee_code).offset(offset).limit(page_size)
            
            result = await session.execute(query)
            employees = result.scalars().all()
            
            # Get latest performance for each employee
            employee_data = []
            for emp in employees:
                emp_dict = emp.to_dict()
                emp_dict["store_name"] = emp.store.name if emp.store else None
                
                # Get latest performance
                perf_query = select(EmployeePerformance).where(
                    EmployeePerformance.employee_id == emp.id
                ).order_by(desc(EmployeePerformance.period_end)).limit(1)
                perf_result = await session.execute(perf_query)
                perf = perf_result.scalar_one_or_none()
                
                emp_dict["latest_performance_score"] = float(perf.performance_score) if perf else None
                emp_dict["latest_performance_grade"] = perf.performance_grade if perf else None
                
                employee_data.append(emp_dict)
            
            return {
                "employees": employee_data,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }
            
    except Exception as e:
        logger.error(f"Error fetching employees: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employees/{employee_id}", response_model=Dict[str, Any])
async def get_employee(employee_id: int):
    """Get detailed employee information including performance history"""
    try:
        async with async_session() as session:
            query = select(Employee).options(
                selectinload(Employee.store),
                selectinload(Employee.performance_records),
                selectinload(Employee.certifications)
            ).where(Employee.id == employee_id)
            
            result = await session.execute(query)
            employee = result.scalar_one_or_none()
            
            if not employee:
                raise HTTPException(status_code=404, detail="Employee not found")
            
            emp_dict = employee.to_dict()
            emp_dict["store_name"] = employee.store.name if employee.store else None
            emp_dict["date_of_birth"] = employee.date_of_birth.isoformat() if employee.date_of_birth else None
            emp_dict["gender"] = employee.gender
            emp_dict["nationality"] = employee.nationality
            emp_dict["emergency_contact_name"] = employee.emergency_contact_name
            emp_dict["emergency_contact_phone"] = employee.emergency_contact_phone
            emp_dict["address"] = employee.address
            
            # Performance history
            emp_dict["performance_history"] = [
                p.to_dict() for p in sorted(
                    employee.performance_records, 
                    key=lambda x: x.period_end, 
                    reverse=True
                )[:12]  # Last 12 periods
            ]
            
            # Certifications
            emp_dict["certifications"] = [
                {
                    "id": c.id,
                    "name": c.certification_name,
                    "authority": c.issuing_authority,
                    "issue_date": c.issue_date.isoformat() if c.issue_date else None,
                    "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
                    "status": c.status
                }
                for c in employee.certifications
            ]
            
            # Recent transactions summary
            txn_query = select(
                func.count(EmployeeTransaction.id).label("total_transactions"),
                func.sum(EmployeeTransaction.net_amount).label("total_sales"),
                func.avg(EmployeeTransaction.net_amount).label("avg_transaction")
            ).where(
                and_(
                    EmployeeTransaction.employee_id == employee_id,
                    EmployeeTransaction.transaction_date >= date.today().replace(day=1)
                )
            )
            txn_result = await session.execute(txn_query)
            txn_summary = txn_result.one()
            
            emp_dict["current_month_stats"] = {
                "transactions": txn_summary.total_transactions or 0,
                "total_sales": float(txn_summary.total_sales or 0),
                "avg_transaction": float(txn_summary.avg_transaction or 0)
            }
            
            return emp_dict
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching employee {employee_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/employees", response_model=Dict[str, Any])
async def create_employee(employee: EmployeeCreate):
    """Create a new employee with full validation"""
    try:
        async with async_session() as session:
            # ===== VALIDATION 1: Check for duplicate email =====
            email_check = select(Employee).where(Employee.email == employee.email)
            existing = await session.execute(email_check)
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=400, 
                    detail=f"An employee with email '{employee.email}' already exists"
                )
            
            # ===== VALIDATION 2: Check store exists =====
            region_prefix = "UAE"
            if employee.store_id:
                store_query = select(Store).where(Store.id == employee.store_id)
                store_result = await session.execute(store_query)
                store = store_result.scalar_one_or_none()
                if not store:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Store with ID {employee.store_id} does not exist"
                    )
                if store.location:
                    region_map = {
                        "Dubai": "DXB",
                        "Abu Dhabi": "AUH", 
                        "Sharjah": "SHJ",
                        "Ajman": "AJM",
                        "Ras Al Khaimah": "RAK"
                    }
                    region_prefix = region_map.get(store.location, "UAE")
            
            # ===== VALIDATION 3: Check reports_to employee exists =====
            if employee.reports_to_id:
                mgr_query = select(Employee).where(Employee.id == employee.reports_to_id)
                mgr_result = await session.execute(mgr_query)
                if not mgr_result.scalar_one_or_none():
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Manager with ID {employee.reports_to_id} does not exist"
                    )
            
            # ===== VALIDATION 4: Check valid role =====
            valid_roles = [
                "sales_executive", "senior_sales", "team_lead", 
                "assistant_manager", "store_manager", "regional_manager",
                "cashier", "inventory_clerk", "customer_service"
            ]
            if employee.role and employee.role not in valid_roles:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid role '{employee.role}'. Valid roles: {', '.join(valid_roles)}"
                )
            
            # ===== VALIDATION 5: Check valid department =====
            valid_departments = [
                "sales", "management", "inventory", "customer_service", 
                "finance", "hr", "it", "logistics", "marketing"
            ]
            if employee.department and employee.department not in valid_departments:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid department '{employee.department}'. Valid departments: {', '.join(valid_departments)}"
                )
            
            # ===== VALIDATION 6: Date validations =====
            from datetime import date as date_type
            if employee.date_of_joining > date_type.today():
                pass  # Allow future join dates (scheduled hires)
            
            if employee.date_of_birth:
                age = (date_type.today() - employee.date_of_birth).days // 365
                if age < 18:
                    raise HTTPException(
                        status_code=400, 
                        detail="Employee must be at least 18 years old"
                    )
                if age > 100:
                    raise HTTPException(
                        status_code=400, 
                        detail="Invalid date of birth"
                    )
            
            # ===== VALIDATION 7: Check phone format (basic) =====
            if employee.phone:
                import re
                cleaned_phone = re.sub(r'[\s\-\(\)]', '', employee.phone)
                if not re.match(r'^\+?[\d]{7,15}$', cleaned_phone):
                    raise HTTPException(
                        status_code=400, 
                        detail="Invalid phone number format. Use 7-15 digits, optionally starting with +"
                    )
            
            # Generate employee code
            count_query = select(func.count(Employee.id))
            count = await session.scalar(count_query)
            employee_code = f"LLU-{region_prefix}-{(count + 1):04d}"
            
            # Ensure employee code is unique
            code_check = select(Employee).where(Employee.employee_code == employee_code)
            while (await session.execute(code_check)).scalar_one_or_none():
                count += 1
                employee_code = f"LLU-{region_prefix}-{(count + 1):04d}"
                code_check = select(Employee).where(Employee.employee_code == employee_code)
            
            # Create employee
            new_employee = Employee(
                employee_code=employee_code,
                first_name=employee.first_name,
                last_name=employee.last_name,
                email=employee.email,
                phone=employee.phone,
                date_of_birth=employee.date_of_birth,
                gender=employee.gender,
                nationality=employee.nationality,
                date_of_joining=employee.date_of_joining,
                role=employee.role,
                department=employee.department,
                designation=employee.designation,
                store_id=employee.store_id,
                reports_to_id=employee.reports_to_id,
                status="active"
            )
            
            session.add(new_employee)
            await session.commit()
            await session.refresh(new_employee)
            
            logger.info(f"Created employee: {employee_code} ({employee.first_name} {employee.last_name})")
            
            return {
                "success": True,
                "message": "Employee created successfully",
                "employee": new_employee.to_dict()
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating employee: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/employees/{employee_id}", response_model=Dict[str, Any])
async def update_employee(employee_id: int, update: EmployeeUpdate):
    """Update an employee with validation"""
    try:
        async with async_session() as session:
            query = select(Employee).where(Employee.id == employee_id)
            result = await session.execute(query)
            employee = result.scalar_one_or_none()
            
            if not employee:
                raise HTTPException(status_code=404, detail="Employee not found")
            
            update_data = update.dict(exclude_unset=True)
            
            # Validate store_id if being updated
            if "store_id" in update_data and update_data["store_id"] is not None:
                store_check = select(Store).where(Store.id == update_data["store_id"])
                store_result = await session.execute(store_check)
                if not store_result.scalar_one_or_none():
                    raise HTTPException(
                        status_code=400,
                        detail=f"Store with ID {update_data['store_id']} does not exist"
                    )
            
            # Validate role if being updated
            if "role" in update_data:
                valid_roles = [
                    "sales_executive", "senior_sales", "team_lead", 
                    "assistant_manager", "store_manager", "regional_manager",
                    "cashier", "inventory_clerk", "customer_service"
                ]
                if update_data["role"] not in valid_roles:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid role '{update_data['role']}'"
                    )
            
            # Validate department if being updated
            if "department" in update_data:
                valid_departments = [
                    "sales", "management", "inventory", "customer_service", 
                    "finance", "hr", "it", "logistics", "marketing"
                ]
                if update_data["department"] not in valid_departments:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid department '{update_data['department']}'"
                    )
            
            # Update fields
            for field, value in update_data.items():
                setattr(employee, field, value)
            
            await session.commit()
            await session.refresh(employee)
            
            logger.info(f"Updated employee: {employee.employee_code}")
            
            return {
                "success": True,
                "message": "Employee updated successfully",
                "employee": employee.to_dict()
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating employee {employee_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# PERFORMANCE ENDPOINTS
# =============================================================================

@router.get("/employees/{employee_id}/performance", response_model=Dict[str, Any])
async def get_employee_performance(
    employee_id: int,
    period_type: Optional[str] = Query("monthly"),
    limit: int = Query(12, ge=1, le=36)
):
    """Get employee performance history"""
    try:
        async with async_session() as session:
            query = select(EmployeePerformance).where(
                and_(
                    EmployeePerformance.employee_id == employee_id,
                    EmployeePerformance.period_type == period_type
                )
            ).order_by(desc(EmployeePerformance.period_end)).limit(limit)
            
            result = await session.execute(query)
            performances = result.scalars().all()
            
            return {
                "employee_id": employee_id,
                "period_type": period_type,
                "records": [p.to_dict() for p in performances]
            }
            
    except Exception as e:
        logger.error(f"Error fetching performance for employee {employee_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ANALYTICS ENDPOINTS
# =============================================================================

@router.get("/employees/analytics/by-role", response_model=Dict[str, Any])
async def get_performance_by_role():
    """Get aggregated performance metrics by role"""
    try:
        async with async_session() as session:
            query = select(
                Employee.role,
                func.count(Employee.id).label("employee_count"),
                func.avg(EmployeePerformance.performance_score).label("avg_score"),
                func.avg(EmployeePerformance.sales_achieved).label("avg_sales"),
                func.avg(EmployeePerformance.customer_rating).label("avg_rating"),
                func.avg(EmployeePerformance.attendance_percentage).label("avg_attendance"),
                func.sum(EmployeePerformance.transactions_count).label("total_transactions")
            ).outerjoin(
                EmployeePerformance, Employee.id == EmployeePerformance.employee_id
            ).where(
                Employee.status == "active"
            ).group_by(Employee.role)
            
            result = await session.execute(query)
            rows = result.all()
            
            return {
                "by_role": [
                    {
                        "role": row.role,
                        "employee_count": row.employee_count,
                        "avg_performance_score": round(float(row.avg_score or 0), 2),
                        "avg_sales": round(float(row.avg_sales or 0), 2),
                        "avg_customer_rating": round(float(row.avg_rating or 0), 2),
                        "avg_attendance": round(float(row.avg_attendance or 0), 2),
                        "total_transactions": row.total_transactions or 0
                    }
                    for row in rows
                ]
            }
            
    except Exception as e:
        logger.error(f"Error fetching role analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employees/analytics/by-store", response_model=Dict[str, Any])
async def get_performance_by_store():
    """Get aggregated performance metrics by store"""
    try:
        async with async_session() as session:
            query = select(
                Store.id.label("store_id"),
                Store.name.label("store_name"),
                Store.location,
                func.count(Employee.id).label("employee_count"),
                func.avg(EmployeePerformance.performance_score).label("avg_score"),
                func.sum(EmployeePerformance.sales_achieved).label("total_sales")
            ).outerjoin(
                Employee, Store.id == Employee.store_id
            ).outerjoin(
                EmployeePerformance, Employee.id == EmployeePerformance.employee_id
            ).where(
                or_(Employee.status == "active", Employee.status.is_(None))
            ).group_by(Store.id, Store.name, Store.location)
            
            result = await session.execute(query)
            rows = result.all()
            
            return {
                "by_store": [
                    {
                        "store_id": row.store_id,
                        "store_name": row.store_name,
                        "location": row.location,
                        "employee_count": row.employee_count or 0,
                        "avg_performance_score": round(float(row.avg_score or 0), 2),
                        "total_sales": round(float(row.total_sales or 0), 2)
                    }
                    for row in rows
                ]
            }
            
    except Exception as e:
        logger.error(f"Error fetching store analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employees/analytics/top-performers", response_model=Dict[str, Any])
async def get_top_performers(
    limit: int = Query(10, ge=1, le=50),
    role: Optional[str] = Query(None)
):
    """Get top performing employees"""
    try:
        async with async_session() as session:
            # Subquery for latest performance
            subquery = select(
                EmployeePerformance.employee_id,
                func.max(EmployeePerformance.period_end).label("latest_period")
            ).group_by(EmployeePerformance.employee_id).subquery()
            
            query = select(
                Employee,
                EmployeePerformance.performance_score,
                EmployeePerformance.performance_grade,
                EmployeePerformance.sales_achieved,
                EmployeePerformance.customer_rating
            ).join(
                EmployeePerformance, Employee.id == EmployeePerformance.employee_id
            ).join(
                subquery,
                and_(
                    EmployeePerformance.employee_id == subquery.c.employee_id,
                    EmployeePerformance.period_end == subquery.c.latest_period
                )
            ).where(Employee.status == "active")
            
            if role:
                query = query.where(Employee.role == role)
            
            query = query.order_by(desc(EmployeePerformance.performance_score)).limit(limit)
            
            result = await session.execute(query)
            rows = result.all()
            
            return {
                "top_performers": [
                    {
                        "employee_id": row.Employee.id,
                        "employee_code": row.Employee.employee_code,
                        "full_name": row.Employee.full_name,
                        "role": row.Employee.role,
                        "store_id": row.Employee.store_id,
                        "performance_score": float(row.performance_score or 0),
                        "performance_grade": row.performance_grade,
                        "sales_achieved": float(row.sales_achieved or 0),
                        "customer_rating": float(row.customer_rating or 0)
                    }
                    for row in rows
                ]
            }
            
    except Exception as e:
        logger.error(f"Error fetching top performers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employees/analytics/summary", response_model=Dict[str, Any])
async def get_employee_summary():
    """Get overall employee statistics summary"""
    try:
        async with async_session() as session:
            # Total employees by status
            status_query = select(
                Employee.status,
                func.count(Employee.id).label("count")
            ).group_by(Employee.status)
            status_result = await session.execute(status_query)
            status_counts = {row.status: row.count for row in status_result.all()}
            
            # By role
            role_query = select(
                Employee.role,
                func.count(Employee.id).label("count")
            ).where(Employee.status == "active").group_by(Employee.role)
            role_result = await session.execute(role_query)
            role_counts = {row.role: row.count for row in role_result.all()}
            
            # Average performance
            perf_query = select(
                func.avg(EmployeePerformance.performance_score).label("avg_score"),
                func.avg(EmployeePerformance.attendance_percentage).label("avg_attendance"),
                func.avg(EmployeePerformance.customer_rating).label("avg_rating")
            )
            perf_result = await session.execute(perf_query)
            perf_stats = perf_result.one()
            
            # New hires this month
            first_of_month = date.today().replace(day=1)
            new_hires_query = select(func.count(Employee.id)).where(
                Employee.date_of_joining >= first_of_month
            )
            new_hires = await session.scalar(new_hires_query)
            
            # Resignations this month
            resignations_query = select(func.count(Employee.id)).where(
                Employee.date_of_resignation >= first_of_month
            )
            resignations = await session.scalar(resignations_query)
            
            return {
                "total_employees": sum(status_counts.values()),
                "by_status": status_counts,
                "by_role": role_counts,
                "avg_performance_score": round(float(perf_stats.avg_score or 0), 2),
                "avg_attendance": round(float(perf_stats.avg_attendance or 0), 2),
                "avg_customer_rating": round(float(perf_stats.avg_rating or 0), 2),
                "new_hires_this_month": new_hires or 0,
                "resignations_this_month": resignations or 0
            }
            
    except Exception as e:
        logger.error(f"Error fetching employee summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LIVE STREAMING ENDPOINTS
# =============================================================================

@router.get("/employees/live/metrics", response_model=Dict[str, Any])
async def get_live_metrics():
    """Get live employee performance metrics from cache"""
    try:
        metrics = await get_live_employee_metrics()
        return metrics
    except Exception as e:
        logger.error(f"Error fetching live metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employees/live/stream")
async def stream_employee_performance(request: Request):
    """SSE endpoint for real-time employee performance updates"""
    from sse_starlette.sse import EventSourceResponse
    from app.services.redis_client import get_redis
    
    async def event_generator():
        redis = await get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe("employee_performance")
        
        try:
            # Send initial data
            initial_data = await get_live_employee_metrics()
            yield {
                "event": "initial",
                "data": json.dumps(initial_data)
            }
            
            # Stream updates
            while True:
                if await request.is_disconnected():
                    break
                
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    yield {
                        "event": "update",
                        "data": message["data"].decode() if isinstance(message["data"], bytes) else message["data"]
                    }
                
                await asyncio.sleep(0.1)
                
        finally:
            await pubsub.unsubscribe("employee_performance")
    
    return EventSourceResponse(event_generator())


@router.get("/employees/performance/chart-data", response_model=Dict[str, Any])
async def get_performance_chart_data(
    employee_id: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    store_id: Optional[int] = Query(None),
    period_type: str = Query("monthly"),
    periods: int = Query(6, ge=1, le=12)
):
    """Get performance data formatted for charts"""
    try:
        async with async_session() as session:
            # Build query
            query = select(
                EmployeePerformance.period_start,
                EmployeePerformance.period_end,
                func.avg(EmployeePerformance.performance_score).label("avg_score"),
                func.avg(EmployeePerformance.sales_achieved).label("avg_sales"),
                func.avg(EmployeePerformance.customer_rating).label("avg_rating"),
                func.avg(EmployeePerformance.attendance_percentage).label("avg_attendance"),
                func.sum(EmployeePerformance.transactions_count).label("total_transactions"),
                func.count(EmployeePerformance.id).label("record_count")
            ).join(
                Employee, EmployeePerformance.employee_id == Employee.id
            ).where(
                EmployeePerformance.period_type == period_type
            )
            
            # Apply filters
            if employee_id:
                query = query.where(EmployeePerformance.employee_id == employee_id)
            if role:
                query = query.where(Employee.role == role)
            if store_id:
                query = query.where(Employee.store_id == store_id)
            
            query = query.group_by(
                EmployeePerformance.period_start,
                EmployeePerformance.period_end
            ).order_by(
                desc(EmployeePerformance.period_end)
            ).limit(periods)
            
            result = await session.execute(query)
            rows = result.all()
            
            # Format for charts
            chart_data = {
                "labels": [],
                "datasets": {
                    "performance_score": [],
                    "sales": [],
                    "customer_rating": [],
                    "attendance": [],
                    "transactions": []
                }
            }
            
            for row in reversed(rows):  # Chronological order
                label = row.period_end.strftime("%b %Y") if row.period_end else ""
                chart_data["labels"].append(label)
                chart_data["datasets"]["performance_score"].append(round(float(row.avg_score or 0), 2))
                chart_data["datasets"]["sales"].append(round(float(row.avg_sales or 0), 2))
                chart_data["datasets"]["customer_rating"].append(round(float(row.avg_rating or 0), 2))
                chart_data["datasets"]["attendance"].append(round(float(row.avg_attendance or 0), 2))
                chart_data["datasets"]["transactions"].append(int(row.total_transactions or 0))
            
            return chart_data
            
    except Exception as e:
        logger.error(f"Error fetching chart data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
