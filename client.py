#!/usr/bin/env python

import ctypes
import asyncio
from aiohttp import web

import wx

from main import create_app
from sd_model_manager.utils.common import get_config
from gui.app import App

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(True)
except:
    pass


USE_INTERNAL_SERVER = True


async def init_server():
    server = await create_app([])
    host = server["config"].listen
    port = server["config"].port

    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    return server


async def main():
    if USE_INTERNAL_SERVER:
        server = await init_server()
        config = server["config"]
    else:
        server = None
        config = get_config([])
    app = App(server, config, redirect=False)
    await app.MainLoop()


if __name__ == "__main__":
    asyncio.run(main())
