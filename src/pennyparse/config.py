import os
import re
import configparser
from pathlib import Path
import importlib.resources

PENNYPARSE_HOST=os.getenv("PENNYPARSE_HOST", "0.0.0.0")
PENNYPARSE_PORT=int(os.getenv("PENNYPARSE_HOST", 52026))

_protocol="http" if PENNYPARSE_HOST == "localhost" or re.match(r"^\d+\.\d+\.\d+\.\d+$", PENNYPARSE_HOST) else "https"
PENNYPARSE_BASE=f"{_protocol}://{PENNYPARSE_HOST}:{PENNYPARSE_PORT}"

pp_config = configparser.ConfigParser()
with importlib.resources.as_file(
    importlib.resources.files('pennyparse') / 'pennyparse.settings.default.ini'
) as default_path:
    pp_config.read(str(default_path))

_user_cfg = Path.home() / '.pennyparse' / 'pennyparse.settings.ini'
_local_cfg = Path.cwd() / 'pennyparse.settings.ini'
for cfg in (_user_cfg, _local_cfg):
    if cfg.exists():
        pp_config.read(str(cfg))
