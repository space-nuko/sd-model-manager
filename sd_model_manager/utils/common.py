import argparse
import os
import pathlib
from typing import Any, Optional, List

from aiohttp import web


PATH = pathlib.Path(__file__).parent.parent.parent
settings_file = os.environ.get('SETTINGS_FILE', 'api.dev.yml')
DEFAULT_CONFIG_PATH = PATH / 'config' / settings_file
