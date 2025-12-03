#!/usr/bin/env python3
"""
Модуль CreateLogsDir
--------------------

Назначение:
    - Определить общий каталог для лог-файлов проекта.
    - Гарантировать, что этот каталог существует.

Использование:
    import CreateLogsDir
    log_path = os.path.join(CreateLogsDir.LogsDir, "Chart.log")
"""

import os

# Базовый каталог – каталог, где расположен данный файл (корень проекта)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Каталог для логов – папка "Logs" в корне проекта
LogsDir = os.path.join(BASE_DIR, "Logs")

# Создаём папку, если её ещё нет
os.makedirs(LogsDir, exist_ok=True)
