#!/usr/bin/env python

import os
import pathlib
import subprocess
import wx
import wx.aui
import wx.lib.newevent
from wx.lib.agw import ultimatelistctrl
from dataclasses import dataclass
import wx.lib.mixins.listctrl as listmix
import wxasync
import asyncio
import aiohttp
import aiopubsub
import simplejson
from PIL import Image
from aiohttp import web
from aiopubsub import Key
from typing import Callable
from ast import literal_eval as make_tuple
from main import create_app
from sd_model_manager.utils.common import get_config
from gui.image_panel import ImagePanel

hub = aiopubsub.Hub()

def open_on_file(path):
    path = os.path.realpath(path)

    if os.name == 'nt':
        explorer = os.path.join(os.getenv('WINDIR'), 'explorer.exe')
        subprocess.run([explorer, '/select,', path])
    else:
        os.startfile(os.path.dirname(path))

def find_image(item, search_folder=False):
    def try_load(file):
        if not os.path.isfile(file):
            return None
        try:
            image = Image.open(file)
            image.load()
            width, height = image.size
            return wx.Bitmap.FromBuffer(width, height, image.tobytes())
        except Exception as ex:
            return None

    path = os.path.dirname(os.path.join(item["root_path"], item["filepath"]))
    basename = os.path.splitext(os.path.basename(item["filepath"]))[0]

    for s in [".preview.png", ".png"]:
        file = os.path.join(path, basename + s)
        image = try_load(file)
        if image:
            return image, file

    for fname in os.listdir(path):
        file = os.path.realpath(os.path.join(path, fname))
        if basename in file:
            image = try_load(file)
            if image:
                return image, file
    return None, None

class API:
    def __init__(self, config):
        self.config = config

    def base_url(self):
        host = self.config.listen
        if host == "0.0.0.0":
            host = "localhost"
        return f"http://{host}:{self.config.port}"

    async def get_loras(self, query):
        params = {
            "limit": 300
        }
        if query:
            params["query"] = query

        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url() + "/api/v1/loras", params=params) as response:
                if response.status != 200:
                    print(await response.text())
                return await response.json()

    async def update_lora(self, id, changes):
        async with aiohttp.ClientSession() as session:
            async with session.patch(self.base_url() + f"/api/v1/lora/{id}", data=simplejson.dumps({"changes": changes})) as response:
                return await response.json()

class ColumnInfo:
    name: str
    callback: Callable
    width: int

    def __init__(self, name, callback, width=None):
        self.name = name
        self.callback = callback
        self.width = width

def format_resolution(tuple_str):
    try:
        t = make_tuple(tuple_str)
        if isinstance(t, [int, float]):
            return f"{t}px"
        elif isinstance(t, tuple):
            return f"{t[0]}px"
    except:
        return tuple_str

def get_unique_tags(item):
    if not item["tag_frequency"]:
        return None

    tags = set()

    for k, v in item["tag_frequency"].items():
        for t in v:
            tags.add(t)

    return len(tags)

COLUMNS = [
    # ColumnInfo("ID", lambda m: m["id"]),
    ColumnInfo("Has Image", lambda m: "★" if find_image(m)[0] is not None else "", width=20),
    ColumnInfo("Filename", lambda m: os.path.basename(m["filepath"]), width=240),
    ColumnInfo("Name", lambda m: m["display_name"]),
    ColumnInfo("Author", lambda m: m["author"]),
    ColumnInfo("Rating", lambda m: m["rating"]),

    ColumnInfo("Module", lambda m: m["network_module"]),
    ColumnInfo("Dim.", lambda m: m["network_dim"], width=40),
    ColumnInfo("Alpha", lambda m: int(m["network_alpha"] or 0), width=40),
    ColumnInfo("Resolution", lambda m: format_resolution(m["resolution"])),
    ColumnInfo("Unique Tags", get_unique_tags),
    ColumnInfo("Learning Rate", lambda m: m["learning_rate"]),
    ColumnInfo("UNet LR", lambda m: m["unet_lr"]),
    ColumnInfo("Text Encoder LR", lambda m: m["text_encoder_lr"]),
    ColumnInfo("# Train Images", lambda m: m["num_train_images"]),
    ColumnInfo("# Reg Images", lambda m: m["num_reg_images"]),
    ColumnInfo("# Batches/Epoch", lambda m: m["num_batches_per_epoch"]),
    ColumnInfo("# Epochs", lambda m: m["num_epochs"]),
    ColumnInfo("Epoch", lambda m: m["epoch"]),
    ColumnInfo("Total Batch Size", lambda m: m["total_batch_size"]),
    ColumnInfo("Filepath", lambda m: os.path.join(m["root_path"], m["filepath"]), width=600),
]

class ResultsListCtrl(ultimatelistctrl.UltimateListCtrl):
    def __init__(self, parent):
        ultimatelistctrl.UltimateListCtrl.__init__(self, parent, -1,
                                                   agwStyle=ultimatelistctrl.ULC_VIRTUAL|ultimatelistctrl.ULC_REPORT|wx.LC_HRULES|wx.LC_VRULES|ultimatelistctrl.ULC_SHOW_TOOLTIPS)

        self.results = []
        self.text = {}

        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnListItemSelected)
        self.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.OnListItemDeselected)
        self.Bind(wx.EVT_LIST_DELETE_ALL_ITEMS, self.OnListItemDeselected)
        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.OnListItemRightClicked)

        self.pub = aiopubsub.Publisher(hub, Key("events"))

    def OnGetItemText(self, item, col):
        if not self.results:
            return ""

        return self.text[col][item]

    def set_results(self, results):
        self.results = results
        self.text = {}

        self.refresh_text()

    def refresh_text(self):
        self.text = {}
        for i, data in enumerate(self.results["data"]):
            data["_index"] = i
            self.refresh_one_text(data)

    def refresh_one_text(self, data):
        i = data["_index"]
        for col, column in enumerate(COLUMNS):
            text = str(column.callback(data))
            if col not in self.text:
                self.text[col] = {}
            self.text[col][i] = text

    def OnGetItemColumnImage(self, item, col):
        return []

    def OnGetItemImage(self, item):
        return []

    def OnGetItemAttr(self, item):
        return None

    def OnGetItemTextColour(self, item, col):
        return None

    def OnGetItemToolTip(self, item, col):
        return None

    def OnGetItemKind(self, item):
        return 0

    def OnGetItemColumnKind(self, item, col):
        return 0

    def OnListItemSelected(self, evt):
        index = evt.GetIndex()
        data = self.results["data"][index]
        self.pub.publish(Key("item_selected"), data)

    def OnListItemDeselected(self, evt):
        self.pub.publish(Key("item_selected"), None)

    def OnListItemRightClicked(self, evt):
        i = self.GetFirstSelected()
        while i != -1:
            self.Select(i, 0)
            i = self.GetNextSelected(i)
        self.Select(evt.GetIndex())

        target = self.results["data"][evt.GetIndex()]

        menu = PopupMenu(target=target, items=[
            PopupMenuItem("Open Folder", self.open_folder)
        ])
        pos = evt.GetPoint()
        self.PopupMenu(menu, pos)
        menu.Destroy()

    def open_folder(self, target):
        path = os.path.join(target["root_path"], target["filepath"])
        open_on_file(path)

class ResultsPanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.results = []

        wx.Panel.__init__(self, *args, **kwargs)

        self.list = ResultsListCtrl(self)

        for i, column in enumerate(COLUMNS):
            self.list.InsertColumn(i, column.name)
            if column.width is not None:
                self.list.SetColumnWidth(i, column.width)

        self.search_box = wx.TextCtrl(self, wx.ID_ANY, style=wx.TE_PROCESS_ENTER)
        self.button = wx.Button(self, label="Search")

        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnSearch, self.button)
        wxasync.AsyncBind(wx.EVT_TEXT_ENTER, self.OnSearch, self.search_box)

        self.sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer2.Add(self.search_box, proportion=5, flag=wx.LEFT | wx.EXPAND | wx.ALL, border=5)
        self.sizer2.Add(self.button, proportion=1, flag=wx.ALL, border=5)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.sizer.Add(self.sizer2, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    async def search(self, query):
        self.list.DeleteAllItems()
        self.list.Arrange(ultimatelistctrl.ULC_ALIGN_DEFAULT)

        results = await self.app.api.get_loras(query)
        self.list.set_results(results)

        self.app.frame.statusbar.SetStatusText("Loading results...")

        self.list.SetItemCount(len(self.list.results["data"]))

        self.sizer.Layout()

        if len(self.list.results["data"]) > 0:
            self.list.Select(0, 1)
            self.list.Focus(0)

    async def OnSearch(self, evt):
        await self.app.frame.search(self.search_box.GetValue())

@dataclass
class PopupMenuItem:
    title: str
    callback: Callable

class PopupMenu(wx.Menu):
    def __init__(self, *args, target=None, items=None, **kwargs):
        wx.Menu.__init__(self, *args, **kwargs)
        self.target = target
        self.items = {}
        self.order = []

        for item in items:
            id = wx.NewIdRef(count=1)
            self.order.append(id)
            self.items[id] = item

        for id in self.order:
            item = self.items[id]
            self.Append(id, item.title)
            self.Bind(wx.EVT_MENU, self.OnMenuSelection, id=id)

    def OnMenuSelection(self, event):
        item = self.items[event.GetId()]
        item.callback(self.target)

class PropertiesPanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.roots = []

        wx.Panel.__init__(self, *args, **kwargs)

        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "item_selected"), self.SubItemSelected)

        self.ctrls = {}

        self.selected_item = None
        self.changes = {}
        self.values = {}

        self.text_name = wx.TextCtrl(self)
        self.text_author = wx.TextCtrl(self)

        self.ctrls["display_name"] = (self.text_name, wx.StaticText(self, label="Name"))
        self.ctrls["author"] = (self.text_author, wx.StaticText(self, label="Author"))

        def handler(key, ctrl, label, evt):
            value = evt.GetString()
            if key in self.values and value != self.values[key]:
                self.app.frame.toolbar.EnableTool(wx.ID_SAVE, True)
                self.changes[key] = value
                text = label.GetLabel()
                if not text.endswith("*"):
                    label.SetLabel(text + "*")
            self.values[key] = value

        for key, (ctrl, label) in self.ctrls.items():
            ctrl.Bind(wx.EVT_TEXT, lambda evt, key=key, ctrl=ctrl, label=label: handler(key, ctrl, label, evt))

        self.text_filename = wx.TextCtrl(self)
        self.image_view = ImagePanel(self, style=wx.SUNKEN_BORDER, size=(450, 450))
        self.text_preview_image = wx.TextCtrl(self)
        self.text_preview_image.SetEditable(False)

        self.other_ctrls = {}
        self.other_ctrls["filename"] = self.text_filename
        self.other_ctrls["image"] = self.image_view
        self.other_ctrls["preview_image"] = self.text_preview_image

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(wx.StaticText(self, label="Filename"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.text_filename, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        self.sizer.Add(self.ctrls["display_name"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["display_name"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["author"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["author"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        self.sizer.Add(self.image_view, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(wx.StaticText(self, label="Preview Image"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.text_preview_image, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        self.SetSizerAndFit(self.sizer)

    def clear_changes(self):
        self.values = {}
        for key, (ctrl, label) in self.ctrls.items():
            label.SetLabel(label.GetLabel().rstrip("*"))
            self.values[key] = ctrl.GetValue()

        self.changes = {}

        self.app.frame.toolbar.EnableTool(wx.ID_SAVE, False)

    async def commit_changes(self):
        if not self.changes:
            return

        for ctrl_name, new_value in self.changes.items():
            changes = {}
            if ctrl_name in self.ctrls:
                changes[ctrl_name] = new_value
            elif ctrl_name in self.other_ctrls:
                changes[ctrl_name] = new_value

            self.selected_item[ctrl_name] = new_value

        count = 0
        updated = 0
        progress = wx.ProgressDialog("Saving", "Saving changes...", parent=self.app.frame,
                                     maximum=1, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)

        result = await self.app.api.update_lora(self.selected_item["id"], changes)
        count += 1
        updated += result['fields_updated']
        progress.Update(count, f"{count}/1")

        self.app.frame.results_panel.list.refresh_one_text(self.selected_item)

        progress.Destroy()
        self.app.frame.statusbar.SetStatusText(f"Updated {updated} fields")

        self.clear_changes()

    async def prompt_commit_changes(self):
        if self.selected_item is None:
            self.changes = {}
            return

        if self.changes:
            dlg = wx.MessageDialog(None, "You have unsaved changes, would you like to commit them?",'Updater',wx.YES_NO | wx.ICON_QUESTION)
            result = dlg.ShowModal()
            if result == wx.ID_YES:
                await self.commit_changes()

    async def SubItemSelected(self, key, item):
        await self.prompt_commit_changes()

        self.selected_item = item

        if item is None:
            for (ctrl, label) in self.ctrls.values():
                ctrl.SetEditable(False)
                ctrl.Clear()
            for ctrl in self.other_ctrls.values():
                ctrl.Clear()
        else:
            for name, (ctrl, label) in self.ctrls.items():
                ctrl.SetEditable(True)
                value = item.get(name)
                if value:
                    ctrl.ChangeValue(str(value))
                else:
                    ctrl.Clear()

            self.text_filename.ChangeValue(os.path.basename(item["filepath"]))

            image, path = find_image(item, search_folder=True)
            if image:
                self.image_view.LoadBitmap(image)
                self.text_preview_image.ChangeValue(path)
            else:
                self.image_view.Clear()
                self.text_preview_image.Clear()

        self.clear_changes()

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

        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "search_finished"), self.SubSearchFinished)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.dir_tree, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    async def SubSearchFinished(self, key, results):
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

        self.menu_file = wx.Menu()
        self.menu_file.Append(wx.ID_OPEN, "Open", "Open")
        self.menu_file.Append(wx.ID_SAVE, "Save", "Save")
        self.menu_file.Append(wx.ID_ABOUT, "About", "About")
        self.menu_file.Append(wx.ID_EXIT, "Exit", "Close")

        self.menu_bar = wx.MenuBar()
        self.menu_bar.Append(self.menu_file, "File")
        self.SetMenuBar(self.menu_bar)

        icon_size = (24, 24)
        self.toolbar = self.CreateToolBar()
        self.tool_save = self.toolbar.AddTool(wx.ID_SAVE, "Save",
                                              wx.ArtProvider.GetBitmap(wx.ART_FILE_SAVE, wx.ART_OTHER, icon_size),
                                              wx.NullBitmap, wx.ITEM_NORMAL, 'Save', "Long help for 'Save'.", None)
        self.toolbar.Realize()

        self.toolbar.EnableTool(wx.ID_SAVE, False)

        wxasync.AsyncBind(wx.EVT_TOOL, self.OnSave, self, id=wx.ID_SAVE)

        # self.aui_mgr.AddPane(self.toolbar, wx.aui.AuiPaneInfo().
        #                      Name("Toolbar").CaptionVisible(False).
        #                      ToolbarPane().Top().CloseButton(False).
        #                      DockFixed(True).Floatable(False).
        #                      LeftDockable(False).RightDockable(False))

        self.results_panel = ResultsPanel(self, app=self.app)
        self.aui_mgr.AddPane(self.results_panel, wx.aui.AuiPaneInfo().Center().CloseButton(False).MinSize(300, 300))

        self.file_panel = FilePanel(self, app=self.app)
        self.aui_mgr.AddPane(self.file_panel, wx.aui.AuiPaneInfo().Right().CloseButton(False).MinSize(250, 250))

        self.properties_panel = PropertiesPanel(self, app=self.app)
        self.aui_mgr.AddPane(self.properties_panel, wx.aui.AuiPaneInfo().Left().CloseButton(False).MinSize(250, 250))

        self.aui_mgr.Update()

        self.statusbar = self.CreateStatusBar(1)

        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "item_selected"), self.SubItemSelected)
        self.pub = aiopubsub.Publisher(hub, Key("events"))

        self.Show()

    async def OnSave(self, evt):
        await self.properties_panel.commit_changes()

    async def SubItemSelected(self, key, item):
        self.toolbar.EnableTool(wx.ID_SAVE, False)

    async def search(self, query):
        self.statusbar.SetStatusText("Searching...")

        await self.results_panel.search(query)

        results = self.results_panel.list.results

        self.statusbar.SetStatusText(f"Done. ({len(results['data'])} records)")

        self.pub.publish(Key("search_finished"), results)


class App(wxasync.WxAsyncApp):
    def __init__(self, server, config, *args, **kwargs):
        self.server = server
        self.title = "sd-model-manager"
        self.api = API(config)

        wxasync.WxAsyncApp.__init__(self, *args, **kwargs)

    def OnInit(self):
        self.frame = MainWindow(self, None, -1, self.title, size=(1200, 800))
        self.frame.Show()
        self.SetTopWindow(self.frame)

        wxasync.StartCoroutine(self.on_init_callback, self.frame)

        return True

    async def on_init_callback(self):
        await self.frame.search("")


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
