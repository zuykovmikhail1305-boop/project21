"""Chart Executor: изолированное выполнение Python-кода для генерации графиков.

Поддерживает два режима:
- SubprocessSandbox (MVP) — изолированный subprocess с ограничениями
- DockerSandbox (Production) — Docker-контейнер с полной изоляцией
"""

import logging
import os
import subprocess
import sys
import tempfile
from typing import Optional

from app.services.artifact.base import SandboxResult

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Ошибка безопасности: код содержит запрещённые конструкции."""
    pass


class SubprocessSandbox:
    """Изолированный subprocess для выполнения кода графиков (MVP).

    Ограничения:
    - Статический анализ кода на запрещённые паттерны
    - Лимит памяти: 512MB
    - Таймаут: 30 секунд
    - Максимальный размер файла: 10MB
    - Изолированное окружение (MPLBACKEND=Agg, минимальный PATH)
    """

    MAX_MEMORY_MB = 512
    MAX_CPU_TIME = 30
    MAX_FILESIZE_MB = 10

    FORBIDDEN_PATTERNS = [
        "import os",
        "import subprocess",
        "import sys",
        "import shutil",
        "import socket",
        "import requests",
        "import urllib",
        "import http",
        "import ftplib",
        "import telnetlib",
        "import ctypes",
        "__import__",
        "eval(",
        "exec(",
        "compile(",
        "open(",
        "BaseException",
    ]

    def __init__(self, output_dir: str = "/tmp/charts"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def execute(self, code: str, chart_index: int) -> SandboxResult:
        """Выполнить код графика в изолированном subprocess.

        Args:
            code: Чистый Python-код для выполнения.
            chart_index: Индекс графика (для именования выходных файлов).

        Returns:
            SandboxResult с путями к сгенерированным файлам.
        """
        # 1. Статический анализ
        self._validate_code(code)

        # 2. Оборачиваем код в sandbox-обёртку
        wrapped = self._wrap_code(code, chart_index)

        # 3. Записываем во временный файл
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir=self.output_dir
        ) as f:
            f.write(wrapped)
            script_path = f.name

        try:
            # 4. Запускаем с ограничениями
            result = subprocess.run(
                [sys.executable, "-I", script_path],
                capture_output=True,
                text=True,
                timeout=self.MAX_CPU_TIME,
                cwd=self.output_dir,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": self.output_dir,
                    "MPLBACKEND": "Agg",
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONHASHSEED": "0",
                },
            )

            if result.returncode != 0:
                error_msg = result.stderr[:2000] if result.stderr else "Unknown error"
                logger.error(f"Chart {chart_index} execution failed: {error_msg}")
                return SandboxResult(
                    success=False,
                    error=f"Chart execution failed (exit code {result.returncode}): {error_msg}",
                )

            # 5. Собираем результаты
            return self._collect_results(chart_index)

        except subprocess.TimeoutExpired:
            logger.error(f"Chart {chart_index} execution timed out ({self.MAX_CPU_TIME}s)")
            return SandboxResult(success=False, error=f"Timeout ({self.MAX_CPU_TIME}s)")
        except Exception as e:
            logger.exception(f"Chart {chart_index} execution error")
            return SandboxResult(success=False, error=str(e))
        finally:
            # 6. Очистка
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def _validate_code(self, code: str) -> None:
        """Статический анализ кода на запрещённые конструкции."""
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern in code:
                raise SecurityError(
                    f"Запрещённая конструкция в коде графика: '{pattern}'"
                )

    def _wrap_code(self, code: str, chart_index: int) -> str:
        """Оборачивает пользовательский код в sandbox-обёртку с ограничениями."""
        return f'''"""
Chart generator — sandboxed execution.
Chart index: {chart_index}
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd
import json
import math
import random
from collections import Counter, defaultdict

# Resource limits
import resource
resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))

# Constants for output
CHART_INDEX = {chart_index}
OUTPUT_DIR = "{self.output_dir}"

# === USER CODE START ===
{code}
# === USER CODE END ===

plt.close("all")
'''

    def _collect_results(self, chart_index: int) -> SandboxResult:
        """Собрать результаты выполнения — найти сгенерированные файлы."""
        output_files = []
        prefix = f"chart_{chart_index}"

        for fname in os.listdir(self.output_dir):
            if fname.startswith(prefix) and os.path.isfile(os.path.join(self.output_dir, fname)):
                output_files.append(os.path.join(self.output_dir, fname))

        if not output_files:
            return SandboxResult(
                success=False,
                error=f"Не найдены выходные файлы для chart_{chart_index}",
            )

        return SandboxResult(success=True, output_files=output_files)


class DockerSandbox:
    """Docker-контейнер для изолированного выполнения кода графиков (Production).

    Требует:
    - Docker daemon
    - Предсобранный образ chart-runner:latest
    """

    IMAGE_NAME = "chart-runner:latest"
    MEMORY_LIMIT = "512m"
    CPU_LIMIT = 1.0
    TIMEOUT = 30

    FORBIDDEN_PATTERNS = SubprocessSandbox.FORBIDDEN_PATTERNS

    def __init__(self, output_dir: str = "/tmp/charts"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self._docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        """Проверить доступность Docker."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def execute(self, code: str, chart_index: int) -> SandboxResult:
        """Выполнить код в Docker-контейнере."""
        if not self._docker_available:
            logger.warning("Docker not available, falling back to SubprocessSandbox")
            return SubprocessSandbox(self.output_dir).execute(code, chart_index)

        # 1. Статический анализ
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern in code:
                return SandboxResult(
                    success=False,
                    error=f"Запрещённая конструкция: '{pattern}'",
                )

        # 2. Подготовка скрипта
        import uuid
        run_id = uuid.uuid4().hex[:8]
        container_output = f"{self.output_dir}/{run_id}"
        os.makedirs(container_output, exist_ok=True)

        script_path = f"{container_output}/script.py"
        wrapped = f'''import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd
import json, math, random
from collections import Counter, defaultdict

CHART_INDEX = {chart_index}
OUTPUT_DIR = "/tmp"

{code}

plt.close("all")
'''
        with open(script_path, "w") as f:
            f.write(wrapped)

        try:
            # 3. Запуск Docker
            import docker
            client = docker.from_env()

            container = client.containers.run(
                image=self.IMAGE_NAME,
                command=f"python /tmp/script.py",
                volumes={container_output: {"bind": "/tmp", "mode": "rw"}},
                mem_limit=self.MEMORY_LIMIT,
                nano_cpus=int(self.CPU_LIMIT * 1e9),
                network_disabled=True,
                read_only=True,
                tmpfs={"/tmp": "size=100m"},
                auto_remove=True,
                detach=True,
            )

            result = container.wait(timeout=self.TIMEOUT)

            if result["StatusCode"] != 0:
                logs = container.logs().decode()[-2000:]
                return SandboxResult(success=False, error=logs)

            # 4. Собираем результаты
            output_files = []
            prefix = f"chart_{chart_index}"
            for fname in os.listdir(container_output):
                if fname.startswith(prefix) and os.path.isfile(os.path.join(container_output, fname)):
                    output_files.append(os.path.join(container_output, fname))

            if not output_files:
                return SandboxResult(
                    success=False,
                    error=f"Не найдены выходные файлы для chart_{chart_index}",
                )

            return SandboxResult(success=True, output_files=output_files)

        except Exception as e:
            logger.exception("Docker sandbox error")
            return SandboxResult(success=False, error=str(e))
        finally:
            import shutil
            shutil.rmtree(container_output, ignore_errors=True)