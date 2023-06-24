import argparse
import os
import pathlib
from typing import Any, Optional, List

from aiohttp import web
import configargparse
import argparse


PATH = pathlib.Path(__file__).parent.parent.parent
# settings_file = os.environ.get('SETTINGS_FILE', 'api.dev.yml')
DEFAULT_CONFIG_PATH = PATH / "config.yml"

p = configargparse.ArgParser(default_config_files=[DEFAULT_CONFIG_PATH],
                             config_file_parser_class=configargparse.YAMLConfigFileParser)
p.add_argument("-c", "--config-file", is_config_file=True, help="Config file path")
p.add_argument("-l", "--listen", type=str, default="127.0.0.1")
p.add_argument("-p", "--port", type=int, default=7779)
p.add_argument("--model-paths", type=str, nargs="+")


def get_config(argv):
    if argv[0].endswith("adev"):
        argv = []

    config = p.parse_args(argv)

    return config
