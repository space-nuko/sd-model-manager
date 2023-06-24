#!/usr/bin/env python

import os
import pathlib
import wx
import wx.aui
import wx.lib.newevent
from wx.lib.agw import ultimatelistctrl
import wx.lib.mixins.listctrl as listmix
import wxasync
import asyncio
import aiohttp
from aiohttp import web
from pubsub import pub

from main import create_app
from sd_model_manager.utils.common import get_config

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
            async with session.get(self.base_url() + "/api/v1/loras", params={"limit": 20}) as response:
                return await response.json()

class ResultsPanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.results = []

        wx.Panel.__init__(self, *args, **kwargs)

        self.list = wx.lib.agw.ultimatelistctrl.UltimateListCtrl(self, agwStyle=wx.LC_REPORT|wx.LC_HRULES|wx.LC_VRULES|ultimatelistctrl.ULC_SHOW_TOOLTIPS)

        self.button = wx.Button(self, label="Test")
        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnSearch, self.button)

        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnListItemSelected, self.list)
        self.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.OnListItemDeselected, self.list)
        self.Bind(wx.EVT_LIST_DELETE_ALL_ITEMS, self.OnListItemDeselected, self.list)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.sizer.Add(self.button, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    async def search(self, query):
        self.list.ClearAll()
        self.list.InsertColumn(0, "ID")
        self.list.InsertColumn(1, "Filename")
        self.list.InsertColumn(2, "Filepath")
        self.list.SetColumnWidth(2, ultimatelistctrl.ULC_AUTOSIZE_FILL)
        self.list.Arrange(ultimatelistctrl.ULC_ALIGN_DEFAULT)

        self.results = await self.app.api.get_loras()

        for model in self.results["data"]:
            filepath = model["filepath"]
            item = self.list.Append([str(model["id"]), os.path.basename(filepath), filepath])
            self.list.SetItemPyData(item, model)

        self.sizer.Layout()

        if self.results:
            self.list.Select(0, 1)
            self.list.Focus(0)
        else:
            self.list.Select(0, 0)

    async def OnSearch(self, evt):
        await self.app.frame.search("test")

    def OnListItemSelected(self, evt):
        data = self.list.GetItemPyData(evt.GetIndex())
        pub.sendMessage("item_selected", item=data)

    def OnListItemDeselected(self, evt):
        pub.sendMessage("item_selected", item=None)

class PropertiesPanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.roots = []

        wx.Panel.__init__(self, *args, **kwargs)

        pub.subscribe(self.SubItemSelected, "item_selected")

        self.ctrls = {}

        self.text_name = wx.TextCtrl(self)
        self.text_author = wx.TextCtrl(self)

        self.ctrls["display_name"] = self.text_name
        self.ctrls["author"] = self.text_author

        self.SubItemSelected(None)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(wx.StaticText(self, label="Name"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.text_name, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(wx.StaticText(self, label="Author"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.text_author, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        self.SetSizerAndFit(self.sizer)

    def SubItemSelected(self, item):
        if item is None:
            for ctrl in self.ctrls.values():
                ctrl.SetEditable(False)
                ctrl.Clear()
        else:
            for name, ctrl in self.ctrls.items():
                ctrl.SetEditable(True)
                value = item.get(name)
                if value:
                    ctrl.ChangeValue(str(value))
                else:
                    ctrl.Clear()

class FilePanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.roots = []

        wx.Panel.__init__(self, *args, **kwargs)

        icon_size = (16, 16)
        self.icons = wx.ImageList(icon_size[0], icon_size[1])

        self.icon_folder_closed = self.icons.Add(wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, icon_size))
        self.icon_folder_open = self.icons.Add(wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN, wx.ART_OTHER, icon_size))
        self.icon_file = self.icons.Add(wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, icon_size))

        self.dir_tree = wx.TreeCtrl(self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TR_HAS_BUTTONS)
        self.button = wx.Button(self, label="Test")

        pub.subscribe(self.SubSearchFinished, "search_finished")

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.dir_tree, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.sizer.Add(self.button, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    def SubSearchFinished(self, results):
        self.dir_tree.DeleteAllItems()
        self.roots = []

        roots = set()
        for result in results["data"]:
            roots.add(result["root_path"])

        for root in list(roots):
            self.roots.append(self.dir_tree.AddRoot(root))

        def find(root, name):
            item, cookie = self.dir_tree.GetFirstChild(root)

            while item.IsOk():
                if self.dir_tree.GetItemText(item) == name:
                    return item
                item, cookie = self.dir_tree.GetNextChild(root, cookie)
            return None

        for result in results["data"]:
            filepath = result["filepath"]
            path = pathlib.Path(filepath)

            root = next(r for r in self.roots if self.dir_tree.GetItemText(r) == result["root_path"])
            for i, part in enumerate(path.parts):
                exist = find(root, part)
                if exist:
                    root = exist
                else:
                    root = self.dir_tree.AppendItem(root, part)

                    is_file = i == len(path.parts) - 1
                    if is_file:
                        self.dir_tree.SetItemImage(root, self.icon_file, wx.TreeItemIcon_Normal)
                    else:
                        self.dir_tree.SetItemImage(root, self.icon_folder_closed, wx.TreeItemIcon_Normal)
                        self.dir_tree.SetItemImage(root, self.icon_folder_open, wx.TreeItemIcon_Expanded)

        self.dir_tree.ExpandAll()


class MainWindow(wx.Frame):
    def __init__(self, app, *args, **kwargs):
        wx.Frame.__init__(self, *args, **kwargs)

        self.app = app

        self.aui_mgr = wx.aui.AuiManager(self)
        self.aui_mgr.SetManagedWindow(self)

        self.results_panel = ResultsPanel(self, app=self.app)
        self.aui_mgr.AddPane(self.results_panel, wx.aui.AuiPaneInfo().Center().CloseButton(False).MinSize(300, 300))

        # self.file_panel = FilePanel(self, app=self.app)
        # self.aui_mgr.AddPane(self.file_panel, wx.aui.AuiPaneInfo().Left().CloseButton(False).MinSize(250, 250))

        self.properties_panel = PropertiesPanel(self, app=self.app)
        self.aui_mgr.AddPane(self.properties_panel, wx.aui.AuiPaneInfo().Left().CloseButton(False).MinSize(250, 250))

        self.aui_mgr.Update()

        self.statusbar = self.CreateStatusBar(1)

        self.Show()

    async def search(self, query):
        self.statusbar.SetStatusText("Searching...")

        await self.results_panel.search(query)

        results = self.results_panel.results

        self.statusbar.SetStatusText(f"Done. ({len(results)} records)")

        pub.sendMessage("search_finished", results=results)


class App(wxasync.WxAsyncApp):
    def __init__(self, server, config, *args, **kwargs):
        self.server = server
        self.title = "sd-model-manager"
        self.api = API(config)

        wxasync.WxAsyncApp.__init__(self, *args, **kwargs)


    def OnInit(self):
        self.frame = MainWindow(self, None, -1, self.title, size=(800, 600))
        self.frame.Show()
        self.SetTopWindow(self.frame)

        wxasync.StartCoroutine(self.on_init_callback, self.frame)

        return True

    async def on_init_callback(self):
        await self.frame.search("lora")


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


if __name__ == '__main__':
    asyncio.run(main())
