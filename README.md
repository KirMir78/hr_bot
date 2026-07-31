# HR-агент — MVP

Веб-чат с HR-агентом на DeepSeek, вход через Telegram Login Widget.
Бота как такового пока нет — только веб-морда и бэкенд, к которому потом
можно подключить aiogram-бота (он будет дёргать тот же `agent.py`).

## Структура

```
backend/
  main.py           — FastAPI, роуты /auth/telegram, /chat, /chat/history
  agent.py          — вызов DeepSeek (ядро агента, сюда позже добавятся скиллы)
  auth.py           — проверка Telegram Login Widget, JWT-сессии
  models.py         — User, Message (SQLAlchemy)
  database.py       — SQLite для MVP
  config.py         — настройки из .env
frontend/
  index.html        — страница логина + чат, ванильный JS, без сборки
```

## Запуск бэкенда

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# впишите в .env:
#   TELEGRAM_BOT_TOKEN   — токен от @BotFather
#   TELEGRAM_BOT_USERNAME
#   DEEPSEEK_API_KEY     — с platform.deepseek.com
#   JWT_SECRET           — любая случайная строка

uvicorn main:app --reload --port 8000
```

Проверка: http://localhost:8000/health → `{"status":"ok"}`

## Запуск фронтенда

Для MVP сборка не нужна — просто откройте `frontend/index.html` в браузере
(или раздайте через `python -m http.server` из папки frontend).

В `index.html` поправьте:
```js
const API_BASE = "http://localhost:8000";
const TELEGRAM_BOT_USERNAME = "your_hr_bot"; // без @
```

## Важный нюанс с Telegram Login Widget

Виджет работает **только на https-домене, который вы явно указали
боту через BotFather**:

1. Напишите @BotFather → выберите бота → `Bot Settings` → `Domain` → `/setdomain`
2. Укажите домен, на котором будет жить сайт (например `hr.mycompany.com`)
3. На localhost виджет не заработает — это ограничение самого Telegram

**Для локальной разработки** используйте кнопку «Войти как тестовый
пользователь (dev)» на странице — она дёргает `/auth/dev-login`, который
работает только при `APP_ENV=dev` и выдаёт токен без реального Telegram-логина.
Когда перейдёте на прод-домен, поставьте `APP_ENV=prod` — dev-логин отключится.

Для быстрого теста виджета до покупки домена можно временно поднять
https-туннель (например ngrok) и прописать его адрес в BotFather.

## Деплой на сервер со своим доменом

Предполагается: у вас есть VPS с публичным IP и вы уже направили A-запись
домена на этот IP (см. предыдущий шаг с DNS).

### 1. Бэкенд как systemd-сервис

```bash
# на сервере
git clone <ваш репозиторий> /opt/hr-agent
cd /opt/hr-agent/backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env   # заполните реальными значениями, APP_ENV=prod, ALLOWED_ORIGIN=https://yourdomain.com
```

Создайте `/etc/systemd/system/hr-agent.service`:

```ini
[Unit]
Description=HR Agent API
After=network.target

[Service]
WorkingDirectory=/opt/hr-agent/backend
ExecStart=/opt/hr-agent/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
EnvironmentFile=/opt/hr-agent/backend/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hr-agent
sudo systemctl status hr-agent   # убедиться, что запустился
```

Обратите внимание: слушаем `127.0.0.1`, а не `0.0.0.0` — наружу бэкенд
не торчит, всё идёт через Caddy.

### 2. Фронт: положить статику

```bash
sudo mkdir -p /var/www/hr-agent-frontend
sudo cp /opt/hr-agent/frontend/index.html /var/www/hr-agent-frontend/
```

В `index.html` перед копированием поправьте:
```js
const API_BASE = "https://yourdomain.com";
const TELEGRAM_BOT_USERNAME = "your_hr_bot";
```

### 3. Caddy — автоматический HTTPS

```bash
sudo apt install -y caddy   # или см. https://caddyserver.com/docs/install
```

Скопируйте `deploy/Caddyfile` в `/etc/caddy/Caddyfile`, замените
`yourdomain.com` на ваш домен:

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy сам получит сертификат Let's Encrypt при первом запросе к домену —
ничего вручную выпускать не нужно. Через минуту-две `https://yourdomain.com`
должен открываться с валидным замком в браузере.

### 4. Прописать домен в BotFather

В чате с @BotFather:
```
/setdomain
→ выбрать бота
→ ввести: yourdomain.com
```

### 5. Проверка

- `https://yourdomain.com/health` → `{"status":"ok"}`
- Откройте `https://yourdomain.com` — должна появиться кнопка «Log in with Telegram»
  (реальная, не dev-заглушка)
- Войдите — если подпись не совпадёт или домен не тот, Telegram сам покажет
  ошибку прямо в виджете ("Bot domain invalid" и т.п.)

После этого можно поставить `APP_ENV=prod` в `.env` на сервере и
перезапустить сервис — `/auth/dev-login` отключится, останется только
настоящий вход через Telegram.

## Как это будет расти дальше

- **Скиллы агента**: в `agent.py` добавляете `tools=[...]` (DeepSeek поддерживает
  function calling в стиле OpenAI) и обработку `tool_calls` — так подключаются
  «оформить отпуск», «найти сотрудника» и т.д., без изменения фронта.
- **Сам Telegram-бот**: aiogram-хендлеры импортируют `get_agent_reply` из
  `agent.py` — бот и сайт используют одну и ту же логику и одну БД,
  диалог продолжается независимо от того, откуда пришло сообщение.
- **Postgres вместо SQLite**: меняется одна строка `database_url` в `config.py`.
- **Стриминг ответа**: замена обычного `/chat` на WebSocket или SSE, когда
  захочется эффекта «печатает...» в реальном времени, а не спиннера.
