import sqlite3
import os

DATA_DIR = os.environ.get("DATA_DIR", "/opt/hr-agent/data")
DB_PATH = os.path.join(DATA_DIR, "schedule.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def save_plan(store_code, period_start, period_end, strategy, shifts_data):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO plans (store_code, period_start, period_end, strategy, status)
        VALUES (?, ?, ?, ?, 'draft')
    """, (store_code, period_start, period_end, strategy))
    
    plan_id = cursor.lastrowid
    
    for shift in shifts_data:
        cursor.execute("""
            INSERT INTO shifts_planned (plan_id, employee_id, date, start_time, end_time, hours, status)
            VALUES (?, ?, ?, ?, ?, ?, 'planned')
        """, (plan_id, shift['employee_id'], shift['date'], shift['start_time'], shift['end_time'], shift['hours']))
        
    conn.commit()
    conn.close()
    return plan_id

def get_plan(plan_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM plans WHERE id=?", (plan_id,))
    plan = cursor.fetchone()
    if not plan:
        return None
        
    cursor.execute("""
        SELECT sp.*, e.last_name, e.first_name, e.middle_name, r.name as role_name
        FROM shifts_planned sp
        JOIN employees e ON sp.employee_id = e.id
        LEFT JOIN roles r ON e.primary_role_id = r.id
        WHERE sp.plan_id=?
        ORDER BY sp.date, sp.start_time
    """, (plan_id,))
    shifts = cursor.fetchall()
    
    return {
        "plan": dict(plan),
        "shifts": [dict(s) for s in shifts]
    }

def publish_plan(plan_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE plans SET status='published' WHERE id=?", (plan_id,))
    conn.commit()
    conn.close()

def update_shift(shift_id, new_date, new_start, new_end, new_hours):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE shifts_planned SET date=?, start_time=?, end_time=?, hours=? WHERE id=?
    """, (new_date, new_start, new_end, new_hours, shift_id))
    conn.commit()
    conn.close()

def get_store_by_code(store_code: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stores WHERE store_code=?", (store_code,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_store_by_id(store_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stores WHERE id=?", (store_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_all_stores():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, store_code, format, work_mode FROM stores ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_employees(store_code=None):
    conn = get_db()
    cursor = conn.cursor()
    base_query = """
        SELECT e.id, e.store_code, e.last_name, e.first_name, e.middle_name, e.gender,
               e.primary_role_id, r.name AS role_name,
               e.contract_type, e.rate, e.is_active,
               e.is_on_vacation, e.is_on_sick_leave
        FROM employees e
        LEFT JOIN roles r ON e.primary_role_id = r.id
    """
    if store_code:
        cursor.execute(base_query + " WHERE e.store_code = ? ORDER BY e.last_name, e.first_name", (store_code,))
    else:
        cursor.execute(base_query + " ORDER BY e.last_name, e.first_name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
