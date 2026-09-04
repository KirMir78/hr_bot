import re
from openai import AsyncOpenAI
import json
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from config import settings
from skills import FileReaderTool
from skills.Schedule_Planner import (
    PlanScheduleTool,
    GetScheduleTool,
    ModifyScheduleTool,
    PublishScheduleTool,
    ListStoresTool,
    GetEmployeesTool,
    PublishLatestPlanTool
)

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=settings.deepseek_api_key,
    base_url="https://api.deepseek.com"
)

file_reader = FileReaderTool()
plan_schedule = PlanScheduleTool()
get_schedule = GetScheduleTool()
modify_schedule = ModifyScheduleTool()
publish_schedule = PublishScheduleTool()
list_stores = ListStoresTool()
get_employees = GetEmployeesTool()
publish_latest = PublishLatestPlanTool()

TOOL_REGISTRY = {
    file_reader.name: file_reader,
    plan_schedule.name: plan_schedule,
    get_schedule.name: get_schedule,
    modify_schedule.name: modify_schedule,
    publish_schedule.name: publish_schedule,
    list_stores.name: list_stores,
    get_employees.name: get_employees,
    publish_latest.name: publish_latest
}

# ========== НОВЫЙ БЛОК ЗАГРУЗКИ ПРОМПТА ==========
PROMPT_FILE = Path(__file__).parent / "system_prompt.txt"
try:
    SYSTEM_PROMPT = PROMPT_FILE.read_text(encoding="utf-8")
except FileNotFoundError:
    raise RuntimeError(f"Файл с системным промптом не найден: {PROMPT_FILE}")
# ================================================

def get_current_datetime_str() -> str:
    """Возвращает текущую дату и время в человекочитаемом формате (МСК)."""
    tz = ZoneInfo("Europe/Moscow")
    now = datetime.now(tz)

    days = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
    months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
              'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']

    return (
        f"{now.day} {months[now.month - 1]} {now.year} года, "
        f"{days[now.weekday()]}, {now.strftime('%H:%M')} (МСК)"
    )


async def get_agent_reply(history: list[dict]) -> str:
    current_dt = get_current_datetime_str()

    system_prompt_with_date = (
        f"{SYSTEM_PROMPT}\n\n"
        f"ТЕКУЩИЕ ДАТА И ВРЕМЯ: {current_dt}\n"
        f"Используй эту информацию, когда пользователь спрашивает про 'сегодня', 'завтра', "
        f"'на этой неделе', 'вчера' и т.п."
    )

    messages = [{"role": "system", "content": system_prompt_with_date}] + history

    tools = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema
            }
        }
        for tool in TOOL_REGISTRY.values()
    ]

    logger.info("=== ЗАПРОС К DEEPSEEK ===")
    logger.info("Количество инструментов: %d", len(tools))

    MAX_TOOL_ROUNDS = 5
    last_pdf_link = None

    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.4,
                max_tokens=800,
                tools=tools,
                tool_choice="auto"
            )
        except Exception as e:
            logger.exception("Ошибка при вызове DeepSeek API")
            return f"Ошибка при обращении к AI: {str(e)}"

        if not response.choices:
            logger.error("Пустой ответ от DeepSeek (нет choices)")
            return "Извините, не удалось получить ответ от AI. Попробуйте ещё раз."

        message = response.choices[0].message

        if not message.tool_calls:
            final_text = message.content or "Извините, не удалось сформировать ответ."
            if last_pdf_link and last_pdf_link not in final_text:
                final_text += f"\nСсылка на PDF: {last_pdf_link}"
            return final_text

        logger.info("=== МОДЕЛЬ ВЫЗВАЛА ИНСТРУМЕНТЫ (раунд %d) ===", round_num + 1)

        assistant_message = {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in message.tool_calls
            ]
        }
        messages.append(assistant_message)

        for tool_call in message.tool_calls:
            logger.info("Вызов: %s (ID: %s)", tool_call.function.name, tool_call.id)
            tool_instance = TOOL_REGISTRY.get(tool_call.function.name)

            if tool_instance:
                try:
                    raw_args = tool_call.function.arguments
                    args = json.loads(raw_args) if raw_args and raw_args.strip() else {}
                    result = await tool_instance.execute(args)
                    logger.info("Результат %s: %s", tool_call.function.name, json.dumps(result, ensure_ascii=False)[:800])
                    if tool_call.function.name == "plan_schedule":
                        found_links = re.findall(r'href="(https?://[^"]+\.pdf)"', json.dumps(result, ensure_ascii=False))
                        if found_links:
                            last_pdf_link = found_links[-1]
                except Exception as e:
                    logger.exception("Ошибка при выполнении скилла")
                    result = {"status": "error", "message": f"Ошибка скилла: {str(e)}", "data": None}
            else:
                logger.warning("Неизвестный инструмент: %s", tool_call.function.name)
                result = {"status": "error", "message": "Неизвестный инструмент", "data": None}

            tool_result = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False)
            }
            messages.append(tool_result)

    logger.warning("Достигнут лимит раундов вызова инструментов (%d)", MAX_TOOL_ROUNDS)
    return "Не удалось завершить обработку запроса за отведённое количество шагов. Уточните, пожалуйста, запрос."
