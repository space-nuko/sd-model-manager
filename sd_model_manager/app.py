from pathlib import Path
from typing import (
    Optional,
    List,
    AsyncGenerator,
)

import aiohttp_jinja2
from aiohttp import web
import jinja2

from sd_model_manager.routes import init_routes


path = Path(__file__).parent


def init_jinja2(app: web.Application) -> None:
    """
    Initialize jinja2 template for application.
    """
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(str(path / "templates")))


def init_app(argv: Optional[List[str]] = None) -> web.Application:
    app = web.Application()

    init_jinja2(app)
    # init_config(app, argv=argv)
    init_routes(app)

    return app
