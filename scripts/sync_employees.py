#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import sqlite3
import sys
from pathlib import Path

CSV_PATH = Path("/opt/hr-agent/data/1_inbox/employees.csv")
DB_PATH = Path("/opt/hr-agent/data/schedule.db")
ENCODING = "windows-1251"

def parse_full_name(full_name):
    parts = full_name.strip().split()
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        return parts[0], parts[1], None
    else:
        return full_name, None, None

def main():
    if not CSV_PATH.exists():
        print(f"❌ CSV не найден: {CSV_PATH}", file=sys.stderr)
        return 1
    if not DB_PATH.exists():
        print(f"❌ База данных не найдена: {DB_PATH}", file=sys.stderr)
        return 1

    # 1. Читаем CSV
    try:
        with open(CSV_PATH, 'r', encoding=ENCODING) as f:
            reader = csv.reader(f)
            header = next(reader)
            col_map = {col.strip(): idx for idx, col in enumerate(header)}
            required_cols = ['Имя', 'Табельный номер', 'Основная роль', 'Договор',
                             'Формат торговой точки', 'Торговая дочка', 'Город']
            for col in required_cols:
                if col not in col_map:
                    print(f"❌ В CSV нет колонки: {col}", file=sys.stderr)
                    return 1
            rows = list(reader)
        print(f"✅ Прочитано {len(rows)} записей из CSV")
    except Exception as e:
        print(f"❌ Ошибка чтения CSV: {e}", file=sys.stderr)
        return 1

    # 2. Подключаемся к БД
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 3. Получаем уникальные магазины из CSV
    stores_from_csv = set()
    for row in rows:
        store = row[col_map['Торговая дочка']].strip()
        if store:
            stores_from_csv.add(store)

    # 4. Очищаем employees (чтобы можно было удалять магазины)
    cursor.execute("DELETE FROM employees")
    print("🧹 Таблица employees очищена")

    # 5. Удаляем магазины, которых нет в CSV
    cursor.execute("SELECT store_code FROM stores")
    existing_stores = {row[0] for row in cursor.fetchall()}

    for code in existing_stores:
        if code not in stores_from_csv:
            cursor.execute("DELETE FROM stores WHERE store_code = ?", (code,))
            print(f"🗑️ Удалён магазин: {code}")
    conn.commit()

    # 6. Добавляем магазины из CSV, если их ещё нет
    cursor.execute("SELECT store_code FROM stores")
    existing_stores_after = {row[0] for row in cursor.fetchall()}
    for code in stores_from_csv:
        if code not in existing_stores_after:
            cursor.execute("INSERT INTO stores (store_code) VALUES (?)", (code,))
            print(f"➕ Добавлен магазин: {code}")
    conn.commit()

    # 7. Добавляем недостающие роли (как раньше)
    roles_from_csv = set()
    for row in rows:
        role = row[col_map['Основная роль']].strip()
        if role:
            roles_from_csv.add(role)

    cursor.execute("SELECT id, name FROM roles")
    existing_roles = {row[1]: row[0] for row in cursor.fetchall()}

    for role_name in roles_from_csv:
        if role_name not in existing_roles:
            cursor.execute("INSERT INTO roles (name) VALUES (?)", (role_name,))
            print(f"➕ Добавлена роль: {role_name}")
    conn.commit()

    cursor.execute("SELECT id, name FROM roles")
    roles_map = {row[1]: row[0] for row in cursor.fetchall()}

    # 8. Формируем записи для employees
    records = []
    for row in rows:
        full_name = row[col_map['Имя']].strip()
        last_name, first_name, middle_name = parse_full_name(full_name)

        store_code = row[col_map['Торговая дочка']].strip()
        role_name = row[col_map['Основная роль']].strip()
        primary_role_id = roles_map.get(role_name)

        contract = row[col_map['Договор']].strip()
        if contract == 'ТД':
            contract_type = 'ТД'
        elif contract.lower() == 'аутсорсинг':
            contract_type = 'аутсорсинг'
        else:
            contract_type = None

        gender = 'Unknown'
        preferred_pattern_id = None
        rate = 1.0
        is_active = 1
        is_on_vacation = 0
        is_on_sick_leave = 0

        records.append((
            store_code,
            last_name,
            first_name,
            middle_name,
            gender,
            primary_role_id,
            preferred_pattern_id,
            contract_type,
            rate,
            is_active,
            is_on_vacation,
            is_on_sick_leave
        ))

    # 9. Вставляем сотрудников
    cursor.executemany("""
        INSERT INTO employees (
            store_code, last_name, first_name, middle_name,
            gender, primary_role_id, preferred_pattern_id,
            contract_type, rate, is_active, is_on_vacation, is_on_sick_leave
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    print(f"✅ Вставлено {len(records)} записей в employees")

    # 10. Проверка
    cursor.execute("SELECT store_code, COUNT(*) FROM employees GROUP BY store_code")
    print("\n📊 Итоговое распределение по магазинам:")
    for code, cnt in cursor.fetchall():
        print(f"   {code}: {cnt}")

    cursor.execute("SELECT store_code FROM stores")
    print("\n🏬 Актуальные магазины в stores:")
    for (code,) in cursor.fetchall():
        print(f"   {code}")

    conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
