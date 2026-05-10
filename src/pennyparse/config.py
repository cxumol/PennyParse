import importlib.resources
import os
import tomllib
import string
from pathlib import Path
from typing import Any, Mapping, TypedDict

from dotenv import load_dotenv

_DEFAULT_SETTINGS_TOML = "pennyparse.settings.default.toml"
PENNYPARSE_CHAT_ENV_NAMES = (
    "PENNYPARSE_CHAT_BASE",
    "PENNYPARSE_CHAT_AUTHKEY",
    "PENNYPARSE_CHAT_MODEL",
)
PENNYPARSE_CHAT_ENV_REMINDER = (
    "PENNYPARSE_CHAT_* needs to be configured by the user; "
    "otherwise PennyParse may not work correctly."
)


def read_package_text(filename: str) -> str:
    resource = importlib.resources.files("pennyparse") / filename
    return resource.read_text(encoding="utf-8")


def read_package_toml(filename: str) -> dict[str, Any]:
    return tomllib.loads(read_package_text(filename))


def _deep_merge(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(left)
    for key, value in right.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}

    base = os.getenv(PENNYPARSE_CHAT_ENV_NAMES[0])
    authkey = os.getenv(PENNYPARSE_CHAT_ENV_NAMES[1]) or os.getenv("OPENAI_API_KEY")
    model = os.getenv(PENNYPARSE_CHAT_ENV_NAMES[2])
    if base or authkey or model:
        overrides = _deep_merge(
            overrides,
            {
                "aigc": {
                    "api": {
                        "chatcomp": {
                            **({"base": base} if base else {}),
                            **({"authkey": authkey} if authkey else {}),
                            **({"model": model} if model else {}),
                        }
                    }
                }
            },
        )

    host = os.getenv("PENNYPARSE_HOST")
    port = os.getenv("PENNYPARSE_PORT")
    if host or port:
        web_overrides: dict[str, Any] = {"web": {}}
        if host:
            web_overrides["web"]["host"] = host
        if port:
            web_overrides["web"]["port"] = int(port)
        overrides = _deep_merge(overrides, web_overrides)

    cli_timeout = os.getenv("PENNYPARSE_CLI_TIMEOUT")
    if cli_timeout:
        overrides = _deep_merge(overrides, {"cli": {"timeout": int(cli_timeout)}})

    return overrides


def has_pennyparse_chat_env() -> bool:
    return any(os.getenv(name) for name in PENNYPARSE_CHAT_ENV_NAMES)


def load_pp_config(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    argv_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    load_dotenv((cwd or Path.cwd()) / ".env", override=False)
    base = read_package_toml(_DEFAULT_SETTINGS_TOML)
    home_cfg = _read_toml_file((home or Path.home()) / ".pennyparse" / "pennyparse.settings.toml")
    local_cfg = _read_toml_file((cwd or Path.cwd()) / "pennyparse.settings.toml")

    merged = _deep_merge(base, home_cfg)
    merged = _deep_merge(merged, local_cfg)

    if argv_overrides is not None:
        if _env_overrides():
            raise RuntimeError("config override source must be either env vars or argv, not both")
        merged = _deep_merge(merged, argv_overrides)
        return merged

    return _deep_merge(merged, _env_overrides())


def _coerce_web_setting(pp_cfg: Mapping[str, Any], key: str) -> Any:
    web = pp_cfg.get("web")
    if isinstance(web, Mapping):
        return web.get(key)
    return None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def get_init_ignore_config(pp_cfg: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    ignore = _as_mapping(_as_mapping(pp_cfg.get("init")).get("ignore"))
    ignore_ext = {str(item).lstrip(".").lower() for item in (ignore.get("ext") or [])}
    ignore_folder = {str(item) for item in (ignore.get("folder") or [])}
    return ignore_ext, ignore_folder


class ChatSettings(TypedDict):
    base_url: str
    api_key: str | None
    model: str | None


pp_config = load_pp_config()

_host = _coerce_web_setting(pp_config, "host")
if not isinstance(_host, str) or not _host.strip():
    raise RuntimeError("web.host must be configured in pennyparse.settings.default.toml")
PENNYPARSE_HOST = _host.strip()

_port = _coerce_web_setting(pp_config, "port")
if not isinstance(_port, int):
    raise RuntimeError("web.port must be configured in pennyparse.settings.default.toml")
PENNYPARSE_PORT = int(_port)


def read_prompt_catalog() -> dict:
    return read_package_toml("pennyparse.prompt.toml")


def get_prompt_text(name: str) -> str:
    catalog = read_prompt_catalog()
    value = catalog.get(name)
    if not isinstance(value, str) or not value.strip():
        raise KeyError(f"prompt {name!r} not found in pennyparse.prompt.toml")
    return value.strip()


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
    aigc = pp_config.get("aigc")
    if not isinstance(aigc, Mapping):
        raise RuntimeError("missing [aigc] config")
    api = aigc.get("api")
    if not isinstance(api, Mapping):
        raise RuntimeError("missing [aigc.api] config")
    chat = api.get("chatcomp")
    if not isinstance(chat, Mapping):
        raise RuntimeError("missing [aigc.api.chatcomp] config")

    base_url = str(chat.get("base") or "").strip()
    if not base_url:
        raise RuntimeError("aigc.api.chatcomp.base is required")

    authkey = chat.get("authkey")
    api_key = str(authkey).strip() if authkey is not None else ""
    if not api_key:
        api_key = None

    model_value = chat.get("model")
    model = str(model_value).strip() if model_value is not None else ""
    if not model:
        model = None

    return {"base_url": base_url, "api_key": api_key, "model": model}


def inject_prompt_context(template: str, context: Mapping[str, str]) -> str:
    return string.Template(template).safe_substitute(context)
