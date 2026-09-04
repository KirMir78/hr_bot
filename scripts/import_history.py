import sqlite3
import os
import glob
import shutil
import re
import pandas as pd

DATA_DIR = os.environ.get("DATA_DIR", "/opt/hr-agent/data")
DB_PATH = os.path.join(DATA_DIR, "schedule.db")
TMP_DIR = os.path.join(DATA_DIR, "tmp")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
HISTORY_YEAR = 2024  # Год для исторических данных

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def ensure_dirs():
    os.makedirs(TMP_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

def seed_dicts(conn):
    """Проверка и создание справочников"""
    cursor = conn.cursor()
    
    # Stores
    cursor.execute("INSERT OR IGNORE INTO stores (format, store_code, address, work_mode, open_time, close_time, manager) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   ('white_store', '5607М', 'СПб, Орджоникидзе пр-т 19к1', '24h', '09:00', '23:00', 'Марочкин К.В.'))
    
    # Roles
    roles = [("Старший продавец",), ("Продавец-кассир",), ("Охранник",), ("Сборщик",)]
    for r in roles:
        cursor.execute("INSERT OR IGNORE INTO roles (name) VALUES (?)", r)

    # Patterns
    patterns = [("2/2", 2, 2), ("3/3", 3, 3), ("4/2", 4, 2), ("5/2", 5, 2)]
    for p in patterns:
        cursor.execute("INSERT OR IGNORE INTO work_patterns (name, work_days, rest_days) VALUES (?, ?, ?)", p)

    conn.commit()

def get_or_create_employee(cursor, fio, contract_raw):
    """Создает или возвращает ID сотрудника"""
    parts = fio.split()
    last_name = parts[0] if len(parts) > 0 else "Unknown"
    first_name = parts[1] if len(parts) > 1 else "Unknown"
    middle_name = parts[2] if len(parts) > 2 else ""

    # Нормализуем тип договора для БД: 'ТД' или 'аутсорсинг'
    contract_norm = 'аутсорсинг' if 'аутсорсинг' in contract_raw.lower() else 'ТД'

    cursor.execute("SELECT id FROM employees WHERE last_name=? AND first_name=? AND middle_name=?", 
                   (last_name, first_name, middle_name))
    row = cursor.fetchone()
    if row:
        return row[0]

    # Определяем роль: Аутсорсинг -> Охранник, ТД -> Продавец-кассир (для MVP)
    role_name = "Охранник" if contract_norm == "аутсорсинг" else "Продавец-кассир"
    cursor.execute("SELECT id FROM roles WHERE name=?", (role_name,))
    role_row = cursor.fetchone()
    role_id = role_row[0] if role_row else None

    cursor.execute("SELECT id FROM work_patterns WHERE name='2/2'")
    pattern_row = cursor.fetchone()
    pattern_id = pattern_row[0] if pattern_row else None

    cursor.execute("""
        INSERT INTO employees (store_code, last_name, first_name, middle_name, gender, primary_role_id, preferred_pattern_id, contract_type, rate, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ('5607М', last_name, first_name, middle_name, 'Unknown', role_id, pattern_id, contract_norm, 1.0, 1))
    return cursor.lastrowid

def parse_excel_history(conn):
    # Возвращаем файл из архива, если он там (для повторного запуска)
    archived_files = glob.glob(os.path.join(ARCHIVE_DIR, "*График*выходов*.xlsx"))
    for f in archived_files:
        shutil.move(f, os.path.join(TMP_DIR, os.path.basename(f)))

    excel_files = glob.glob(os.path.join(TMP_DIR, "*График*выходов*.xlsx"))
    if not excel_files:
        print("⚠️ Файл Excel не найден в tmp или archive.")
        return

    cursor = conn.cursor()
    file_path = excel_files[0]
    print(f"📂 Парсим факт из: {os.path.basename(file_path)} (год: {HISTORY_YEAR})")

    try:
        df = pd.read_excel(file_path, header=None)
        headers = df.iloc[0]
        
        # Ищем колонки с датами (ДД.ММ)
        date_cols = {}
        for idx, val in headers.items():
            if isinstance(val, str) and re.match(r'\d{2}\.\d{2}', val):
                date_cols[idx] = val
        
        print(f"Найдено колонок с датами: {len(date_cols)}")
        imported_shifts = 0

        for index, row in df.iterrows():
            if index == 0: continue
            
            fio = str(row[0]).strip()
            contract_raw = str(row[1]).strip()
            
            if not fio or fio == 'nan': continue

            employee_id = get_or_create_employee(cursor, fio, contract_raw)

            for col_idx, date_str in date_cols.items():
                cell_val = row[col_idx]
                if pd.isna(cell_val) or str(cell_val).strip() == '':
                    continue
                
                cell_str = str(cell_val).strip()
                try:
                    day, month = map(int, date_str.split('.'))
                    shift_date = f"{HISTORY_YEAR}-{month:02d}-{day:02d}"
                except:
                    continue

                # Парсим смену: "15 ч. (07:31-22:18)"
                match = re.search(r'(\d+)\s*ч\.\s*\((\d{2}:\d{2})-(\d{2}:\d{2})\)', cell_str)
                if match:
                    hours = float(match.group(1))
                    start_time = match.group(2)
                    end_time = match.group(3)
                    status = 'worked'
                    
                    cursor.execute("""
                        INSERT INTO shifts_history (store_code, employee_id, date, start_time, end_time, hours, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, ('5607М', employee_id, shift_date, start_time, end_time, hours, status))
                    imported_shifts += 1
                else:
                    # Маркеры: Б, ОТ, НН
                    status = cell_str
                    cursor.execute("""
                        INSERT INTO shifts_history (store_code, employee_id, date, start_time, end_time, hours, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, ('5607М', employee_id, shift_date, None, None, 0, status))
                    imported_shifts += 1

        conn.commit()
        print(f"✅ Импортировано записей: {imported_shifts}.")
        
        # Переносим файл в архив
        shutil.move(file_path, os.path.join(ARCHIVE_DIR, os.path.basename(file_path)))
        print(f"📁 Файл перемещен в архив.")

    except Exception as e:
        print(f"❌ Ошибка парсинга Excel: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🚀 Запуск импорта фактических данных...")
    ensure_dirs()
    conn = get_db()
    seed_dicts(conn)
    parse_excel_history(conn)
    conn.close()
    print("🏁 Импорт завершен.")
