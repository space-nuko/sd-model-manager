#!/usr/bin/env python

import os
import pathlib
import subprocess
import wx
import wx.aui
import wx.lib.newevent
import ctypes
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
from typing import Callable, Optional
from ast import literal_eval as make_tuple

from main import create_app
from sd_model_manager.utils.common import get_config
from sd_model_manager.utils.timer import Timer
from gui.image_panel import ImagePanel
from gui.rating_ctrl import RatingCtrl, EVT_RATING_CHANGED

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(True)
except:
    pass

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
        self.client = aiohttp.ClientSession()

    def base_url(self):
        host = self.config.listen
        if host == "0.0.0.0":
            host = "localhost"
        return f"http://{host}:{self.config.port}"

    async def get_loras(self, query):
        params = {
            "limit": 500
        }
        if query:
            params["query"] = query

        async with self.client.get(self.base_url() + "/api/v1/loras", params=params) as response:
            if response.status != 200:
                print(await response.text())
            return await response.json()

    async def update_lora(self, id, changes):
        async with self.client.patch(self.base_url() + f"/api/v1/lora/{id}", data=simplejson.dumps({"changes": changes})) as response:
            return await response.json()

class ColumnInfo:
    name: str
    callback: Callable
    width: int
    is_meta: bool
    is_visible: bool

    def __init__(self, name, callback, width=None, is_meta=False):
        self.name = name
        self.callback = callback
        self.width = width
        self.is_meta = is_meta

        self.is_visible = True

def format_resolution(tuple_str):
    try:
        t = make_tuple(tuple_str)
        if isinstance(t, [int, float]):
            return f"{t}px"
        elif isinstance(t, tuple):
            return f"{t[0]}px"
    except:
        return tuple_str

def format_rating(rating):
    if rating is None or rating <= 0:
        return ""
    rating = min(10, max(0, int(rating)))
    return u'\u2605'*int(rating/2) + u'\u00BD'*int(rating%2!=0)


MODEL_TYPES = {
    "networks.lora": "LoRA",
    "sd_scripts.networks.lora": "LoRA",
    "networks.dylora": "DyLoRA",
}


MODEL_ALGOS = {
    "lora": "LoRA",
    "locon": "LoCon",
    "lokr": "LoKR",
    "loha": "LoHa",
    "ia3": "(IA)^3",
}


def format_module(m):
    module = m["network_module"]
    if module in MODEL_TYPES:
        return MODEL_TYPES[module]

    if module == "lycoris.kohya":
        args = m.get("network_args") or {}
        algo = args.get("algo")
        return MODEL_ALGOS.get(algo, module)

    return module


COLUMNS = [
    # ColumnInfo("ID", lambda m: m["id"]),
    ColumnInfo("Has Image", lambda m: "★" if find_image(m)[0] is not None else "", width=20),
    ColumnInfo("Filename", lambda m: os.path.basename(m["filepath"]), width=240),

    ColumnInfo("Module", format_module, width=140),

    ColumnInfo("Name", lambda m: m["display_name"], is_meta=True, width=100),
    ColumnInfo("Author", lambda m: m["author"], is_meta=True, width=100),
    ColumnInfo("Rating", lambda m: format_rating(m["rating"]), is_meta=True, width=60),

    ColumnInfo("Dim.", lambda m: m["network_dim"], width=40),
    ColumnInfo("Alpha", lambda m: int(m["network_alpha"] or 0), width=40),
    ColumnInfo("Resolution", lambda m: format_resolution(m["resolution"])),
    ColumnInfo("Unique Tags", lambda m: m["unique_tags"]),
    ColumnInfo("Learning Rate", lambda m: m["learning_rate"]),
    ColumnInfo("UNet LR", lambda m: m["unet_lr"]),
    ColumnInfo("Text Encoder LR", lambda m: m["text_encoder_lr"]),
    ColumnInfo("# Train Images", lambda m: m["num_train_images"]),
    ColumnInfo("# Reg Images", lambda m: m["num_reg_images"]),
    ColumnInfo("# Batches/Epoch", lambda m: m["num_batches_per_epoch"]),
    ColumnInfo("# Epochs", lambda m: m["num_epochs"]),
    ColumnInfo("Epoch", lambda m: m["epoch"]),
    ColumnInfo("Total Batch Size", lambda m: m["total_batch_size"]),

    ColumnInfo("Tags", lambda m: m["tags"], is_meta=True, width=140),
    ColumnInfo("Keywords", lambda m: m["keywords"], is_meta=True, width=140),
    ColumnInfo("Source", lambda m: m["source"], is_meta=True, width=100),

    ColumnInfo("Filepath", lambda m: os.path.join(m["root_path"], m["filepath"]), width=600),
]

class ResultsListCtrl(ultimatelistctrl.UltimateListCtrl):
    def __init__(self, parent, app=None):
        ultimatelistctrl.UltimateListCtrl.__init__(self, parent, -1,
                                                   agwStyle=ultimatelistctrl.ULC_VIRTUAL|ultimatelistctrl.ULC_REPORT|wx.LC_HRULES|wx.LC_VRULES|ultimatelistctrl.ULC_SHOW_TOOLTIPS)

        self.app = app

        self.results = []
        self.text = {}
        self.values = {}
        self.colmap = {}
        self.clicked = False

        # EVT_LIST_ITEM_SELECTED and ULC_VIRTUAL don't mix
        # https://github.com/wxWidgets/wxWidgets/issues/4541
        self.Bind(wx.EVT_LIST_CACHE_HINT, self.OnListItemSelected)
        self.Bind(wx.EVT_LIST_DELETE_ALL_ITEMS, self.OnListItemSelected)
        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.OnListItemRightClicked)
        self.Bind(wx.EVT_LIST_COL_RIGHT_CLICK, self.OnColumnRightClicked)
        self.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)
        self.Bind(wx.EVT_KEY_UP, self.OnKeyUp)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnClick)
        self.Bind(wx.EVT_RIGHT_DOWN, self.OnClick)

        self.pub = aiopubsub.Publisher(hub, Key("events"))

        for col, column in enumerate(COLUMNS):
            self.InsertColumn(col, column.name)
            self.SetColumnShown(col, column.is_visible)

        self.refresh_columns()

    def OnKeyUp(self, evt):
        self.clicked = True
        evt.Skip()

    def OnKeyDown(self, evt):
        self.clicked = True
        evt.Skip()

    def set_results(self, results):
        self.results = results
        self.text = {}
        self.values = {}

        self.refresh_text()

    def refresh_columns(self):
        self.colmap = {}
        col = 0
        for i, column in enumerate(COLUMNS):
            if not column.is_visible:
                continue
            self.colmap[col] = i

            if column.width is not None:
                width = self.Parent.FromDIP(column.width)
            else:
                width = wx.LIST_AUTOSIZE_USEHEADER
            self.SetColumnWidth(col, width)

            c = self.GetColumn(col)
            c.SetText(column.name)
            self.SetColumn(col, c)
            col += 1

    def resize_columns(self):
        for col, realcol in self.colmap.items():
            column = COLUMNS[realcol]
            if column.width is not None:
                width = self.Parent.FromDIP(column.width)
            else:
                width = wx.LIST_AUTOSIZE_USEHEADER
            self.SetColumnWidth(col, width)

        self.Arrange(ultimatelistctrl.ULC_ALIGN_DEFAULT)

    def refresh_text(self):
        self.app.frame.statusbar.SetStatusText("Loading results...")

        self.DeleteAllItems()
        self.Refresh()

        self.text = {}
        self.values = {}
        for i, data in enumerate(self.results["data"]):
            data["_index"] = i
            self.refresh_one_text(data)

        count = len(self.results["data"])
        self.SetItemCount(count)

        self.app.frame.statusbar.SetStatusText(f"Done. ({count} records)")

        self.resize_columns()

    def refresh_one_text(self, data):
        i = data["_index"]
        for col, column in enumerate(COLUMNS):
            value = column.callback(data)
            if value is None:
                text = ""
            else:
                text = str(value)
            if col not in self.text:
                self.text[col] = {}
                self.values[col] = {}
            self.text[col][i] = text
            self.values[col][i] = value

    def get_selection(self):
        item = self.GetFirstSelected()
        num = self.GetSelectedItemCount()
        selection = [item]
        for i in range(1, num):
            item = self.GetNextSelected(item)
            selection.append(item)
        return [self.results["data"][i] for i in selection]

    def OnGetItemColumnImage(self, item, col):
        return []

    def OnGetItemImage(self, item):
        return []

    def OnGetItemAttr(self, item):
        return None

    def OnGetItemText(self, item, col):
        col = self.colmap.get(col)
        if col is None:
            return ""

        entry = self.values[col][item]
        if entry is None:
            column = COLUMNS[col]
            if not column.is_meta:
                return "(None)"

        return self.text[col][item]

    def OnGetItemTextColour(self, item, col):
        col = self.colmap.get(col)
        if col is None:
            return None

        entry = self.values[col][item]
        if entry is None:
            return "gray"
        return None

    def OnGetItemToolTip(self, item, col):
        return None

    def OnGetItemKind(self, item):
        return 0

    def OnGetItemColumnKind(self, item, col):
        return 0

    def OnClick(self, evt):
        self.clicked = True
        evt.Skip()

    def OnListItemSelected(self, evt):
        if not self.clicked:
            return

        self.clicked = False
        selection = self.get_selection()
        self.pub.publish(Key("item_selected"), selection)

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

    def OnColumnRightClicked(self, evt):
        items = []
        for i, col in enumerate(COLUMNS):
            def check(target, col=col):
                col.is_visible = not col.is_visible
                self.SetColumnShown(i, col.is_visible)
                self.refresh_columns()
            items.append(PopupMenuItem(col.name, check, checked=col.is_visible))
        menu = PopupMenu(target=self, items=items)
        pos = evt.GetPoint()
        self.PopupMenu(menu, pos)
        menu.Destroy()
        pass

class ResultsPanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.results = []

        wx.Panel.__init__(self, *args, **kwargs)

        self.list = ResultsListCtrl(self, app)

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

        self.sizer.Layout()

        if len(self.list.results["data"]) > 0:
            self.list.Select(0, 1)
            self.list.Focus(0)

    async def OnSearch(self, evt):
        await self.app.frame.search(self.search_box.GetValue())

class PopupMenuItem:
    title: str
    callback: Callable
    checked: Optional[bool]

    def __init__(self, title, callback, checked=None):
        self.title = title
        self.callback = callback
        self.checked = checked

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
            if item.checked is not None:
                self.AppendCheckItem(id, item.title)
                self.Check(id, item.checked)
            else:
                self.Append(id, item.title)
            self.Bind(wx.EVT_MENU, self.OnMenuSelection, id=id)

    def OnMenuSelection(self, event):
        item = self.items[event.GetId()]
        item.callback(self.target)

class MetadataTagsList(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
    def __init__(self, parent):
        self.tags = []

        wx.ListCtrl.__init__(self, parent, id=wx.ID_ANY, style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_HRULES | wx.LC_VRULES)
        self.EnableAlternateRowColours(True)
        self.InsertColumn(0, "Tag")
        self.setResizeColumn(0)

    def set_tags(self, tags):
        self.tags = tags
        self.Refresh()

    def Clear(self):
        self.tags = []

    def OnGetItemText(self, item, col):
        return self.tags[item]

class PreviewImagePanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.roots = []

        wx.Panel.__init__(self, *args, **kwargs)

        self.image_view = ImagePanel(self, style=wx.SUNKEN_BORDER)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.image_view, 1, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        self.SetSizerAndFit(self.sizer)

        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "item_selected"), self.SubItemSelected)

    async def SubItemSelected(self, key, items):
        image = None
        if len(items) == 1:
            image, path = find_image(items[0], search_folder=True)

        if image:
            self.image_view.LoadBitmap(image)
            # self.text_preview_image.ChangeValue(path)
        else:
            self.image_view.Clear()
            # self.text_preview_image.Clear()

class PropertiesPanel(wx.lib.scrolledpanel.ScrolledPanel):
    def __init__(self, parent, app=None):
        self.app = app
        self.roots = []

        wx.lib.scrolledpanel.ScrolledPanel.__init__(self, parent, id=wx.ID_ANY, style=wx.VSCROLL)

        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "item_selected"), self.SubItemSelected)

        self.ctrls = {}

        self.selected_items = []
        self.changes = {}
        self.values = {}
        self.is_committing = False

        ctrls = [
            ("display_name", "Name", None, None),
            ("author", "Author", None, None),
            ("source", "Source", None, None),
            ("tags", "Tags", None, None),
            ("keywords", "Keywords", wx.TE_MULTILINE, self.Parent.FromDIP(wx.Size(250, 60))),
            ("description", "Description", wx.TE_MULTILINE, self.Parent.FromDIP(wx.Size(250, 140)))
        ]

        for key, label, style, size in ctrls:
            if style is not None:
                ctrl = wx.TextCtrl(self, id=wx.ID_ANY, size=size, value="", style=style)
            else:
                choices = ["< blank >", "< keep >"]
                ctrl = wx.ComboBox(self, id=wx.ID_ANY, value="", choices=choices)
            self.ctrls[key] = (ctrl, wx.StaticText(self, label=label))

        def handler(key, label, evt):
            value = evt.GetString()
            self.modify_value(key, label, value)

        for key, (ctrl, label) in self.ctrls.items():
            ctrl.Bind(wx.EVT_TEXT, lambda evt, key=key, label=label: handler(key, label, evt))

        self.label_filename = wx.StaticText(self, label="Filename")
        self.label_rating = wx.StaticText(self, label="Rating")

        self.text_filename = wx.TextCtrl(self)
        self.text_filename.SetEditable(False)
        self.ctrl_rating = RatingCtrl(self)
        # self.text_preview_image = wx.TextCtrl(self)
        # self.text_preview_image.SetEditable(False)
        self.text_id = wx.TextCtrl(self)
        self.text_id.SetEditable(False)
        # self.list_tags = MetadataTagsList(self)

        self.other_ctrls = {}
        self.other_ctrls["filename"] = self.text_filename
        # self.other_ctrls["preview_image"] = self.text_preview_image
        self.other_ctrls["id"] = self.text_id
        self.other_ctrls["rating"] = self.ctrl_rating

        self.ctrl_rating.Bind(EVT_RATING_CHANGED, lambda evt: self.modify_value("rating", self.label_rating, evt.rating))

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.label_filename, flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.text_filename, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        self.sizer.Add(self.ctrls["display_name"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["display_name"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["author"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["author"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["source"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["source"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["tags"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["tags"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["keywords"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["keywords"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["description"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["description"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.label_rating, flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrl_rating, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        # self.sizer.Add(wx.StaticText(self, label="Preview Image"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        # self.sizer.Add(self.text_preview_image, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(wx.StaticText(self, label="ID"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.text_id, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        # self.sizer.Add(wx.StaticText(self, label="Tags"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        # self.sizer.Add(self.list_tags, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        sizer = wx.WrapSizer()
        sizer.Add(self.sizer)
        self.SetSizerAndFit(sizer)
        self.SetupScrolling(scroll_x=False)
        self.Bind(wx.EVT_SIZE, self.OnSize)

    def modify_value(self, key, label, value):
        if key in self.values and value != self.values[key]:
            self.app.frame.toolbar.EnableTool(wx.ID_SAVE, True)
            self.changes[key] = value
            text = label.GetLabel()
            if not text.endswith("*"):
                label.SetLabel(text + "*")
        self.values[key] = value

    def OnSize(self, evt):
        size = self.GetSize()
        vsize = self.GetVirtualSize()
        self.SetVirtualSize((size[0], vsize[1]))

        evt.Skip()

    def clear_changes(self):
        self.values = {}
        for key, (ctrl, label) in self.ctrls.items():
            label.SetLabel(label.GetLabel().rstrip("*"))
            self.values[key] = ctrl.GetValue()

        self.label_rating.SetLabel(self.label_rating.GetLabel().rstrip("*"))
        self.values["rating"] = self.ctrl_rating.GetValue()

        self.changes = {}

        self.app.frame.toolbar.EnableTool(wx.ID_SAVE, False)

    async def commit_changes(self):
        if not self.changes or not self.selected_items or self.is_committing:
            return

        self.is_committing = True

        changes = {}

        for ctrl_name, new_value in self.changes.items():
            if new_value == "< blank >":
                new_value = ""
            elif new_value == "< keep >":
                continue

            if ctrl_name in self.ctrls:
                changes[ctrl_name] = new_value
            elif ctrl_name in self.other_ctrls:
                changes[ctrl_name] = new_value

            for item in self.selected_items:
                item[ctrl_name] = new_value

        if not changes:
            self.clear_changes()
            return

        count = 0
        updated = 0
        progress = wx.ProgressDialog("Saving", "Saving changes...", parent=self.app.frame,
                                     maximum=len(self.selected_items), style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)

        for item in self.selected_items:
            result = await self.app.api.update_lora(item["id"], changes)
            count += 1
            updated += result['fields_updated']
            progress.Update(count, f"Saving changes... ({count}/{len(self.selected_items)})")

            self.app.frame.results_panel.list.refresh_one_text(item)

        progress.Destroy()
        self.app.frame.statusbar.SetStatusText(f"Updated {updated} fields")

        self.is_committing = False

        self.clear_changes()

    async def prompt_commit_changes(self):
        if not self.selected_items:
            self.changes = {}
            return

        if not self.changes or self.is_committing:
            return

        if self.changes:
            dlg = wx.MessageDialog(None, "You have unsaved changes, would you like to commit them?",'Updater',wx.YES_NO | wx.ICON_QUESTION)
            result = dlg.ShowModal()
            if result == wx.ID_YES:
                await self.commit_changes()

    async def SubItemSelected(self, key, items):
        await self.prompt_commit_changes()

        self.selected_items = items

        if len(items) == 0:
            for (ctrl, label) in self.ctrls.values():
                ctrl.SetEditable(False)
                ctrl.Clear()
            for ctrl in self.other_ctrls.values():
                ctrl.Clear()
        else:
            for name, (ctrl, label) in self.ctrls.items():
                ctrl.SetEditable(True)

                choices = ["< blank >", "< keep >"]

                def get_value(item):
                    value = item.get(name, "< blank >")
                    if value is None or value == "":
                        value = "< blank >"
                    return value

                value = None

                if len(items) == 1:
                    value = get_value(items[0])
                    if value not in choices:
                        choices.append(value)
                else:
                    for item in items:
                        if value != "< keep >":
                            item_value = get_value(item)
                            if value is None:
                                value = item_value
                            elif value != item_value:
                                value = "< keep >"
                        choice = get_value(item)
                        if choice not in choices:
                            choices.append(choice)

                is_combo_box = hasattr(ctrl, "SetItems")
                if is_combo_box:
                    ctrl.SetItems(choices)
                else:
                    if value == "< blank >":
                        value = ""
                ctrl.ChangeValue(value)

            if len(items) == 1:
                filename = os.path.basename(items[0]["filepath"])
                id = str(items[0]["id"])
                tags = (items[0].get("tags") or "").split()
                rating = items[0].get("rating") or 0
                self.ctrl_rating.ChangeValue(rating)
            else:
                filename = "< multiple >"
                id = "< multiple >"
                tags = ["< multiple >"]
                self.ctrl_rating.SetMultiple()
            self.text_filename.ChangeValue(filename)
            self.text_id.ChangeValue(id)
            # self.list_tags.set_tags(tags)

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


class TagFrequencyList(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app

        self.text = []
        self.tags = {}
        self.itemDataMap = {}
        self.itemIndexMap = []
        self.sortColumn = -1
        self.sortReverse = False

        wx.ListCtrl.__init__(self, *args, **kwargs)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        self.EnableAlternateRowColours(True)
        self.InsertColumn(0, "Tag")
        self.InsertColumn(1, "Count")
        self.setResizeColumn(0)

        self.Bind(wx.EVT_LIST_COL_CLICK, self.OnColClick)

    def set_tags(self, tags):
        self.DeleteAllItems()

        self.sortColumn = -1
        self.sortReverse = False
        self.tags = tags
        self.text = []

        if self.tags is None:
            self.tags = {}
            self.tags["_"] = {}
            self.tags["_"]["(Tag frequency not saved)"] = 0

        self.totals = {}
        for folder, freqs in self.tags.items():
            for tag, freq in freqs.items():
                if tag not in self.totals:
                    self.totals[tag] = 0
                self.totals[tag] += freq

        if len(self.totals) == 0:
            self.totals["(No tags)"] = 0

        for tag, freq in self.totals.items():
            self.text.append((tag.strip(), str(freq)))

        self.itemDataMap = {}
        for i, (tag, freq) in enumerate(self.totals.items()):
            self.itemDataMap[i] = (tag, freq)

        self.itemIndexMap = list(self.itemDataMap.keys())

        self.SetItemCount(len(self.text))
        self.Arrange()

        self.SortByColumn(1)

    def OnGetItemText(self, item, col):
        index = self.itemIndexMap[item]
        return self.text[index][col]

    def GetListCtrl(self):
        return self

    def SortByColumn(self, col):
        if col == self.sortColumn:
            self.sortReverse = not self.sortReverse
        else:
            self.sortReverse = col == 1
        self.sortColumn = col
        def sort(index):
            cols = self.itemDataMap[index]
            return cols[col]
        self.itemIndexMap = list(sorted(self.itemIndexMap, key=sort, reverse=self.sortReverse))

        # redraw the list
        self.Refresh()

    def OnColClick(self, event):
        self.SortByColumn(event.GetColumn())


class TagFrequencyPanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app

        wx.Panel.__init__(self, *args, **kwargs)

        self.list = TagFrequencyList(self, id=wx.ID_ANY, style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_HRULES | wx.LC_VRULES, app=app)

        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "item_selected"), self.SubItemSelected)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    async def SubItemSelected(self, key, items):
        item = {}
        if len(items) == 1:
            item = items[0]
        tags = item.get("tag_frequency", {})
        self.list.set_tags(tags)

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
        self.aui_mgr.AddPane(self.results_panel, wx.aui.AuiPaneInfo().Caption("Search Results").Center().CloseButton(False).MinSize(self.FromDIP(wx.Size(300, 300))))

        self.file_panel = FilePanel(self, app=self.app)
        self.aui_mgr.AddPane(self.file_panel, wx.aui.AuiPaneInfo().Caption("Files").Top().Right().CloseButton(False).MinSize(self.FromDIP(wx.Size(250, 250))))

        self.tag_freq_panel = TagFrequencyPanel(self, app=self.app)
        self.aui_mgr.AddPane(self.tag_freq_panel, wx.aui.AuiPaneInfo().Caption("Tag Frequency").Bottom().Right().CloseButton(False).MinSize(self.FromDIP(wx.Size(250, 250))))

        self.properties_panel = PropertiesPanel(self, app=self.app)
        self.aui_mgr.AddPane(self.properties_panel, wx.aui.AuiPaneInfo().Caption("Properties").Top().Left().CloseButton(False).MinSize(self.FromDIP(wx.Size(325, 325))))

        self.image_panel = PreviewImagePanel(self, app=self.app)
        self.aui_mgr.AddPane(self.image_panel, wx.aui.AuiPaneInfo().Caption("Preview Image").Bottom().Left().CloseButton(False).MinSize(wx.Size(250, 250)).BestSize(self.FromDIP(wx.Size(250, 250))))

        self.aui_mgr.Update()

        self.statusbar = self.CreateStatusBar(1)

        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "item_selected"), self.SubItemSelected)
        self.pub = aiopubsub.Publisher(hub, Key("events"))

        self.accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('S'), wx.ID_SAVE),
        ])
        self.SetAcceleratorTable(self.accel_tbl)

        self.Show()

    async def OnSave(self, evt):
        await self.properties_panel.commit_changes()
        self.Refresh()

    async def SubItemSelected(self, key, items):
        self.toolbar.EnableTool(wx.ID_SAVE, False)

    async def search(self, query):
        self.statusbar.SetStatusText("Searching...")

        await self.results_panel.search(query)

        results = self.results_panel.list.results

        self.pub.publish(Key("search_finished"), results)


class App(wxasync.WxAsyncApp):
    def __init__(self, server, config, *args, **kwargs):
        self.server = server
        self.title = "sd-model-manager"
        self.api = API(config)

        wxasync.WxAsyncApp.__init__(self, *args, **kwargs)

    def OnInit(self):
        self.frame = MainWindow(self, None, -1, self.title)
        self.frame.SetClientSize(self.frame.FromDIP(wx.Size(1600, 800)))
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
