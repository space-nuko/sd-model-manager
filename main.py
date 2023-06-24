#!/usr/bin/env python

from aiohttp import web
import aiohttp_debugtoolbar
from sd_model_manager.app import init_app
from sd_model_manager.db import DB
from sd_model_manager.utils.common import get_config
import sys


async def create_app() -> web.Application:
    app = init_app()
    app["config"] = get_config(sys.argv)

    db = DB()
    await db.init()
    await db.scan(app["config"].model_paths)

    app["db"] = db

    aiohttp_debugtoolbar.setup(app, check_host=False)

    return app


def main() -> None:
    app = init_app()
    host = app["config"].host
    port = app["config"].port
    web.run_app(app, host=host, port=port)


if __name__ == '__main__':
    main()
