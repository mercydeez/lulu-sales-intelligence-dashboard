"""
Synthetic Employee Data Generator
Generates realistic employee data for Meridian Hypermarket UAE with:
- Realistic UAE/South Asian names
- Performance metrics matching historical patterns
- Proper role distribution across stores
"""
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
import uuid

# =============================================================================
# REALISTIC NAME POOLS
# =============================================================================

# UAE/South Asian first names (common in UAE retail)
FIRST_NAMES_MALE = [
    # Arabic
    "Mohammed", "Ahmed", "Ali", "Omar", "Khalid", "Hassan", "Hussein", "Saeed", 
    "Ibrahim", "Youssef", "Rashid", "Faisal", "Abdullah", "Tariq", "Waleed",
    # Indian/Pakistani
    "Raj", "Vikram", "Arun", "Suresh", "Ramesh", "Pradeep", "Sanjay", "Amit",
    "Rahul", "Vijay", "Ajay", "Deepak", "Manoj", "Rajesh", "Sunil", "Anil",
    "Naveen", "Harish", "Ganesh", "Krishna", "Arjun", "Kiran", "Nitin", "Rohit",
    # Filipino
    "Jose", "Juan", "Carlo", "Miguel", "Rafael", "Antonio", "Mark", "John",
    # Pakistani
    "Imran", "Asif", "Zaheer", "Wasim", "Waqar", "Shoaib", "Usman", "Bilal"
]

FIRST_NAMES_FEMALE = [
    # Arabic
    "Fatima", "Aisha", "Mariam", "Noura", "Sara", "Layla", "Hana", "Amina",
    "Zahra", "Rania", "Nadia", "Salma", "Yasmin", "Leila", "Samira",
    # Indian
    "Priya", "Anita", "Sunita", "Kavita", "Meena", "Deepa", "Neha", "Pooja",
    "Anjali", "Divya", "Shweta", "Rekha", "Sita", "Geeta", "Radha", "Lakshmi",
    # Filipino
    "Maria", "Ana", "Rosa", "Elena", "Grace", "Joy", "Faith", "Hope"
]

LAST_NAMES = [
    # Arabic
    "Al-Maktoum", "Al-Nahyan", "Al-Qasimi", "Al-Nuaimi", "Al-Sharqi", 
    "Al-Mualla", "Khan", "Sheikh", "Hussain", "Rahman", "Malik", "Abbas",
    # Indian
    "Patel", "Sharma", "Kumar", "Singh", "Verma", "Gupta", "Joshi", "Pillai",
    "Nair", "Menon", "Reddy", "Rao", "Iyer", "Agarwal", "Mehta", "Shah",
    "Kapoor", "Malhotra", "Chopra", "Khanna", "Bhatia", "Sinha", "Chatterjee",
    # Pakistani
    "Qureshi", "Siddiqui", "Mirza", "Butt", "Chaudhry", "Raza", "Iqbal",
    # Filipino
    "Santos", "Cruz", "Garcia", "Reyes", "Ramos", "Mendoza", "Torres"
]

NATIONALITIES = [
    ("Indian", 35), ("Pakistani", 20), ("Filipino", 15), ("Bangladeshi", 10),
    ("Emirati", 5), ("Egyptian", 5), ("Nepali", 5), ("Sri Lankan", 5)
]

# =============================================================================
# ROLE CONFIGURATION
# =============================================================================

ROLE_CONFIG = {
    "super_admin": {
        "count": 1,
        "department": "management",
        "designation": "Chief Operating Officer",
        "salary_grade": "E1",
        "base_target": 0,  # No sales target
        "store_id": None  # HQ
    },
    "regional_manager": {
        "count": 2,
        "department": "management", 
        "designation": "Regional Manager",
        "salary_grade": "M1",
        "base_target": 500000,
        "store_id": None  # Multiple stores
    },
    "store_manager": {
        "count": 5,
        "department": "management",
        "designation": "Store Manager",
        "salary_grade": "M2",
        "base_target": 300000,
        "store_id": "assigned"
    },
    "inventory_manager": {
        "count": 3,
        "department": "inventory",
        "designation": "Inventory Manager",
        "salary_grade": "S1",
        "base_target": 50000,
        "store_id": "assigned"
    },
    "sales_executive": {
        "count": 10,
        "department": "sales",
        "designation": "Sales Executive",
        "salary_grade": "J1",
        "base_target": 25000,
        "store_id": "assigned"
    },
    "customer_service": {
        "count": 5,
        "department": "customer_service",
        "designation": "Customer Service Representative",
        "salary_grade": "J2",
        "base_target": 15000,
        "store_id": "assigned"
    },
    "cashier": {
        "count": 2,
        "department": "sales",
        "designation": "Senior Cashier",
        "salary_grade": "J2",
        "base_target": 20000,
        "store_id": "assigned"
    },
    "analyst": {
        "count": 2,
        "department": "finance",
        "designation": "Business Analyst",
        "salary_grade": "S2",
        "base_target": 0,
        "store_id": None
    }
}

# Store mapping
STORES = [
    {"id": 1, "name": "Meridian Hypermarket Al Barsha", "location": "Dubai", "region_id": 1},
    {"id": 2, "name": "Meridian Hypermarket Deira City Centre", "location": "Dubai", "region_id": 1},
    {"id": 3, "name": "Meridian Hypermarket Karama", "location": "Dubai", "region_id": 1},
    {"id": 4, "name": "Meridian Hypermarket Mushrif Mall", "location": "Abu Dhabi", "region_id": 2},
    {"id": 5, "name": "Meridian Hypermarket Al Wahda", "location": "Abu Dhabi", "region_id": 2},
    {"id": 6, "name": "Meridian Hypermarket Khalidiyah", "location": "Abu Dhabi", "region_id": 2},
    {"id": 7, "name": "Meridian Hypermarket Sharjah City Centre", "location": "Sharjah", "region_id": 3},
    {"id": 8, "name": "Meridian Hypermarket Al Nahda", "location": "Sharjah", "region_id": 3},
    {"id": 9, "name": "Meridian Hypermarket Ajman", "location": "Ajman", "region_id": 3},
    {"id": 10, "name": "Meridian Hypermarket Ras Al Khaimah", "location": "Ras Al Khaimah", "region_id": 3}
]

REGION_PREFIXES = {
    "Dubai": "DXB",
    "Abu Dhabi": "AUH",
    "Sharjah": "SHJ",
    "Ajman": "AJM",
    "Ras Al Khaimah": "RAK"
}


def get_weighted_nationality():
    """Get nationality based on UAE workforce demographics"""
    total = sum(w for _, w in NATIONALITIES)
    r = random.randint(1, total)
    cumulative = 0
    for nat, weight in NATIONALITIES:
        cumulative += weight
        if r <= cumulative:
            return nat
    return "Indian"


def generate_employee_code(index: int, store: dict = None) -> str:
    """Generate employee code like LLU-DXB-0001"""
    if store:
        prefix = REGION_PREFIXES.get(store["location"], "UAE")
    else:
        prefix = "HQ"
    return f"LLU-{prefix}-{index:04d}"


def generate_phone():
    """Generate UAE phone number"""
    prefixes = ["050", "052", "055", "056", "058"]
    return f"+971-{random.choice(prefixes)}-{random.randint(1000000, 9999999)}"


def generate_email(first_name: str, last_name: str, domain: str = "retaildemo.app") -> str:
    """Generate corporate email"""
    first = first_name.lower().replace(" ", "")
    last = last_name.lower().replace(" ", "").replace("-", "")
    suffix = random.randint(1, 99) if random.random() < 0.3 else ""
    return f"{first}.{last}{suffix}@{domain}"


def generate_date_of_birth(min_age: int = 22, max_age: int = 55) -> date:
    """Generate realistic date of birth"""
    today = date.today()
    age = random.randint(min_age, max_age)
    dob = date(today.year - age, random.randint(1, 12), random.randint(1, 28))
    return dob


def generate_date_of_joining(role: str) -> date:
    """Generate date of joining based on role seniority"""
    today = date.today()
    
    # Senior roles joined earlier
    if role in ["super_admin", "regional_manager"]:
        min_years, max_years = 3, 8
    elif role in ["store_manager", "inventory_manager"]:
        min_years, max_years = 2, 6
    elif role == "analyst":
        min_years, max_years = 1, 4
    else:
        min_years, max_years = 0.25, 5  # 3 months to 5 years
    
    days_ago = random.randint(int(min_years * 365), int(max_years * 365))
    return today - timedelta(days=days_ago)


def generate_employees() -> list:
    """Generate all synthetic employees"""
    employees = []
    emp_index = 1
    
    # Track store managers for reporting structure
    store_managers = {}
    regional_managers = []
    coo = None
    
    # Generate employees by role
    for role, config in ROLE_CONFIG.items():
        for i in range(config["count"]):
            # Select name
            is_female = random.random() < 0.50  # Balanced gender distribution
            first_name = random.choice(FIRST_NAMES_FEMALE if is_female else FIRST_NAMES_MALE)
            last_name = random.choice(LAST_NAMES)
            
            # Assign store - distribute across 10 stores
            if config["store_id"] == "assigned":
                store_idx = i % 10
                store = STORES[store_idx]
            elif role == "store_manager":
                store = STORES[i % 10]  # Each manager gets a store (up to 10)
            else:
                store = None
            
            # Generate employee data
            date_of_joining = generate_date_of_joining(role)
            
            # 5% chance of resignation for non-management roles
            date_of_resignation = None
            status = "active"
            if role in ["sales_executive", "customer_service"] and random.random() < 0.05:
                if date_of_joining < date.today() - timedelta(days=180):
                    date_of_resignation = date_of_joining + timedelta(days=random.randint(180, 730))
                    if date_of_resignation > date.today():
                        date_of_resignation = None
                    else:
                        status = "terminated"
            
            employee = {
                "employee_code": generate_employee_code(emp_index, store),
                "first_name": first_name,
                "last_name": last_name,
                "email": generate_email(first_name, last_name),
                "phone": generate_phone(),
                "date_of_birth": generate_date_of_birth(),
                "gender": "Female" if is_female else "Male",
                "nationality": get_weighted_nationality(),
                "date_of_joining": date_of_joining,
                "date_of_resignation": date_of_resignation,
                "role": role,
                "department": config["department"],
                "designation": config["designation"],
                "store_id": store["id"] if store else None,
                "region_id": store["region_id"] if store else None,
                "status": status,
                "salary_grade": config["salary_grade"],
                "reports_to_id": None,  # Set later
                "base_target": config["base_target"]
            }
            
            employees.append(employee)
            
            # Track for hierarchy
            if role == "super_admin":
                coo = emp_index
            elif role == "regional_manager":
                regional_managers.append(emp_index)
            elif role == "store_manager":
                store_managers[store["id"]] = emp_index
            
            emp_index += 1
    
    # Set reporting structure
    for i, emp in enumerate(employees):
        idx = i + 1  # 1-based index
        
        if emp["role"] == "super_admin":
            emp["reports_to_id"] = None
        elif emp["role"] == "regional_manager":
            emp["reports_to_id"] = coo
        elif emp["role"] == "store_manager":
            # Report to regional manager based on region
            region_id = emp["region_id"]
            if region_id and regional_managers:
                rm_idx = (region_id - 1) % len(regional_managers)
                emp["reports_to_id"] = regional_managers[rm_idx]
        elif emp["role"] == "analyst":
            emp["reports_to_id"] = coo
        else:
            # Report to store manager
            if emp["store_id"] and emp["store_id"] in store_managers:
                emp["reports_to_id"] = store_managers[emp["store_id"]]
    
    return employees


def generate_performance_data(employees: list, months: int = 6) -> list:
    """Generate performance records for each employee"""
    performance_records = []
    today = date.today()
    
    for emp in employees:
        if emp["status"] == "terminated" and emp["date_of_resignation"]:
            # Don't generate performance after resignation
            end_date = emp["date_of_resignation"]
        else:
            end_date = today
        
        # Generate monthly performance for last N months
        for month_offset in range(months):
            period_end = date(
                (today.year if today.month - month_offset > 0 else today.year - 1),
                ((today.month - month_offset - 1) % 12) + 1,
                28
            )
            period_start = period_end.replace(day=1)
            
            # Skip if before joining or after resignation
            if period_start < emp["date_of_joining"]:
                continue
            if emp["date_of_resignation"] and period_end > emp["date_of_resignation"]:
                continue
            
            # Generate performance metrics
            base_target = emp["base_target"]
            
            # Performance varies by role
            if emp["role"] in ["super_admin", "analyst"]:
                # Non-sales roles
                sales_target = 0
                sales_achieved = 0
                transactions_count = random.randint(0, 10)
            else:
                # Sales-related roles
                sales_target = base_target * (0.9 + random.random() * 0.2)  # ±10% target variation
                
                # Achievement depends on random performance + some seasonality
                month_factor = 1.0 + 0.1 * (1 if period_end.month in [11, 12, 1] else -0.1)  # Holiday boost
                performance_factor = random.gauss(1.0, 0.15)  # Normal distribution around 100%
                performance_factor = max(0.5, min(1.5, performance_factor))  # Clamp to 50%-150%
                
                sales_achieved = sales_target * performance_factor * month_factor
                transactions_count = int(sales_achieved / random.uniform(50, 200))  # Avg transaction value
            
            # Returns (5-15% of transactions)
            returns_count = int(transactions_count * random.uniform(0.05, 0.15))
            
            # Customer rating (3.5 to 5.0, higher for experienced employees)
            tenure_months = (period_end - emp["date_of_joining"]).days / 30
            base_rating = 3.5 + min(tenure_months / 24, 1.0)  # Improves with tenure
            customer_rating = min(5.0, base_rating + random.uniform(-0.3, 0.5))
            
            # Attendance (85-100%)
            days_in_month = 26  # Working days
            days_absent = random.randint(0, 4)
            days_late = random.randint(0, 3)
            days_present = days_in_month - days_absent
            attendance_percentage = (days_present / days_in_month) * 100
            
            # Calculate performance score
            # Weights: Sales 40%, Customer Rating 25%, Attendance 25%, Low Returns 10%
            if sales_target > 0:
                sales_pct = min(sales_achieved / sales_target * 100, 150)
            else:
                sales_pct = 100  # Non-sales roles get full sales score
            
            return_rate = (returns_count / max(transactions_count, 1)) * 100
            
            score = (
                (sales_pct / 150 * 40) +
                (customer_rating / 5 * 25) +
                (attendance_percentage / 100 * 25) +
                ((100 - min(return_rate, 100)) / 100 * 10)
            )
            
            # Grade
            if score >= 95: grade = "A+"
            elif score >= 90: grade = "A"
            elif score >= 85: grade = "B+"
            elif score >= 80: grade = "B"
            elif score >= 70: grade = "C"
            elif score >= 60: grade = "D"
            else: grade = "F"
            
            performance_records.append({
                "employee_code": emp["employee_code"],
                "period_type": "monthly",
                "period_start": period_start,
                "period_end": period_end,
                "sales_target": round(sales_target, 2),
                "sales_achieved": round(sales_achieved, 2),
                "transactions_count": transactions_count,
                "returns_count": returns_count,
                "voids_count": random.randint(0, 5),
                "avg_transaction_value": round(sales_achieved / max(transactions_count, 1), 2),
                "items_sold": transactions_count * random.randint(2, 8),
                "customers_served": int(transactions_count * 0.9),
                "customer_rating": round(customer_rating, 2),
                "complaints_received": random.randint(0, 3),
                "compliments_received": random.randint(0, 10),
                "days_present": days_present,
                "days_absent": days_absent,
                "days_late": days_late,
                "overtime_hours": round(random.uniform(0, 20), 2),
                "attendance_percentage": round(attendance_percentage, 2),
                "performance_score": round(score, 2),
                "performance_grade": grade
            })
    
    return performance_records


def generate_transactions(employees: list, days: int = 30) -> list:
    """Generate transaction records attributed to employees"""
    transactions = []
    today = date.today()
    
    # Only sales-related employees make transactions
    sales_employees = [e for e in employees if e["role"] in ["sales_executive", "customer_service", "store_manager", "inventory_manager", "cashier"] and e["status"] == "active"]
    
    for day_offset in range(days):
        transaction_date = today - timedelta(days=day_offset)
        
        for emp in sales_employees:
            if transaction_date < emp["date_of_joining"]:
                continue
            
            # Number of transactions per day varies by role
            if emp["role"] == "store_manager":
                num_transactions = random.randint(5, 15)
            elif emp["role"] == "sales_executive":
                num_transactions = random.randint(20, 50)
            elif emp["role"] == "cashier":
                num_transactions = random.randint(25, 60)
            else:
                num_transactions = random.randint(10, 30)
            
            for t in range(num_transactions):
                # Transaction time (store hours 9 AM - 11 PM)
                hour = random.randint(9, 22)
                minute = random.randint(0, 59)
                second = random.randint(0, 59)
                
                # Transaction type (90% sales, 8% returns, 2% voids)
                rand = random.random()
                if rand < 0.90:
                    txn_type = "sale"
                    gross_amount = random.uniform(20, 500)
                    discount = gross_amount * random.uniform(0, 0.15)
                elif rand < 0.98:
                    txn_type = "return"
                    gross_amount = -random.uniform(20, 200)
                    discount = 0
                else:
                    txn_type = "void"
                    gross_amount = 0
                    discount = 0
                
                net_amount = gross_amount - discount
                
                transaction = {
                    "transaction_code": f"TXN-{transaction_date.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}",
                    "employee_code": emp["employee_code"],
                    "transaction_type": txn_type,
                    "transaction_date": transaction_date,
                    "transaction_time": f"{hour:02d}:{minute:02d}:{second:02d}",
                    "gross_amount": round(abs(gross_amount), 2),
                    "discount_amount": round(discount, 2),
                    "net_amount": round(net_amount, 2),
                    "items_count": random.randint(1, 15),
                    "store_id": emp["store_id"],
                    "register_id": f"REG-{random.randint(1, 10):02d}",
                    "payment_method": random.choice(["cash", "card", "mobile"]),
                    "is_completed": txn_type != "void",
                    "is_voided": txn_type == "void"
                }
                
                transactions.append(transaction)
    
    return transactions


def generate_sql_inserts():
    """Generate SQL INSERT statements for all synthetic data"""
    employees = generate_employees()
    performance = generate_performance_data(employees)
    transactions = generate_transactions(employees, days=30)
    
    sql_statements = []
    
    # Employees INSERT
    sql_statements.append("-- =============================================================================")
    sql_statements.append("-- SYNTHETIC EMPLOYEE DATA")
    sql_statements.append("-- Generated: " + datetime.now().isoformat())
    sql_statements.append("-- =============================================================================\n")
    
    sql_statements.append("-- Clear existing data (optional - comment out in production)")
    sql_statements.append("-- TRUNCATE employee_transactions, employee_performance, employee_attendance, employee_certifications, employees RESTART IDENTITY CASCADE;\n")
    
    sql_statements.append("-- Insert Employees")
    for emp in employees:
        sql_statements.append(f"""INSERT INTO employees (
    employee_code, first_name, last_name, email, phone,
    date_of_birth, gender, nationality, date_of_joining, date_of_resignation,
    role, department, designation, store_id, region_id,
    status, salary_grade, reports_to
) VALUES (
    '{emp["employee_code"]}', '{emp["first_name"]}', '{emp["last_name"]}', '{emp["email"]}', '{emp["phone"]}',
    '{emp["date_of_birth"]}', '{emp["gender"]}', '{emp["nationality"]}', '{emp["date_of_joining"]}', {f"'{emp['date_of_resignation']}'" if emp["date_of_resignation"] else "NULL"},
    '{emp["role"]}', '{emp["department"]}', '{emp["designation"]}', {emp["store_id"] if emp["store_id"] else "NULL"}, {emp["region_id"] if emp["region_id"] else "NULL"},
    '{emp["status"]}', '{emp["salary_grade"]}', {emp["reports_to_id"] if emp["reports_to_id"] else "NULL"}
) ON CONFLICT (employee_code) DO NOTHING;""")
    
    sql_statements.append("\n-- Insert Performance Records")
    for perf in performance[:500]:  # Limit for readability
        emp = next((e for e in employees if e["employee_code"] == perf["employee_code"]), None)
        if not emp:
            continue
        emp_idx = employees.index(emp) + 1
        
        sql_statements.append(f"""INSERT INTO employee_performance (
    employee_id, period_type, period_start, period_end,
    sales_target, sales_achieved, transactions_count, returns_count, voids_count,
    avg_transaction_value, items_sold, customers_served, customer_rating,
    complaints_received, compliments_received, days_present, days_absent, days_late,
    overtime_hours, attendance_percentage, performance_score, performance_grade
) VALUES (
    {emp_idx}, '{perf["period_type"]}', '{perf["period_start"]}', '{perf["period_end"]}',
    {perf["sales_target"]}, {perf["sales_achieved"]}, {perf["transactions_count"]}, {perf["returns_count"]}, {perf["voids_count"]},
    {perf["avg_transaction_value"]}, {perf["items_sold"]}, {perf["customers_served"]}, {perf["customer_rating"]},
    {perf["complaints_received"]}, {perf["compliments_received"]}, {perf["days_present"]}, {perf["days_absent"]}, {perf["days_late"]},
    {perf["overtime_hours"]}, {perf["attendance_percentage"]}, {perf["performance_score"]}, '{perf["performance_grade"]}'
) ON CONFLICT (employee_id, period_type, period_start) DO NOTHING;""")
    
    return "\n".join(sql_statements), employees, performance, transactions


if __name__ == "__main__":
    # Generate and print SQL
    sql, employees, performance, transactions = generate_sql_inserts()
    print(f"Generated {len(employees)} employees")
    print(f"Generated {len(performance)} performance records")
    print(f"Generated {len(transactions)} transactions")
    
    # Save to file
    with open("synthetic_employee_data.sql", "w") as f:
        f.write(sql)
    print("SQL saved to synthetic_employee_data.sql")
