#!/usr/bin/env python

import sys
import ctypes
import asyncio
import argparse
import traceback
from aiohttp import web

import wx

from main import create_app
from sd_model_manager.utils.common import get_config
from gui.app import App

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(True)
except:
    pass


parser = argparse.ArgumentParser()
parser.add_argument(
    "-l",
    "--listen",
    type=str,
    default="127.0.0.1",
    help="Address for model manager server",
)
parser.add_argument("-p", "--port", type=int, help="Port for model manager server")
parser.add_argument(
    "-m",
    "--mode",
    type=str,
    default="standalone",
    help="Runtime mode ('standalone', 'noserver', 'comfyui')",
)


async def init_server():
    server = await create_app([])
    host = server["config"].listen
    port = server["config"].port

    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    return server


app = None


def exception_handler(exception_type, exception_value, exception_traceback):
    global app
    msg = "An error has occurred!\n\n"
    tb = traceback.format_exception(
        exception_type, exception_value, exception_traceback
    )
    for i in tb:
        msg += i

    parent = None
    if app is not None:
        parent = app.frame
    dlg = wx.MessageDialog(parent, msg, str(exception_type), wx.OK | wx.ICON_ERROR)
    dlg.ShowModal()
    dlg.Destroy()


async def main():
    global app
    config = parser.parse_args()
    use_internal_server = config.mode != "noserver" and config.mode != "comfyui"
    is_comfyui = config.mode == "comfyui"

    if config.port is None:
        config.port = 8188 if is_comfyui else 7779

    server = None
    if use_internal_server:
        server = await init_server()

    app = App(server, config, redirect=False)
    sys.excepthook = exception_handler
    await app.MainLoop()


if __name__ == "__main__":
    asyncio.run(main())
