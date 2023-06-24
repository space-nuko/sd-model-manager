#!/usr/bin/env python

import os
import wx
import wx.lib.mixins.listctrl as listmix
import wxasync
import asyncio
import aiohttp
from aiohttp import web
from main import create_app

class TestListCtrl(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
    def __init__(self, *args, **kwargs):
        wx.ListCtrl.__init__(self, *args, **kwargs)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        self.setResizeColumn(3)

    def OnCheckItem(self, index, flag):
        print(index, flag)

class API:
    def __init__(self, config):
        self.config = config

    def base_url(self):
        host = self.config.listen
        if host == "0.0.0.0":
            host = "localhost"
        return f"http://{host}:{self.config.port}"

    async def get_loras(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url() + "/api/v1/loras") as response:
                return await response.json()

class MainWindow(wx.Frame):
    def __init__(self, app, *args, **kwargs):
        wx.Frame.__init__(self, *args, **kwargs)

        self.app = app
        self.api = API(app.server["config"])

        self.panel = wx.Panel(self)

        self.list = TestListCtrl(self.panel, style=wx.LC_REPORT)

        self.button = wx.Button(self.panel, label="Test")
        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnSearch, self.button)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.sizer.Add(self.button, flag=wx.EXPAND | wx.ALL, border=5)

        self.panel.SetSizerAndFit(self.sizer)

        self.statusbar = self.CreateStatusBar(1)

        self.Show()

    async def search(self, query):
        self.list.ClearAll()
        self.list.InsertColumn(0, "ID")
        self.list.InsertColumn(1, "Filename")
        self.list.InsertColumn(2, "Filepath")
        self.list.Arrange()

        self.statusbar.SetStatusText("Searching...")

        results = await self.api.get_loras()

        for model in results["data"]:
            filepath = model["filepath"]
            self.list.Append([model["id"], os.path.basename(filepath), filepath])

        self.sizer.Layout()

        self.statusbar.SetStatusText(f"Done. ({len(results['data'])} records)")

    async def OnSearch(self, evt):
        await self.search("test")


class App(wxasync.WxAsyncApp):
    def __init__(self, server, *args, **kwargs):
        self.server = server
        self.title = "sd-model-manager"

        wxasync.WxAsyncApp.__init__(self, *args, **kwargs)


    def OnInit(self):
        self.frame = MainWindow(self, None, -1, self.title, size=(800, 600))
        self.frame.Show()
        self.SetTopWindow(self.frame)

        wxasync.StartCoroutine(self.on_init_callback, self.frame)

        return True

    async def on_init_callback(self):
        await self.frame.search("lora")


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
    server = await init_server()
    app = App(server, redirect=False)
    await app.MainLoop()


if __name__ == '__main__':
    asyncio.run(main())
