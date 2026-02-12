"""
Employee Data Seeder
Seeds the database with synthetic employee data on application startup
"""
import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
import random
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import async_session, engine
from app.models.employee import (
    Employee, EmployeePerformance, EmployeeTransaction,
    EmployeeAttendance, EmployeeCertification
)
from app.models.sales import Store
from app.config import logger
from app.services.employee_generator import (
    generate_employees, generate_performance_data, generate_transactions,
    ROLE_CONFIG
)


async def check_employees_exist() -> bool:
    """Check if employees already exist in database with the correct count"""
    async with async_session() as session:
        result = await session.execute(select(func.count(Employee.id)))
        count = result.scalar()
        # Expected ~30 employees from ROLE_CONFIG
        # If we have a vastly different count (e.g. 100 from old config), re-seed
        from app.services.employee_generator import ROLE_CONFIG
        expected_count = sum(c["count"] for c in ROLE_CONFIG.values())
        if count and abs(count - expected_count) > 5:
            logger.info(f"Employee count mismatch: have {count}, expect ~{expected_count}. Will re-seed.")
            return False
        return count > 0


async def seed_employees():
    """Seed employees into the database"""
    logger.info("Starting employee data seeding...")
    
    # Check if already seeded with correct count
    if await check_employees_exist():
        logger.info("Employees already exist with correct count, skipping seeding")
        return
    
    # Clean up old employee data if it exists (re-seeding)
    async with async_session() as session:
        try:
            await session.execute(text("DELETE FROM employee_certifications"))
            await session.execute(text("DELETE FROM employee_attendance"))
            await session.execute(text("DELETE FROM employee_transactions"))
            await session.execute(text("DELETE FROM employee_performance"))
            await session.execute(text("DELETE FROM employees"))
            await session.commit()
            logger.info("Cleaned up old employee data for re-seeding")
        except Exception as e:
            await session.rollback()
            logger.warning(f"Cleanup warning (tables may not exist yet): {e}")
    
    # Generate synthetic data
    employees_data = generate_employees()
    logger.info(f"Generated {len(employees_data)} synthetic employees")
    
    async with async_session() as session:
        # Create employees
        employee_map = {}  # employee_code -> Employee object
        
        for emp_data in employees_data:
            employee = Employee(
                employee_code=emp_data["employee_code"],
                first_name=emp_data["first_name"],
                last_name=emp_data["last_name"],
                email=emp_data["email"],
                phone=emp_data["phone"],
                date_of_birth=emp_data["date_of_birth"],
                gender=emp_data["gender"],
                nationality=emp_data["nationality"],
                date_of_joining=emp_data["date_of_joining"],
                date_of_resignation=emp_data["date_of_resignation"],
                role=emp_data["role"],
                department=emp_data["department"],
                designation=emp_data["designation"],
                store_id=emp_data["store_id"],
                region_id=emp_data["region_id"],
                status=emp_data["status"],
                salary_grade=emp_data["salary_grade"]
            )
            session.add(employee)
            employee_map[emp_data["employee_code"]] = employee
        
        await session.flush()  # Get IDs
        
        # Set reporting relationships
        for emp_data in employees_data:
            if emp_data["reports_to_id"]:
                employee = employee_map[emp_data["employee_code"]]
                # Find the manager by index (1-based in original data)
                manager_idx = emp_data["reports_to_id"] - 1
                if 0 <= manager_idx < len(employees_data):
                    manager_code = employees_data[manager_idx]["employee_code"]
                    manager = employee_map.get(manager_code)
                    if manager:
                        employee.reports_to_id = manager.id
        
        await session.commit()
        logger.info(f"Seeded {len(employees_data)} employees")
        
        # Generate and seed performance data
        performance_data = generate_performance_data(employees_data, months=6)
        logger.info(f"Generated {len(performance_data)} performance records")
        
        for perf_data in performance_data:
            employee = employee_map.get(perf_data["employee_code"])
            if not employee:
                continue
            
            performance = EmployeePerformance(
                employee_id=employee.id,
                period_type=perf_data["period_type"],
                period_start=perf_data["period_start"],
                period_end=perf_data["period_end"],
                sales_target=Decimal(str(perf_data["sales_target"])),
                sales_achieved=Decimal(str(perf_data["sales_achieved"])),
                transactions_count=perf_data["transactions_count"],
                returns_count=perf_data["returns_count"],
                voids_count=perf_data["voids_count"],
                avg_transaction_value=Decimal(str(perf_data["avg_transaction_value"])),
                items_sold=perf_data["items_sold"],
                customers_served=perf_data["customers_served"],
                customer_rating=Decimal(str(perf_data["customer_rating"])),
                complaints_received=perf_data["complaints_received"],
                compliments_received=perf_data["compliments_received"],
                days_present=perf_data["days_present"],
                days_absent=perf_data["days_absent"],
                days_late=perf_data["days_late"],
                overtime_hours=Decimal(str(perf_data["overtime_hours"])),
                attendance_percentage=Decimal(str(perf_data["attendance_percentage"])),
                performance_score=Decimal(str(perf_data["performance_score"])),
                performance_grade=perf_data["performance_grade"]
            )
            session.add(performance)
        
        await session.commit()
        logger.info(f"Seeded {len(performance_data)} performance records")
        
        # Generate recent transactions (last 7 days for live feel)
        transactions_data = generate_transactions(employees_data, days=7)
        logger.info(f"Generated {len(transactions_data)} transaction records")
        
        batch_size = 1000
        for i in range(0, len(transactions_data), batch_size):
            batch = transactions_data[i:i+batch_size]
            for txn_data in batch:
                employee = employee_map.get(txn_data["employee_code"])
                if not employee:
                    continue
                
                # Parse time string to time object
                time_parts = txn_data["transaction_time"].split(":")
                from datetime import time as dt_time
                txn_time = dt_time(int(time_parts[0]), int(time_parts[1]), int(time_parts[2]))
                
                transaction = EmployeeTransaction(
                    transaction_code=txn_data["transaction_code"],
                    employee_id=employee.id,
                    transaction_type=txn_data["transaction_type"],
                    transaction_date=txn_data["transaction_date"],
                    transaction_time=txn_time,
                    gross_amount=Decimal(str(txn_data["gross_amount"])),
                    discount_amount=Decimal(str(txn_data["discount_amount"])),
                    net_amount=Decimal(str(txn_data["net_amount"])),
                    items_count=txn_data["items_count"],
                    store_id=txn_data["store_id"],
                    register_id=txn_data["register_id"],
                    payment_method=txn_data["payment_method"],
                    is_completed=txn_data["is_completed"],
                    is_voided=txn_data["is_voided"]
                )
                session.add(transaction)
            
            await session.commit()
            logger.info(f"Seeded transactions batch {i//batch_size + 1}")
        
        logger.info("Employee data seeding completed successfully!")


async def run_employee_migration():
    """Run the employee migration - create tables via SQLAlchemy models"""
    logger.info("Running employee migration...")
    
    try:
        from app.models.employee import (
            Employee, EmployeePerformance, EmployeeTransaction,
            EmployeeAttendance, EmployeeCertification
        )
        from app.models.sales import Base
        
        async with engine.begin() as conn:
            # Create all employee tables if they don't exist
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Employee migration completed (tables created via SQLAlchemy)")
        
    except Exception as e:
        logger.error(f"Error running migration: {e}")
        raise


async def initialize_employee_system():
    """Initialize the complete employee system"""
    try:
        # Run migration first
        await run_employee_migration()
        
        # Then seed data
        await seed_employees()
        
    except Exception as e:
        logger.error(f"Error initializing employee system: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(initialize_employee_system())
