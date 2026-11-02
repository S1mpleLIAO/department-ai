from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[2]


def _load_environment() -> None:
    """读取部门项目根目录的统一环境配置。"""
    load_dotenv(os.getenv("DEPARTMENT_ENV_FILE") or PROJECT_DIR.parent / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    database_url: str
    docling_base_url: str
    siliconflow_base_url: str
    siliconflow_api_key: str
    siliconflow_configured: bool
    metadata_base_url: str
    metadata_api_key: str
    metadata_model: str
    data_dir: Path
    skill_dir: Path
    max_source_bytes: int
    harness_url: str
    harness_health_url: str
    host: str
    port: int
    auth_origin: str = ""


def get_settings() -> Settings:
    _load_environment()
    auth_origin = os.getenv("DEPARTMENT_AUTH_ORIGIN", "").rstrip("/")
    from urllib.parse import urlsplit
    origin = urlsplit(auth_origin)
    if (not origin.netloc or origin.path or origin.query or origin.fragment or
        (origin.scheme != "https" and not
         (origin.scheme == "http" and origin.hostname in ("127.0.0.1", "localhost")))):
        raise RuntimeError("必须配置 DEPARTMENT_AUTH_ORIGIN；公网必须使用 HTTPS")
    database_url = os.getenv("DEPARTMENT_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "缺少 DEPARTMENT_DATABASE_URL；请在 department-ai/.env 中配置。"
        )
    siliconflow_base_url = os.getenv(
        "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
    ).rstrip("/")
    siliconflow_api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    return Settings(
        auth_origin=auth_origin,
        database_url=database_url,
        docling_base_url=os.getenv("DOCLING_BASE_URL", "http://127.0.0.1:15001").rstrip("/"),
        siliconflow_base_url=siliconflow_base_url,
        siliconflow_api_key=siliconflow_api_key,
        siliconflow_configured=bool(siliconflow_api_key),
        metadata_base_url=os.getenv("METADATA_BASE_URL", siliconflow_base_url).rstrip("/"),
        metadata_api_key=os.getenv("METADATA_API_KEY", siliconflow_api_key).strip(),
        metadata_model=os.getenv("METADATA_MODEL", "deepseek-ai/DeepSeek-V3.2").strip(),
        data_dir=Path(
            os.getenv(
                "DEPARTMENT_DATA_DIR",
                str(PROJECT_DIR.parent / "runtime-data" / "department-ai-python"),
            )
        ).resolve(),
        skill_dir=Path(
            os.getenv(
                "DEPARTMENT_SKILL_DIR",
                str(PROJECT_DIR.parent / "runtime-data" / "department-skills"),
            )
        ).resolve(),
        max_source_bytes=int(os.getenv("DEPARTMENT_MAX_SOURCE_BYTES", str(20 * 1024 * 1024))),
        harness_url=os.getenv(
            "DEPARTMENT_HARNESS_URL", "http://127.0.0.1:3080/"
        ).strip(),
        harness_health_url=os.getenv(
            "DEPARTMENT_HARNESS_HEALTH_URL", "http://127.0.0.1:3080/"
        ).strip(),
        host=os.getenv("DEPARTMENT_PYTHON_HOST", "127.0.0.1"),
        port=int(os.getenv("DEPARTMENT_PYTHON_PORT", "3081")),
    )
