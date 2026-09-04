"""
Расчёт требуемой численности персонала на смену.

Источники данных:
- staffing_templates (БД) — фиксированные шаблоны, используются для форматов
  вроде white_store, где потребность не зависит от объёма заказов.
- demand_forecast.csv (файл) — для dark_store: потребность рассчитывается
  на основе прогноза объёма заказов/продаж. Пока файла нет — используется
  временный минимальный норматив (заглушка), чтобы система не падала.
"""
import csv
import logging
import os

logger = logging.getLogger(__name__)

DEMAND_FORECAST_PATH = os.environ.get(
    "DEMAND_FORECAST_PATH",
    "/opt/hr-agent/data/1_inbox/demand_forecast.csv"
)

# Временный минимальный норматив, пока нет реального файла прогноза.
FALLBACK_SHIFT_START = "09:00"
FALLBACK_SHIFT_END = "21:00"
FALLBACK_COUNT_PER_ROLE = 1


def get_required_slots_template(cursor, store_format: str, work_mode: str) -> list[dict]:
    """Старая логика: фиксированные шаблоны из staffing_templates.
    Используется для форматов, где потребность не считается по заказам
    (например, white_store)."""
    if work_mode == "24h":
        cursor.execute(
            """
            SELECT * FROM staffing_templates
            WHERE (format=? AND work_mode='day') OR work_mode='24h'
            """,
            (store_format,),
        )
    else:
        cursor.execute(
            "SELECT * FROM staffing_templates WHERE format=? AND work_mode='day'",
            (store_format,),
        )
    return [dict(row) for row in cursor.fetchall()]


def _read_demand_forecast(store_code: str, date_str: str) -> list[dict]:
    """Читает demand_forecast.csv и возвращает строки для конкретного
    магазина и даты. Возвращает [] если файла нет или подходящих строк нет."""
    if not os.path.exists(DEMAND_FORECAST_PATH):
        logger.warning(
            "Файл прогноза заказов не найден: %s. Используется временный норматив.",
            DEMAND_FORECAST_PATH,
        )
        return []

    rows = []
    with open(DEMAND_FORECAST_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("store_code") == store_code and row.get("date") == date_str:
                rows.append(row)
    return rows


def _fallback_slots_for_dark_store(cursor, store_code: str) -> list[dict]:
    """Временный норматив: по 1 человеку на каждую роль, реально
    представленную среди активных сотрудников магазина."""
    cursor.execute(
        """
        SELECT DISTINCT r.id as role_id, r.name as role_name
        FROM employees e
        JOIN roles r ON e.primary_role_id = r.id
        WHERE e.store_code=? AND e.is_active=1
        """,
        (store_code,),
    )
    roles = cursor.fetchall()
    return [
        {
            "role_id": row["role_id"],
            "count_per_day": FALLBACK_COUNT_PER_ROLE,
            "shift_start": FALLBACK_SHIFT_START,
            "shift_end": FALLBACK_SHIFT_END,
        }
        for row in roles
    ]


def get_required_slots_by_demand(cursor, store_code: str, date_str: str) -> list[dict]:
    """Потребность для dark_store: сначала пробуем прогноз заказов,
    если его нет — временный норматив по ролям."""
    forecast_rows = _read_demand_forecast(store_code, date_str)

    if not forecast_rows:
        return _fallback_slots_for_dark_store(cursor, store_code)

    # Преобразуем role_name -> role_id
    cursor.execute("SELECT id, name FROM roles")
    role_name_to_id = {row["name"]: row["id"] for row in cursor.fetchall()}

    slots = []
    for row in forecast_rows:
        role_id = role_name_to_id.get(row["role_name"])
        if role_id is None:
            logger.warning(
                "Роль '%s' из demand_forecast.csv не найдена в таблице roles, строка пропущена",
                row["role_name"],
            )
            continue
        slots.append(
            {
                "role_id": role_id,
                "count_per_day": int(row["count"]),
                "shift_start": row["shift_start"],
                "shift_end": row["shift_end"],
            }
        )
    return slots


def get_required_slots(cursor, store_code: str, store_format: str, work_mode: str, date_str: str) -> list[dict]:
    """Единая точка входа: выбирает источник потребности в зависимости от формата."""
    if store_format == "dark_store":
        return get_required_slots_by_demand(cursor, store_code, date_str)
    return get_required_slots_template(cursor, store_format, work_mode)
