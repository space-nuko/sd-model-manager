#!/usr/bin/env python

from aiohttp import web
from sd_model_manager.app import init_app
from sd_model_manager.db import DB
from sd_model_manager.utils.common import get_config
import sys


async def create_app(argv=None) -> web.Application:
    app = init_app()
    if argv is None:
        argv = sys.argv
    app["sdmm_config"] = get_config(argv)

    db = DB()
    await db.init(app["sdmm_config"].model_paths)
    # await db.scan(app["sdmm_config"].model_paths)

    app["sdmm_db"] = db

    try:
        import aiohttp_debugtoolbar

        aiohttp_debugtoolbar.setup(app, check_host=False)
    except ModuleNotFoundError:
        pass

    return app


def main() -> None:
    app = init_app()
    host = app["sdmm_config"].listen
    port = app["sdmm_config"].port
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()
