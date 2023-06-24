#!/usr/bin/env python

from aiohttp import web
import aiohttp_debugtoolbar
from sd_model_manager.app import init_app


def create_app() -> web.Application:
    app = init_app()
    aiohttp_debugtoolbar.setup(app, check_host=False)

    return app


def main() -> None:
    app = init_app()
    host = "0.0.0.0"
    port = 7779
    web.run_app(app, host=host, port=port)


if __name__ == '__main__':
    main()
