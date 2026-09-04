import logging
import html
from datetime import datetime, timedelta
from typing import Optional, Union
from .scheduler import run_scheduler
from .schedule_db import get_plan, save_plan, publish_plan, get_store_by_code, get_store_by_id
from .pdf_generator import generate_schedule_pdf

logger = logging.getLogger(__name__)

def render_shifts_table(shifts_list, title, plan_id=None):
    if not shifts_list:
        return "<p>График пуст.</p>"
    rows = []
    for shift in shifts_list:
        last_name = shift.get('last_name', '')
        first_name = shift.get('first_name', '')
        employee = html.escape(f"{last_name} {first_name}".strip() or '—')
        date = html.escape(str(shift.get('date', '—')))
        time_from = html.escape(str(shift.get('start_time', '—')))
        time_to = html.escape(str(shift.get('end_time', '—')))
        role = html.escape(str(shift.get('role_name') or '—'))
        rows.append(
            f"<tr><td>{employee}</td><td>{date}</td><td>{time_from}–{time_to}</td><td>{role}</td></tr>"
        )
    pdf_link = ""
    if plan_id:
        pdf_result = generate_schedule_pdf(plan_id)
        if pdf_result:
            pdf_url = pdf_result["url"]
            pdf_link = f'<p><a href="{pdf_url}" target="_blank">📄 Скачать график в PDF</a></p>'
    table_html = f"""
    <h3>{html.escape(title)}</h3>
    <table border="1" cellpadding="6" style="border-collapse: collapse; width: 100%; font-size: 14px;">
        <thead style="background-color: #4a90d9; color: white; font-weight: bold;">
            <tr><th>Сотрудник</th><th>Дата</th><th>Время</th><th>Должность</th></tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    {pdf_link}
    """
    if plan_id:
        table_html += f'<p style="font-size: 12px; color: #666;">ID плана: {html.escape(str(plan_id))}</p>'
    return table_html

def schedule_planner(
    store_code: str,
    date_start: str,
    date_end: str,
    plan_id: Optional[int] = None
) -> str:
    try:
        store = get_store_by_code(store_code)
        if not store:
            return f"<p>Ошибка: магазин с кодом {html.escape(store_code)} не найден.</p>"
        store_id = store['id']

        if plan_id:
            plan_data = get_plan(plan_id)
            if not plan_data:
                return f"<p>Ошибка: план с ID {plan_id} не найден.</p>"
        else:
            shifts = run_scheduler(store_id, date_start, date_end)
            if not shifts:
                return "<p>Не удалось сгенерировать график. Проверьте входные данные.</p>"
            plan_id = save_plan(store_code, date_start, date_end, 'A', shifts)
            plan_data = get_plan(plan_id)

        shifts_list = plan_data.get('shifts', [])
        title = f"График для магазина {store_code} на {date_start} – {date_end}"
        return render_shifts_table(shifts_list, title, plan_id)
    except Exception as e:
        logger.exception("Ошибка в schedule_planner")
        return f"<p>Произошла ошибка при генерации графика: {html.escape(str(e))}</p>"

class PlanScheduleTool:
    def __init__(self):
        self.name = "plan_schedule"
        self.description = "Создаёт график работы для магазина на указанный период. Можно передать store_code, date_start, date_end или store_code, start_date, days (тогда days преобразуется в date_end)."
        self.input_schema = {
            "type": "object",
            "properties": {
                "store_code": {"type": "string", "description": "Код магазина (например, '7565')"},
                "date_start": {"type": "string", "description": "Дата начала (YYYY-MM-DD)"},
                "date_end": {"type": "string", "description": "Дата окончания (YYYY-MM-DD)"},
                "start_date": {"type": "string", "description": "Альтернативно: дата начала (YYYY-MM-DD)"},
                "days": {"type": "integer", "description": "Альтернативно: количество дней"},
                "plan_id": {"type": "integer", "description": "ID плана (опционально)"}
            },
            "required": ["store_code"]
        }
    def run(self, **kwargs) -> str:
        store_code = kwargs.get('store_code')
        if not store_code:
            return "<p>Ошибка: не указан store_code.</p>"

        # Определяем даты
        date_start = kwargs.get('date_start') or kwargs.get('start_date')
        date_end = kwargs.get('date_end')
        days = kwargs.get('days')

        if not date_start:
            return "<p>Ошибка: не указана дата начала (date_start или start_date).</p>"

        if date_end is None and days is not None:
            try:
                start = datetime.strptime(date_start, "%Y-%m-%d")
                date_end = (start + timedelta(days=int(days) - 1)).strftime("%Y-%m-%d")
            except Exception:
                return f"<p>Ошибка: неверный формат days ({days}) или date_start ({date_start}).</p>"
        elif date_end is None:
            return "<p>Ошибка: не указаны ни date_end, ни days.</p>"

        plan_id = kwargs.get('plan_id')
        return schedule_planner(store_code, date_start, date_end, plan_id)

    async def execute(self, args: dict):
        return self.run(**args)

# Остальные классы оставляем без изменений (GetScheduleTool, ModifyScheduleTool, PublishScheduleTool, PublishLatestPlanTool, ListStoresTool, GetEmployeesTool)
# Чтобы не дублировать, я скопирую их из предыдущей версии. Но для простоты я оставлю только изменённый класс, а остальные – из старой версии. 
# Однако сейчас файл полностью перезаписан, поэтому я добавлю остальные классы ниже.

class GetScheduleTool:
    def __init__(self):
        self.name = "get_schedule"
        self.description = "Получает существующий график по его ID."
        self.input_schema = {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer", "description": "ID плана"}
            },
            "required": ["plan_id"]
        }
    def run(self, plan_id: int) -> str:
        plan = get_plan(plan_id)
        if not plan:
            return f"<p>Ошибка: план с ID {plan_id} не найден.</p>"
        shifts = plan.get('shifts', [])
        title = f"График (план #{plan_id})"
        return render_shifts_table(shifts, title, plan_id)
    async def execute(self, args: dict):
        return self.run(args.get('plan_id'))

class ModifyScheduleTool:
    def __init__(self):
        self.name = "modify_schedule"
        self.description = "Изменяет параметры смены (сотрудник, дата, время, роль)."
        self.input_schema = {
            "type": "object",
            "properties": {
                "shift_id": {"type": "integer", "description": "ID смены"},
                "employee_id": {"type": "integer", "description": "Новый ID сотрудника (опционально)"},
                "date": {"type": "string", "description": "Новая дата (YYYY-MM-DD, опционально)"},
                "time_from": {"type": "string", "description": "Новое время начала (HH:MM, опционально)"},
                "time_to": {"type": "string", "description": "Новое время окончания (HH:MM, опционально)"},
                "role": {"type": "string", "description": "Новая роль (опционально)"}
            },
            "required": ["shift_id"]
        }
    def run(self, shift_id: int, **kwargs) -> str:
        from .schedule_db import update_shift
        success = update_shift(shift_id, kwargs)
        if success:
            return f"<p>Смена #{shift_id} успешно обновлена.</p>"
        else:
            return f"<p>Ошибка: не удалось обновить смену #{shift_id}.</p>"
    async def execute(self, args: dict):
        shift_id = args.get('shift_id')
        other_params = {k: v for k, v in args.items() if k != 'shift_id'}
        return self.run(shift_id, **other_params)

class PublishScheduleTool:
    def __init__(self):
        self.name = "publish_schedule"
        self.description = "Публикует черновик графика по его ID."
        self.input_schema = {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer", "description": "ID плана"}
            },
            "required": ["plan_id"]
        }
    def run(self, plan_id: int) -> str:
        success = publish_plan(plan_id)
        if success:
            return f"<p>План #{plan_id} опубликован.</p>"
        else:
            return f"<p>Ошибка: не удалось опубликовать план #{plan_id}.</p>"
    async def execute(self, args: dict):
        return self.run(args.get('plan_id'))

class PublishLatestPlanTool:
    def __init__(self):
        self.name = "publish_latest_plan"
        self.description = "Находит последний черновик графика для указанного магазина и дат и публикует его."
        self.input_schema = {
            "type": "object",
            "properties": {
                "store_code": {"type": "string", "description": "Код магазина (например, '7565')"},
                "date_start": {"type": "string", "description": "Дата начала периода (YYYY-MM-DD)"},
                "date_end": {"type": "string", "description": "Дата окончания периода (YYYY-MM-DD)"}
            },
            "required": ["store_code", "date_start", "date_end"]
        }
    def run(self, store_code: str, date_start: str, date_end: str) -> str:
        from .schedule_db import publish_plan, get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM plans
            WHERE store_code=? AND period_start=? AND period_end=? AND status='draft'
            ORDER BY id DESC LIMIT 1
        """, (store_code, date_start, date_end))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return f"<p>Не найден черновик плана для магазина {store_code} на период {date_start}–{date_end}.</p>"
        plan_id = row['id']
        success = publish_plan(plan_id)
        if success:
            return f"<p>План #{plan_id} для магазина {store_code} опубликован.</p>"
        else:
            return f"<p>Ошибка: не удалось опубликовать план #{plan_id}.</p>"
    async def execute(self, args: dict):
        return self.run(args.get('store_code'), args.get('date_start'), args.get('date_end'))

class ListStoresTool:
    def __init__(self):
        self.name = "list_stores"
        self.description = "Показывает список всех магазинов с их кодами и форматами."
        self.input_schema = {
            "type": "object",
            "properties": {},
            "required": []
        }
    def run(self) -> str:
        from .schedule_db import get_all_stores
        stores = get_all_stores()
        if not stores:
            return "<p>Магазины не найдены.</p>"
        rows = []
        for store in stores:
            store_dict = dict(store)
            format_val = store_dict.get('format') or '—'
            work_mode = store_dict.get('work_mode') or '—'
            if 'white' in format_val.lower():
                format_icon = "🏪"
            elif 'dark' in format_val.lower():
                format_icon = "🏬"
            else:
                format_icon = "🏢"
            if '24h' in work_mode.lower():
                work_icon = "🌙"
            else:
                work_icon = "☀️"
            rows.append(
                f"<tr><td><strong>{html.escape(str(store_dict['id']))}</strong></td>"
                f"<td><code>{html.escape(str(store_dict['store_code']))}</code></td>"
                f"<td>{format_icon} {html.escape(format_val)}</td>"
                f"<td>{work_icon} {html.escape(work_mode)}</td></tr>"
            )
        table_html = f"""
        <style>
        .stores-table {{
            width: 100%;
            border-collapse: collapse;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        .stores-table thead {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85rem;
            letter-spacing: 0.5px;
        }}
        .stores-table th {{
            padding: 14px 16px;
            text-align: left;
        }}
        .stores-table td {{
            padding: 12px 16px;
            border-bottom: 1px solid #f0f0f0;
            background-color: white;
        }}
        .stores-table tbody tr:hover {{
            background-color: #f8f9ff;
            transition: 0.2s;
        }}
        .stores-table tbody tr:last-child td {{
            border-bottom: none;
        }}
        </style>
        <h3>🏢 Список магазинов</h3>
        <table class="stores-table">
            <thead>
                <tr><th>ID</th><th>Код</th><th>Формат</th><th>Режим</th></tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """
        return table_html
    async def execute(self, args: dict):
        return self.run()

class GetEmployeesTool:
    def __init__(self):
        self.name = "get_employees"
        self.description = "Показывает список сотрудников и их статистику. Можно указать store_code для фильтрации."
        self.input_schema = {
            "type": "object",
            "properties": {
                "store_code": {"type": "string", "description": "Код магазина (опционально, если не указан — по всем)"}
            },
            "required": []
        }
    def run(self, store_code=None) -> str:
        from .schedule_db import get_employees
        employees = get_employees(store_code)
        if not employees:
            return "<p>Сотрудники не найдены.</p>"
        total = len(employees)
        male = sum(1 for e in employees if e.get('gender') == 'male')
        female = sum(1 for e in employees if e.get('gender') == 'female')
        unknown = total - male - female
        rows = []
        for emp in employees:
            emp_dict = dict(emp)
            gender_icon = "👨" if emp_dict.get('gender') == 'male' else ("👩" if emp_dict.get('gender') == 'female' else "🧑")
            rows.append(
                f"<tr><td>{html.escape(str(emp_dict['id']))}</td>"
                f"<td>{html.escape(str(emp_dict['last_name']))} {html.escape(str(emp_dict['first_name']))}</td>"
                f"<td>{gender_icon}</td>"
                f"<td>{html.escape(str(emp_dict.get('role_name') or '—'))}</td>"
                f"<td>{html.escape(str(emp_dict.get('store_code', '—')))}</td>"
                f"<td>{'✅' if emp_dict.get('is_active') else '❌'}</td></tr>"
            )
        table_html = f"""
        <h3>👥 Список сотрудников</h3>
        <p><strong>Всего:</strong> {total} | <strong>Мужчин:</strong> {male} | <strong>Женщин:</strong> {female} | <strong>Не указан:</strong> {unknown}</p>
        <table border="1" cellpadding="6" style="border-collapse: collapse; width: 100%; font-size: 14px;">
            <thead style="background-color: #4a90d9; color: white; font-weight: bold;">
                <tr><th>ID</th><th>ФИО</th><th>Пол</th><th>Роль</th><th>Магазин</th><th>Активен</th></tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """
        return table_html
    async def execute(self, args: dict):
        return self.run(args.get('store_code'))
