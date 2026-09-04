import asyncio
import json
import logging
from pathlib import Path
import sys

# Добавляем путь к проекту
sys.path.insert(0, "/opt/hr-agent")

from skills.File_Reader import FileReaderTool

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

async def main():
    tool = FileReaderTool()

    print("=== Инфо о скилле ===")
    print(f"name: {tool.name}")
    print(f"description: {tool.description}")
    print(f"schema: {json.dumps(tool.input_schema, indent=2, ensure_ascii=False)}")

    print("\n=== Проверяем base_dir ===")
    base_dir = tool._get_base_dir()
    print(f"base_dir: {base_dir}")
    print(f"exists: {base_dir.exists()}")

    inbox = base_dir / "1_inbox"
    print(f"inbox: {inbox}")
    print(f"inbox exists: {inbox.exists()}")
    if inbox.exists():
        print(f"files in inbox: {list(inbox.iterdir())}")

    print("\n=== Вызываем скилл ===")
    result = await tool.execute({
        "file_name": "employees.csv",
        "folder": "inbox",
        "max_rows": 5
    })

    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
