from ortools.sat.python import cp_model
import sqlite3
from datetime import datetime, timedelta
import os

DATA_DIR = os.environ.get("DATA_DIR", "/opt/hr-agent/data")
DB_PATH = os.path.join(DATA_DIR, "schedule.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def calculate_hours(start_time, end_time):
    """Расчет длительности смены с учетом перехода через полночь"""
    fmt = "%H:%M"
    start = datetime.strptime(start_time, fmt)
    end = datetime.strptime(end_time, fmt)
    if end <= start:
        end += timedelta(days=1)
    delta = end - start
    return round(delta.total_seconds() / 3600, 2)

from .labor_law import is_night_shift, MAX_HOURS_PER_WEEK, MAX_CONSECUTIVE_SHIFTS
from .staffing_rules import get_required_slots

def generate_schedule(store_code, start_date_str, days=14, strategy='A'):
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Загружаем магазин
    cursor.execute("SELECT * FROM stores WHERE store_code=?", (store_code,))
    store = cursor.fetchone()
    if not store:
        return {"status": "error", "message": f"Магазин {store_code} не найден"}
        
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    
    # 2. Требования по потребности теперь считаются по каждой дате отдельно
    # (для dark_store из прогноза заказов, для остальных из staffing_templates)
    
    # 3. Загружаем активных сотрудников
    cursor.execute("""
        SELECT e.*, r.name as role_name 
        FROM employees e 
        LEFT JOIN roles r ON e.primary_role_id = r.id 
        WHERE e.store_code=? AND e.is_active=1 AND e.is_on_vacation=0 AND e.is_on_sick_leave=0
    """, (store_code,))
    employees = cursor.fetchall()
    
    if not employees:
        return {"status": "error", "message": "Нет доступных сотрудников для планирования"}

    # 4. Генерируем слоты (потребность)
    slots = []
    slot_id = 0
    for d in range(days):
        current_date = start_date + timedelta(days=d)
        date_str = current_date.strftime("%Y-%m-%d")
        day_requirements = get_required_slots(cursor, store_code, store['format'], store['work_mode'], date_str)
        
        for t in day_requirements:
            for _ in range(t['count_per_day']):
                slots.append({
                    'id': slot_id,
                    'date': date_str,
                    'role_id': t['role_id'],
                    'start_time': t['shift_start'],
                    'end_time': t['shift_end'],
                    'hours': calculate_hours(t['shift_start'], t['shift_end']),
                    'is_night': is_night_shift(t['shift_start'], t['shift_end'])
                })
                slot_id += 1
    
    # Подгружаем названия ролей для слотов
    role_ids = list(set(s['role_id'] for s in slots))
    if role_ids:
        cursor.execute("SELECT id, name FROM roles WHERE id IN ({})".format(','.join('?'*len(role_ids))), role_ids)
        role_map = {row['id']: row['name'] for row in cursor.fetchall()}
        for s in slots:
            s['role_name'] = role_map.get(s['role_id'])
            
    # 5. Модель CP-SAT
    model = cp_model.CpModel()
    x = {}
    
    for e in employees:
        for s in slots:
            # Блок: Ночь ≠ охранник (если смена ночная, то только Охранник)
            if s['is_night'] and e['role_name'] != 'Охранник':
                continue
            # Блок: Роли должны совпадать
            if e['role_name'] == s['role_name']:
                x[(e['id'], s['id'])] = model.NewBoolVar(f"x_{e['id']}_{s['id']}")
    
    # Ограничение 1: На одну смену не больше одного человека
    for s in slots:
        vars_for_slot = [x[(e['id'], s['id'])] for e in employees if (e['id'], s['id']) in x]
        if vars_for_slot:
            model.AddAtMostOne(vars_for_slot)
            
    # Ограничение 2: Одна смена в день на сотрудника
    dates = sorted(list(set(s['date'] for s in slots)))
    for e in employees:
        for date in dates:
            vars_for_day = [x[(e['id'], s['id'])] for s in slots if s['date'] == date and (e['id'], s['id']) in x]
            if vars_for_day:
                model.AddAtMostOne(vars_for_day)
                
    # Ограничение 3: не больше MAX_CONSECUTIVE_SHIFTS смен подряд
    window_size = MAX_CONSECUTIVE_SHIFTS + 1
    for e in employees:
        for i in range(len(dates) - MAX_CONSECUTIVE_SHIFTS):
            window = dates[i:i + window_size]
            vars_window = []
            for date in window:
                vars_window.extend([x[(e['id'], s['id'])] for s in slots if s['date'] == date and (e['id'], s['id']) in x])
            if vars_window:
                model.Add(sum(vars_window) <= MAX_CONSECUTIVE_SHIFTS)
                
    # Целевая функция
    assigned_vars = list(x.values())
    coverage_weight = 1000
    
    if strategy == 'A':
        # Стратегия А: Максимизировать покрытие, минимизировать аутсорсинг
        outsourcing_penalty = 10
        obj_terms = [coverage_weight * v for v in assigned_vars]
        outsourcing_vars = [x[(e['id'], s['id'])] for e in employees if e['contract_type'] == 'аутсорсинг' for s in slots if (e['id'], s['id']) in x]
        obj_terms.extend([-outsourcing_penalty * v for v in outsourcing_vars])
        model.Maximize(sum(obj_terms))
    else:
        # Стратегия Б: Просто максимизируем покрытие (позже добавим выравнивание)
        model.Maximize(sum(assigned_vars))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        planned_shifts = []
        warnings = []
        
        for e in employees:
            e_hours = 0
            for s in slots:
                if (e['id'], s['id']) in x and solver.Value(x[(e['id'], s['id'])]) == 1:
                    planned_shifts.append({
                        'employee_id': e['id'],
                        'employee_name': f"{e['last_name']} {e['first_name']}",
                        'date': s['date'],
                        'start_time': s['start_time'],
                        'end_time': s['end_time'],
                        'hours': s['hours'],
                        'role_name': s['role_name']
                    })
                    e_hours += s['hours']
            
            if e_hours > MAX_HOURS_PER_WEEK:
                warnings.append(f"Сотрудник {e['last_name']} {e['first_name']} превысил {MAX_HOURS_PER_WEEK} часов в неделю (план: {e_hours} ч)")
                
        covered_slots = sum(1 for s in slots if any((e['id'], s['id']) in x and solver.Value(x[(e['id'], s['id'])]) == 1 for e in employees))
        if covered_slots < len(slots):
            warnings.append(f"Не удалось покрыть все смены: {len(slots) - covered_slots} слотов остались пустыми")
            
        return {
            "status": "success",
            "shifts": planned_shifts,
            "warnings": warnings,
            "total_slots": len(slots),
            "covered_slots": covered_slots
        }
    else:
        return {"status": "error", "message": "Невозможно составить график с текущими ограничениями"}

if __name__ == "__main__":
    # Тестовый запуск
    print("🧪 Тест планировщика...")
    result = generate_schedule('5607М', '2024-08-01', 7, 'A')
    if result['status'] == 'success':
        print(f"✅ Составлено смен: {len(result['shifts'])}")
        print(f"⚠️ Предупреждения: {result['warnings']}")
        for s in result['shifts'][:5]:
            print(f"  {s['date']} {s['employee_name']} ({s['role_name']}) {s['start_time']}-{s['end_time']}")
    else:
        print(f"❌ Ошибка: {result['message']}")

def run_scheduler(store_id: int, date_start: str, date_end: str) -> list:
    """
    Обёртка для generate_schedule, возвращает список смен в формате для save_plan.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT store_code FROM stores WHERE id=?", (store_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Магазин с id {store_id} не найден")
    store_code = row['store_code']
    
    start = datetime.strptime(date_start, "%Y-%m-%d")
    end = datetime.strptime(date_end, "%Y-%m-%d")
    days = (end - start).days + 1  # включительно
    
    result = generate_schedule(store_code, date_start, days, strategy='A')
    if result['status'] != 'success':
        raise RuntimeError(f"Ошибка генерации: {result.get('message', 'неизвестная ошибка')}")
    
    # save_plan уже ожидает эти самые поля (employee_id, date, start_time, end_time, hours) — просто передаём как есть
    shifts = []
    for s in result['shifts']:
        shifts.append({
            'employee_id': s['employee_id'],
            'date': s['date'],
            'start_time': s['start_time'],
            'end_time': s['end_time'],
            'hours': s['hours']
        })
    return shifts
