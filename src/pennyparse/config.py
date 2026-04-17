import configparser
import importlib.resources
import os
import re
import tomllib
from pathlib import Path
from typing import Mapping, TypedDict

PENNYPARSE_HOST = os.getenv("PENNYPARSE_HOST", "0.0.0.0")
PENNYPARSE_PORT = int(os.getenv("PENNYPARSE_PORT", "52026"))

_protocol ="http"if PENNYPARSE_HOST == "localhost" or re.match(r"^\d+\.\d+\.\d+\.\d+$", PENNYPARSE_HOST)else "https"
PENNYPARSE_BASE = f"{_protocol}://{PENNYPARSE_HOST}:{PENNYPARSE_PORT}"

pp_config = configparser.ConfigParser()
with importlib.resources.as_file(
    importlib.resources.files("pennyparse") / "pennyparse.settings.default.ini"
) as default_path:
    pp_config.read(str(default_path))

_user_cfg = Path.home() / ".pennyparse" / "pennyparse.settings.ini"
_local_cfg = Path.cwd() / "pennyparse.settings.ini"
for cfg in (_user_cfg, _local_cfg):
    if cfg.exists():
        pp_config.read(str(cfg))


class ChatSettings(TypedDict):
    base_url: str
    api_key: str | None
    model: str | None


def read_package_text(filename: str) -> str:
    resource = importlib.resources.files("pennyparse") / filename
    return resource.read_text(encoding="utf-8")


def read_package_toml(filename: str) -> dict:
    return tomllib.loads(read_package_text(filename))


def read_prompt_catalog() -> dict:
    return read_package_toml("pennyparse.prompt.toml")


def get_prompt_text(name: str) -> str:
    catalog = read_prompt_catalog()
    value = catalog.get(name)
    if not isinstance(value, str) or not value.strip():
        raise KeyError(f"prompt {name!r} not found in pennyparse.prompt.toml")
    return value.strip()


def get_builtin_toolbox_metadata() -> dict:
    return read_package_toml("pennyparse.toolbox_builtin.toml")


def get_user_toolbox_example_text() -> str:
    return read_package_text("pennyparse.toolbox_user.example.txt")


def get_user_toolbox_text_path(*, cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / "pennyparse.toolbox_user.txt"


def get_user_toolbox_path(*, home: Path | None = None) -> Path:
    return (home or Path.home()) / ".pennyparse" / "user_toolbox.py"


def ensure_user_state_dir(*, home: Path | None = None) -> Path:
    state_dir = (home or Path.home()) / ".pennyparse"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def get_chat_settings() -> ChatSettings:
    section = pp_config["aigc.api.chatcomp"]
    base_url = os.getenv("PENNYPARSE_CHAT_BASE") or section.get("base") or "http://localhost:8080/v1"
    if base_url == "https://example.com/v1":
        base_url = "http://localhost:8080/v1"

    api_key = (
        os.getenv("PENNYPARSE_CHAT_AUTHKEY")
        or os.getenv("OPENAI_API_KEY")
        or section.get("authkey")
        or None
    )
    if api_key == "sk-example":
        api_key = None

    model = os.getenv("PENNYPARSE_CHAT_MODEL") or section.get("model") or None
    return {"base_url": base_url, "api_key": api_key, "model": model}


def inject_prompt_context(template: str, context: Mapping[str, str]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"${{{key}}}", value)
    return rendered
