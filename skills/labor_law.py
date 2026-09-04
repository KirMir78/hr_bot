"""
Ограничения по режиму труда (ТК РФ + внутренние нормативы компании).

Модуль не знает ничего о конкретных магазинах — только правила и функции
для их проверки/применения к уже готовому набору смен.

ВАЖНО: значения ниже — стандартные нормы ТК РФ на общих основаниях
(без учёта льготных категорий — несовершеннолетних, инвалидов и т.п.).
Если в штате есть такие сотрудники, для них нужны отдельные нормативы —
уточните и добавим.
"""
from datetime import datetime, timedelta

# --- Константы -------------------------------------------------------

MAX_HOURS_PER_WEEK = 40            # ст. 91 ТК РФ, стандартная норма для полной ставки
MAX_CONSECUTIVE_SHIFTS = 6         # внутренний норматив компании (уточнить, не жёсткая норма ТК)
MIN_REST_BETWEEN_SHIFTS_HOURS = 11 # межсменный отдых, ориентир из практики (уточнить точную норму)
MIN_WEEKLY_REST_HOURS = 42         # ст. 110 ТК РФ, непрерывный еженедельный отдых
NIGHT_SHIFT_START_HOUR = 22        # ст. 96 ТК РФ, ночное время: 22:00–06:00
NIGHT_SHIFT_END_HOUR = 6


def _parse_time(t: str) -> int:
    """'09:30' -> 570 (минуты от начала суток)."""
    h, m = map(int, t.split(":"))
    return h * 60 + m


def is_night_shift(start_time: str, end_time: str) -> bool:
    """Смена считается ночной, если пересекается с 22:00–06:00."""
    start = _parse_time(start_time)
    end = _parse_time(end_time)
    if end <= start:  # смена через полночь
        end += 24 * 60
    night_start = NIGHT_SHIFT_START_HOUR * 60
    night_end = (NIGHT_SHIFT_END_HOUR + 24) * 60  # 06:00 следующих суток
    return start < night_end and end > night_start


def check_weekly_hours(employee_hours: dict) -> list[str]:
    """employee_hours: {employee_name: total_hours_in_period}.
    Возвращает список нарушений превышения MAX_HOURS_PER_WEEK."""
    warnings = []
    for name, hours in employee_hours.items():
        if hours > MAX_HOURS_PER_WEEK:
            warnings.append(
                f"Сотрудник {name} превысил {MAX_HOURS_PER_WEEK}ч/неделю (план: {hours}ч)"
            )
    return warnings


def check_consecutive_days(shifts_by_employee: dict) -> list[str]:
    """shifts_by_employee: {employee_name: sorted list of 'YYYY-MM-DD'}.
    Проверка превышения MAX_CONSECUTIVE_SHIFTS дней подряд."""
    warnings = []
    for name, dates in shifts_by_employee.items():
        streak = 1
        for i in range(1, len(dates)):
            prev = datetime.strptime(dates[i - 1], "%Y-%m-%d")
            curr = datetime.strptime(dates[i], "%Y-%m-%d")
            if (curr - prev).days == 1:
                streak += 1
                if streak > MAX_CONSECUTIVE_SHIFTS:
                    warnings.append(
                        f"Сотрудник {name} работает {streak} дней подряд без выходного (дата: {dates[i]})"
                    )
            else:
                streak = 1
    return warnings


def check_rest_between_shifts(shifts_by_employee: dict) -> list[str]:
    """shifts_by_employee: {employee_name: sorted list of (date, start_time, end_time)}.
    Проверка минимального межсменного отдыха."""
    warnings = []
    for name, shifts in shifts_by_employee.items():
        for i in range(1, len(shifts)):
            prev_date, _, prev_end = shifts[i - 1]
            curr_date, curr_start, _ = shifts[i]

            prev_end_dt = datetime.strptime(f"{prev_date} {prev_end}", "%Y-%m-%d %H:%M")
            curr_start_dt = datetime.strptime(f"{curr_date} {curr_start}", "%Y-%m-%d %H:%M")

            if curr_start_dt < prev_end_dt:
                # смена предыдущего дня уходит за полночь — не пересчитываем здесь,
                # это должно быть учтено при формировании shifts выше по стеку
                continue

            rest_hours = (curr_start_dt - prev_end_dt).total_seconds() / 3600
            if rest_hours < MIN_REST_BETWEEN_SHIFTS_HOURS:
                warnings.append(
                    f"Сотрудник {name}: отдых между сменами {rest_hours:.1f}ч "
                    f"(меньше нормы {MIN_REST_BETWEEN_SHIFTS_HOURS}ч), смена {curr_date}"
                )
    return warnings
