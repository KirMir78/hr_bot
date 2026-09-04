import sqlite3
import os

# Путь к данным берем из переменной окружения или используем дефолтный
DATA_DIR = os.environ.get("DATA_DIR", "/opt/hr-agent/data")
DB_PATH = os.path.join(DATA_DIR, "schedule.db")

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.executescript("""
    -- 1. Справочник торговых точек (Stores)
    CREATE TABLE IF NOT EXISTS stores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        format TEXT CHECK(format IN ('white_store', 'dark_store')),
        store_code TEXT UNIQUE NOT NULL,
        address TEXT,
        work_mode TEXT CHECK(work_mode IN ('day', '24h')),
        open_time TEXT,
        close_time TEXT,
        manager TEXT
    );

    -- 2. Справочник ролей (Roles)
    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    );

    -- 3. Шаблоны укомплектованности (Staffing Templates)
    CREATE TABLE IF NOT EXISTS staffing_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        format TEXT,
        work_mode TEXT,
        role_id INTEGER,
        count_per_day INTEGER,
        shift_start TEXT,
        shift_end TEXT,
        FOREIGN KEY (role_id) REFERENCES roles(id)
    );

    -- 4. Паттерны графиков (Work Patterns)
    CREATE TABLE IF NOT EXISTS work_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        work_days INTEGER,
        rest_days INTEGER
    );

    -- 5. Сотрудники (Employees)
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_code TEXT,
        last_name TEXT NOT NULL,
        first_name TEXT NOT NULL,
        middle_name TEXT,
        gender TEXT,
        primary_role_id INTEGER,
        preferred_pattern_id INTEGER,
        contract_type TEXT CHECK(contract_type IN ('ТД', 'аутсорсинг')),
        rate REAL DEFAULT 1.0,
        is_active BOOLEAN DEFAULT 1,
        is_on_vacation BOOLEAN DEFAULT 0,
        is_on_sick_leave BOOLEAN DEFAULT 0,
        FOREIGN KEY (store_code) REFERENCES stores(store_code),
        FOREIGN KEY (primary_role_id) REFERENCES roles(id),
        FOREIGN KEY (preferred_pattern_id) REFERENCES work_patterns(id)
    );

    -- 6. Планы графиков (Plans - планировочный слой)
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_code TEXT,
        period_start DATE,
        period_end DATE,
        strategy TEXT CHECK(strategy IN ('A', 'B')),
        status TEXT CHECK(status IN ('draft', 'published')) DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (store_code) REFERENCES stores(store_code)
    );

    -- 7. Запланированные смены (Shifts Planned)
    CREATE TABLE IF NOT EXISTS shifts_planned (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER,
        employee_id INTEGER,
        date DATE,
        start_time TEXT,
        end_time TEXT,
        hours REAL,
        status TEXT,
        FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
        FOREIGN KEY (employee_id) REFERENCES employees(id)
    );

    -- 8. История фактических смен (Shifts History - исторический слой)
    CREATE TABLE IF NOT EXISTS shifts_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_code TEXT,
        employee_id INTEGER,
        date DATE,
        start_time TEXT,
        end_time TEXT,
        hours REAL,
        status TEXT,
        FOREIGN KEY (store_code) REFERENCES stores(store_code),
        FOREIGN KEY (employee_id) REFERENCES employees(id)
    );
    """)

    conn.commit()
    conn.close()
    print(f"✅ База данных успешно инициализирована: {DB_PATH}")

if __name__ == "__main__":
    init_db()
