from openai import OpenAI

from config import settings

# DeepSeek полностью совместим с OpenAI SDK — меняем только base_url
client = OpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")

SYSTEM_PROMPT = (
    "Ты — HR-агент компании, помогаешь сотрудникам по вопросам управления персоналом: "
    "отпуска, справки, адаптация, внутренние процессы. Отвечай кратко, по-деловому и дружелюбно. "
    "Если не знаешь ответа или для действия нужен доступ к данным, которых у тебя пока нет, "
    "честно скажи об этом, а не выдумывай."
)


def get_agent_reply(history: list[dict]) -> str:
    """
    history — список сообщений [{"role": "user"/"assistant", "content": "..."}], без system.
    На этом этапе — просто диалог. Скиллы (function calling) подключим сюда позже:
    добавится параметр tools=[...] и обработка tool_calls в ответе.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.4,
        max_tokens=800,
    )
    return response.choices[0].message.content
