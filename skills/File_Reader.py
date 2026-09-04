"""
Skills: File Reader (Чтение файлов)
Назначение: предоставляет агенту возможность читать Excel, CSV и JSON из папок данных.
Автор: Команда разработки
Дата: 2025-08-05
Версия: 2.0
"""

import os
import csv as csv_mod
import json
import asyncio
import logging
import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from abc import ABC, abstractmethod

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ============================================================================
#  Базовый абстрактный класс для всех инструментов (Skills)
# ============================================================================
class BaseTool(ABC):
    """Абстрактный класс для всех инструментов агента."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя инструмента (используется в function calling)."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Описание инструмента для LLM (что он делает и когда его вызывать)."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """JSON Schema для параметров вызова."""
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Основной метод выполнения. Возвращает словарь с результатом."""
        pass


# ============================================================================
#  Конкретная реализация инструмента для чтения файлов
# ============================================================================
class FileReaderTool(BaseTool):
    """
    Инструмент для чтения файлов из папок data/ (inbox, working, knowledge).
    Поддерживает форматы: .xlsx, .xls, .csv, .json.

    Безопасность:
        - file_name валидируется (запрет на символы пути)
        - итоговый путь проверяется через resolve(), чтобы остаться в target_folder

    Асинхронность:
        - execute() — async
        - файловый ввод-вывод вынесен в asyncio.to_thread(), чтобы не блокировать event loop
    """

    SUPPORTED_EXTENSIONS = {'.xlsx', '.xls', '.csv', '.json'}
    DEFAULT_MAX_ROWS = 1000

    # ------------------------------------------------------------------
    #  Свойства инструмента
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Читает структурированные файлы (Excel, CSV, JSON) из папок data/ "
            "и возвращает содержимое в виде списка словарей. "
            "Поддерживает указание листа для Excel и ограничение числа строк. "
            "Используйте для получения списка сотрудников, текущих графиков и справочников."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": (
                        "Имя файла с расширением, без символов пути. "
                        "Например: employees.xlsx, schedule.csv"
                    )
                },
                "folder": {
                    "type": "string",
                    "enum": ["inbox", "working", "knowledge"],
                    "description": "Папка внутри data/. По умолчанию 'inbox'.",
                    "default": "inbox"
                },
                "sheet_name": {
                    "type": ["string", "integer"],
                    "description": (
                        "Название или индекс листа для Excel. "
                        "Если не указан, берётся первый лист."
                    )
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Максимальное количество строк для чтения.",
                    "default": 1000,
                    "minimum": 1
                },
                "all_as_string": {
                    "type": "boolean",
                    "description": (
                        "Если true, все значения читаются как строки. "
                        "Полезно для сохранения ведущих нулей и табельных номеров."
                    ),
                    "default": False
                }
            },
            "required": ["file_name"]
        }

    # ------------------------------------------------------------------
    #  Основной метод
    # ------------------------------------------------------------------
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Читает файл и возвращает:
            {
                "status": "ok" | "error",
                "data": list | None,
                "message": str
            }
        """
        file_name = params.get("file_name", "")
        folder = params.get("folder", "inbox")
        sheet_name = params.get("sheet_name")
        max_rows = params.get("max_rows", self.DEFAULT_MAX_ROWS)
        all_as_string = bool(params.get("all_as_string", False))

        # --- Нормализация max_rows ---
        try:
            max_rows = int(max_rows)
        except (TypeError, ValueError):
            max_rows = self.DEFAULT_MAX_ROWS
        if max_rows < 1:
            max_rows = self.DEFAULT_MAX_ROWS

        # --- Валидация имени файла ---
        validation_error = self._validate_file_name(file_name)
        if validation_error:
            logger.warning("Отклонён file_name=%r: %s", file_name, validation_error)
            return {"status": "error", "message": validation_error, "data": None}

        # --- Определяем папку ---
        base_dir = self._get_base_dir()
        folder_map = {
            "inbox": base_dir / "1_inbox",
            "working": base_dir / "2_working",
            "knowledge": base_dir / "5_knowledge",
        }

        target_folder = folder_map.get(folder)
        if target_folder is None:
            return {
                "status": "error",
                "message": f"Неизвестная папка: {folder}. Допустимы: inbox, working, knowledge.",
                "data": None
            }

        # --- Безопасное построение пути ---
        file_path = (target_folder / file_name).resolve()
        if not str(file_path).startswith(str(target_folder.resolve())):
            logger.warning(
                "Попытка выхода за пределы папки: file_name=%r, resolved=%s",
                file_name, file_path
            )
            return {
                "status": "error",
                "message": f"Недопустимый путь к файлу: {file_name}",
                "data": None
            }

        if not file_path.exists():
            return {
                "status": "error",
                "message": f"Файл {file_name} не найден в папке {folder}.",
                "data": None
            }

        # --- Проверка расширения ---
        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            return {
                "status": "error",
                "message": (
                    f"Неподдерживаемый формат: {ext}. "
                    f"Используйте {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}"
                ),
                "data": None
            }

        # --- Чтение в отдельном потоке ---
        try:
            data = await asyncio.to_thread(
                self._read_file_sync,
                file_path, ext, sheet_name, max_rows, all_as_string
            )
        except Exception as exc:
            logger.exception("Ошибка при чтении файла %s", file_name)
            return {
                "status": "error",
                "message": f"Ошибка при чтении файла: {exc}",
                "data": None
            }

        logger.info("Прочитано %d строк из %s", len(data), file_name)
        return {
            "status": "ok",
            "data": data,
            "message": f"Успешно прочитано {len(data)} строк из {file_name}"
        }

    # ------------------------------------------------------------------
    #  Внутренняя диспетчеризация форматов (синхронная, для to_thread)
    # ------------------------------------------------------------------
    def _read_file_sync(
        self,
        file_path: Path,
        ext: str,
        sheet_name: Optional[Any],
        max_rows: int,
        all_as_string: bool
    ) -> List[Dict]:
        if ext in ('.xlsx', '.xls'):
            return self._read_excel(file_path, sheet_name, max_rows, all_as_string)
        if ext == '.csv':
            return self._read_csv(file_path, max_rows)
        if ext == '.json':
            return self._read_json(file_path, max_rows)
        raise ValueError(f"Неподдерживаемый формат: {ext}")

    # ------------------------------------------------------------------
    #  Excel
    # ------------------------------------------------------------------
    def _read_excel(
        self,
        file_path: Path,
        sheet_name: Optional[Any],
        max_rows: int,
        all_as_string: bool
    ) -> List[Dict]:
        """
        Читает один лист Excel. Если sheet_name не указан, берётся первый лист.
        """
        if sheet_name is None:
            sheet_name = 0  # КРИТИЧНО: None заставил бы pandas читать ВСЕ листы

        dtype = str if all_as_string else None

        df = pd.read_excel(
            file_path,
            sheet_name=sheet_name,
            nrows=max_rows,
            dtype=dtype
        )

        df = df.where(pd.notnull(df), None)
        records = df.to_dict(orient="records")
        return self._sanitize_records(records)

    # ------------------------------------------------------------------
    #  CSV
    # ------------------------------------------------------------------
    def _read_csv(self, file_path: Path, max_rows: int) -> List[Dict]:
        """
        Читает CSV с автоопределением разделителя и перебором кодировок.
        """
        encodings = ['utf-8', 'cp1251', 'latin-1']
        separators = [',', ';', '\t']

        # Пытаемся угадать разделитель через csv.Sniffer
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                sample = f.read(8192)
                dialect = csv_mod.Sniffer().sniff(sample, delimiters=',;\t')
                guessed = dialect.delimiter
                if guessed in separators:
                    separators.remove(guessed)
                separators.insert(0, guessed)
        except Exception:
            # Sniffer не справился — идём по списку по умолчанию
            pass

        last_error: Optional[Exception] = None
        fallback_df: Optional[pd.DataFrame] = None

        for enc in encodings:
            for sep in separators:
                try:
                    df = pd.read_csv(file_path, nrows=max_rows, encoding=enc, sep=sep)

                    # Если больше одной колонки — скорее всего, разделитель угадан
                    if df.shape[1] > 1:
                        df = df.where(pd.notnull(df), None)
                        return self._sanitize_records(df.to_dict(orient="records"))

                    # Одна колонка — сохраняем как fallback, вдруг дальше будет лучше
                    if fallback_df is None:
                        fallback_df = df

                except UnicodeDecodeError as exc:
                    last_error = exc
                    continue
                except pd.errors.ParserError as exc:
                    last_error = exc
                    continue
                except Exception as exc:
                    last_error = exc
                    continue

        # Ничего лучше не нашли, но хотя бы одна колонка прочиталась
        if fallback_df is not None:
            fallback_df = fallback_df.where(pd.notnull(fallback_df), None)
            return self._sanitize_records(fallback_df.to_dict(orient="records"))

        raise ValueError(f"Не удалось распарсить CSV: {last_error}")

    # ------------------------------------------------------------------
    #  JSON
    # ------------------------------------------------------------------
    def _read_json(self, file_path: Path, max_rows: int) -> List[Dict]:
        """
        Читает JSON. Ожидается массив объектов или объект с ключом-массивом.
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = json.load(f)

        data: Optional[List[Dict]] = None

        if isinstance(content, list):
            data = content
        elif isinstance(content, dict):
            for key in ("data", "employees", "schedule", "items", "records"):
                if key in content and isinstance(content[key], list):
                    data = content[key]
                    break
            if data is None:
                data = [content]
        else:
            raise ValueError(
                "JSON должен содержать массив или объект с ключом-массивом "
                "('data', 'employees', 'schedule', 'items', 'records')."
            )

        return data[:max_rows]

    # ------------------------------------------------------------------
    #  Вспомогательные методы
    # ------------------------------------------------------------------
    def _validate_file_name(self, file_name: str) -> Optional[str]:
        """
        Возвращает текст ошибки или None, если имя файла допустимо.
        """
        if not file_name or not isinstance(file_name, str):
            return "file_name должен быть непустой строкой."

        if '\x00' in file_name:
            return "file_name содержит недопустимые символы."

        if '/' in file_name or '\\' in file_name:
            return "file_name не должен содержать символы пути (/ или \\)."

        if file_name in ('.', '..'):
            return "Недопустимое имя файла."

        return None

    def _get_base_dir(self) -> Path:
        """
        Возвращает корневую папку data/.
        Приоритет: переменная окружения DATA_DIR, иначе относительный путь.
        """
        env_data_dir = os.environ.get("DATA_DIR")
        if env_data_dir:
            return Path(env_data_dir).resolve()

        # Fallback: предполагаем, что файл лежит в project_root/src/.../file_reader.py
        return Path(__file__).resolve().parents[1] / "data"

    def _sanitize_records(self, records: List[Dict]) -> List[Dict]:
        """
        Приводит значения к JSON-совместимым типам:
        datetime → ISO-строка, numpy-типы → встроенные Python-типы.
        """
        sanitized = []
        for row in records:
            clean_row = {}
            for key, value in row.items():
                if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
                    clean_row[key] = value.isoformat()
                elif isinstance(value, np.integer):
                    clean_row[key] = int(value)
                elif isinstance(value, np.floating):
                    clean_row[key] = float(value)
                elif isinstance(value, np.bool_):
                    clean_row[key] = bool(value)
                elif isinstance(value, np.ndarray):
                    clean_row[key] = value.tolist()
                else:
                    clean_row[key] = value
            sanitized.append(clean_row)
        return sanitized


# ============================================================================
#  Отладочный запуск
# ============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    async def test():
        tool = FileReaderTool()

        result = await tool.execute({
            "file_name": "employees_master.xlsx",
            "folder": "inbox",
            "max_rows": 5
        })

        print("Результат теста:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(test())
