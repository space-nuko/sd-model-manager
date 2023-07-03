#!/usr/bin/env python

import os
import pathlib
import subprocess
import re
import ctypes
import io
from dataclasses import dataclass
import asyncio
import aiohttp
import aiopubsub
import simplejson
from PIL import Image
from aiohttp import web
from aiopubsub import Key
from typing import Callable, Optional

import wx
import wx.aui
import wx.lib.newevent
from wx.lib.agw import ultimatelistctrl
import wx.lib.mixins.listctrl as listmix
import wxasync

from main import create_app
from sd_model_manager.prompt import infotext
from sd_model_manager.utils.common import get_config, find_image, try_load_image
from sd_model_manager.utils.timer import Timer
from gui.image_panel import ImagePanel
from gui.rating_ctrl import RatingCtrl, EVT_RATING_CHANGED
from gui.scrolledthumbnail import ScrolledThumbnail, Thumb, PILImageHandler, file_broken, EVT_THUMBNAILS_SEL_CHANGED, EVT_THUMBNAILS_DCLICK, EVT_THUMBNAILS_RCLICK

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(True)
except:
    pass

hub = aiopubsub.Hub()

def trim_string(s, n=200):
    return (s[:n] + "...") if len(s) > n else s

def open_on_file(path):
    path = os.path.realpath(path)

    if os.name == 'nt':
        explorer = os.path.join(os.getenv('WINDIR'), 'explorer.exe')
        subprocess.run([explorer, '/select,', path])
    else:
        os.startfile(os.path.dirname(path))

def load_bitmap(path):
    with open(path, "rb") as f:
        img = wx.Image(io.BytesIO(f.read()), type=wx.BITMAP_TYPE_ANY, index=-1)
        return wx.Bitmap(img, depth=wx.BITMAP_SCREEN_DEPTH)

def find_image_for_model(item):
    image = None
    image_path = None

    image_paths = item["preview_images"]
    if len(image_paths) > 0:
        for path in image_paths:
            image = try_load_image(path)
            if image is not None:
                image_path = path
                break

    if image is None:
        filepath = os.path.normpath(os.path.join(item["root_path"], item["filepath"]))
        image, image_path = find_image(filepath, load=True)

    return image, image_path

def find_image_path_for_model(item):
    image_path = None

    image_paths = item["preview_images"]
    if len(image_paths) > 0:
        for path in image_paths:
            if os.path.isfile(path):
                return path

    filepath = os.path.normpath(os.path.join(item["root_path"], item["filepath"]))
    _, image_path = find_image(filepath, load=False)
    return image_path

def combine_tag_freq(tags):
    totals = {}
    for folder, freqs in tags.items():
        for tag, freq in freqs.items():
            if tag not in totals:
                totals[tag] = 0
            totals[tag] += freq
    return totals


class PopupMenuSeparator:
    pass

class PopupMenuItem:
    title: str
    callback: Callable
    enabled: bool
    checked: Optional[bool]
    bitmap: Optional[wx.Bitmap]

    def __init__(self, title, callback, enabled=True, checked=None, icon=None):
        self.title = title
        self.callback = callback
        self.enabled = enabled
        self.checked = checked
        self.icon = icon

class PopupMenu(wx.Menu):
    def __init__(self, *args, target=None, event=None, items=None, **kwargs):
        wx.Menu.__init__(self, *args, **kwargs)
        self.target = target
        self.event = event
        self.items = {}
        self.order = []

        for item in items:
            id = wx.NewIdRef(count=1)
            self.order.append(id)
            self.items[id] = item

        for id in self.order:
            item = self.items[id]

            if isinstance(item, PopupMenuSeparator):
                self.AppendSeparator()
            else:
                if item.checked is not None:
                    self.AppendCheckItem(id, item.title)
                    self.Check(id, item.checked)
                else:
                    self.Append(id, item.title)
                    if item.icon is not None:
                        menu_item, _menu = self.FindItem(id)
                        menu_item.SetBitmap(item.icon)
                self.Enable(id, item.enabled)
            self.Bind(wx.EVT_MENU, self.OnMenuSelection, id=id)

    def OnMenuSelection(self, event):
        item = self.items[event.GetId()]
        item.callback(self.target, self.event)


def open_folder(target, event):
    path = os.path.join(target["root_path"], target["filepath"])
    open_on_file(path)

def copy_item_value(target, event, colmap, app):
    col = colmap[event.GetColumn()]
    column = COLUMNS[col]
    value = column.callback(target)

    copy_to_clipboard(value, app)

def copy_top_n_tags(tag_freq, app, n=None):
    totals = combine_tag_freq(tag_freq)
    tags = list(totals.keys())
    if n is not None:
        tags = tags[:n]
    s = ", ".join(tags)
    copy_to_clipboard(s, app)

def copy_to_clipboard(value, app=None):
    if wx.TheClipboard.Open():
        wx.TheClipboard.SetData(wx.TextDataObject(str(value)))
        wx.TheClipboard.Close()

        if app:
            app.frame.statusbar.SetStatusText(f"Copied: {trim_string(value)}")

def create_popup_menu_for_item(target, evt, app, colmap=None):
    tag_freq = target.get("tag_frequency")

    image_prompt = None
    image_tags = None
    image_neg_tags = None
    image, image_path = find_image_for_model(target)
    if image is not None:
        if "parameters" in image.info:
            image_prompt = image.info["parameters"]
            image_tags = infotext.parse_a1111_prompt(image_prompt)
        elif "prompt" in image.info:
            image_prompt = image.info["prompt"]
            image_tags = infotext.parse_comfyui_prompt(image_prompt)
        if image_tags is not None:
            image_neg_tags = next(iter(i for i in image_tags if i.startswith("negative:")), "negative:").lstrip("negative:")
            image_tags = infotext.remove_metatags(image_tags)
            image_tags = ", ".join([t for t in image_tags])

    icon_copy = load_bitmap("images/icons/page_copy.png")
    icon_folder_go = load_bitmap("images/icons/folder_go.png")

    items = [
        PopupMenuItem("Open Folder", open_folder, icon=icon_folder_go),
        PopupMenuItem("Copy Value", lambda t, e: copy_item_value(t, e, colmap, app)) if colmap is not None else None,
        PopupMenuSeparator(),
        PopupMenuItem("Image Prompt", lambda t, e: copy_to_clipboard(image_prompt, app), enabled=image_prompt is not None, icon=icon_copy),
        PopupMenuItem("Image Tags", lambda t, e: copy_to_clipboard(image_tags, app), enabled=image_tags is not None, icon=icon_copy),
        PopupMenuItem("Image Neg. Tags", lambda t, e: copy_to_clipboard(image_neg_tags, app), enabled=image_neg_tags is not None, icon=icon_copy),
        PopupMenuItem("Top 10 Tags", lambda t, e: copy_top_n_tags(tag_freq, app, 10), enabled=tag_freq is not None, icon=icon_copy),
        PopupMenuItem("Top 20 Tags", lambda t, e: copy_top_n_tags(tag_freq, app, 20), enabled=tag_freq is not None, icon=icon_copy),
        PopupMenuItem("Top 50 Tags", lambda t, e: copy_top_n_tags(tag_freq, app, 50), enabled=tag_freq is not None, icon=icon_copy),
        PopupMenuItem("All Tags", lambda t, e: copy_top_n_tags(tag_freq, app), enabled=tag_freq is not None, icon=icon_copy),
    ]
    items = [i for i in items if i]

    return PopupMenu(target=target, event=evt, items=items)

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
            "limit": 1000
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

    def __init__(self, name, callback, width=None, is_meta=False, is_visible=True):
        self.name = name
        self.callback = callback
        self.width = width
        self.is_meta = is_meta

        self.is_visible = is_visible

def format_rating(rating):
    if rating is None or rating <= 0:
        return ""
    rating = min(10, max(0, int(rating)))
    return u'\u2605'*int(rating/2) + u'\u00BD'*int(rating%2!=0)


re_optimizer = re.compile(r'([^.]+)(\(.*\))?$')


def format_optimizer(m):
    optimizer = m["optimizer"]
    if optimizer is None:
        return None

    matches = re_optimizer.search(optimizer)
    if matches is None:
        return optimizer
    return matches[1]


def format_optimizer_args(m):
    optimizer = m["optimizer"]
    if optimizer is None:
        return None

    matches = re_optimizer.search(optimizer)
    if matches is None or matches[2] is None:
        return None
    return matches[2].lstrip("(").rstrip(")")

    # result = {}
    # for pair in args.split(","):
    #     spl = pair.split("=", 1)
    #     if len(spl) > 1:
    #         result[spl[0]] = spl[1]

    # return str(result)


def format_network_alpha(v):
    try:
        return int(float(v))
    except Exception:
        try:
            return float(v)
        except Exception:
            return v


COLUMNS = [
    # ColumnInfo("ID", lambda m: m["id"]),
    ColumnInfo("Has Image", lambda m: "★" if len(m["preview_images"] or []) > 0 else "", width=20),
    ColumnInfo("Filename", lambda m: os.path.basename(m["filepath"]), width=240),

    ColumnInfo("Module", lambda m: m["module_name"], width=60),

    ColumnInfo("Name", lambda m: m["display_name"], is_meta=True, width=100),
    ColumnInfo("Author", lambda m: m["author"], is_meta=True, width=100),
    ColumnInfo("Rating", lambda m: format_rating(m["rating"]), is_meta=True, width=60),

    ColumnInfo("Dim.", lambda m: format_network_alpha(m["network_dim"]), width=60),
    ColumnInfo("Alpha", lambda m: format_network_alpha(m["network_alpha"]), width=60),
    ColumnInfo("Resolution", lambda m: m["resolution_width"]),
    ColumnInfo("Unique Tags", lambda m: m["unique_tags"]),
    ColumnInfo("Learning Rate", lambda m: m["learning_rate"]),
    ColumnInfo("UNet LR", lambda m: m["unet_lr"]),
    ColumnInfo("Text Encoder LR", lambda m: m["text_encoder_lr"]),
    ColumnInfo("Optimizer", format_optimizer, width=120),
    ColumnInfo("Optimizer Args", format_optimizer_args, width=240),
    ColumnInfo("Scheduler", lambda m: m["lr_scheduler"], width=80),
    ColumnInfo("# Train Images", lambda m: m["num_train_images"]),
    ColumnInfo("# Reg Images", lambda m: m["num_reg_images"]),
    ColumnInfo("# Batches/Epoch", lambda m: m["num_batches_per_epoch"]),
    ColumnInfo("# Epochs", lambda m: m["num_epochs"]),
    ColumnInfo("Epoch", lambda m: m["epoch"]),
    ColumnInfo("Total Batch Size", lambda m: m["total_batch_size"]),
    ColumnInfo("Keep Tokens", lambda m: m["keep_tokens"]),
    ColumnInfo("Noise Offset", lambda m: m["noise_offset"]),
    ColumnInfo("Training Comment", lambda m: m["training_comment"], width=140, is_visible=False),

    ColumnInfo("Tags", lambda m: m["tags"], is_meta=True, width=140),
    ColumnInfo("Keywords", lambda m: m["keywords"], is_meta=True, width=140, is_visible=False),
    ColumnInfo("Source", lambda m: m["source"], is_meta=True, width=100, is_visible=False),

    ColumnInfo("Filepath", lambda m: os.path.normpath(os.path.join(m["root_path"], m["filepath"])), width=600),
]

IGNORE_FIELDS = set([
    "preview_images",
    "tag_frequency",
    "dataset_dirs",
    "reg_dataset_dirs",
    "bucket_info",
    "name",
    "author",
    "rating",
    "tags",
    "keywords",
    "source",
    "_index",
    "id",
    "type"
])

METADATA_ORDER = [
    "output_name",
    "root_path",
    "filepath",
    "training_started_at",
    "training_finished_at",
    "session_id",
    "learning_rate",
    "text_encoder_lr",
    "unet_lr",
    "num_train_images",
    "num_reg_images",
    "num_batches_per_epoch",
    "max_train_steps",
    "lr_warmup_steps",
    "batch_size_per_device",
    "total_batch_size",
    "num_epochs",
    "epoch",
    "gradient_checkpointing",
    "gradient_accumulation_steps",
    "optimizer",
    "lr_scheduler",
    "network_module",
    "network_dim",
    "network_alpha",
    "network_args",
    "mixed_precision",
    "full_fp16",
    "v2",
    "resolution_width",
    "resolution_height",
    "clip_skip",
    "max_token_length",
    "color_aug",
    "flip_aug",
    "random_crop",
    "shuffle_caption",
    "cache_latents",
    "enable_bucket",
    "min_bucket_reso",
    "max_bucket_reso",
    "seed",
    "keep_tokens",
    "noise_offset",
    "max_grad_norm",
    "caption_dropout_rate",
    "caption_dropout_every_n_epochs",
    "caption_tag_dropout_rate",
    "face_crop_aug_range",
    "prior_loss_weight",
    "min_snr_gamma",
    "scale_weight_norms",
    "unique_tags",
    "model_hash",
    "legacy_hash",
    "sd_model_name",
    "sd_model_hash",
    "new_sd_model_hash",
    "vae_name",
    "vae_hash",
    "new_vae_hash",
    "vae_name",
    "training_comment",
    "sd_scripts_commit_hash",
]

class MetadataList(ultimatelistctrl.UltimateListCtrl):
    def __init__(self, parent, item, app=None):
        super().__init__(parent=parent, id=wx.ID_ANY, agwStyle=ultimatelistctrl.ULC_VIRTUAL|ultimatelistctrl.ULC_REPORT|wx.LC_HRULES|wx.LC_VRULES)

        self.item = item
        self.app = app

        self.InsertColumn(0, "Key")
        self.InsertColumn(1, "Value")
        self.SetColumnWidth(0, parent.FromDIP(140))
        self.SetColumnWidth(1, ultimatelistctrl.ULC_AUTOSIZE_FILL)

        self.fields = [(k, v) for k, v in self.item.items() if k in METADATA_ORDER]
        self.fields = list(sorted(self.fields, key=lambda i: METADATA_ORDER.index(i[0])))

        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.OnListItemRightClicked)

        self.SetItemCount(len(self.fields))

    def OnGetItemColumnImage(self, item, col):
        return []

    def OnGetItemImage(self, item):
        return []

    def OnGetItemAttr(self, item):
        return None

    def OnGetItemText(self, item, col):
        v = self.fields[item][col]
        if col == 1:
            if v is None:
                return "(None)"
            elif isinstance(v, str):
                return f"\"{v}\""
        return str(v)

    def OnGetItemTextColour(self, item, col):
        v = self.fields[item][col]
        if col == 1 and v is None:
            return "gray"
        return None

    def OnGetItemToolTip(self, item, col):
        return None

    def OnGetItemKind(self, item):
        return 0

    def OnGetItemColumnKind(self, item, col):
        return 0

    def ClearSelection(self):
        i = self.GetFirstSelected()
        while i != -1:
            self.Select(i, 0)
            i = self.GetNextSelected(i)

    def OnListItemRightClicked(self, evt):
        self.ClearSelection()
        self.Select(evt.GetIndex())

        target = self.fields[evt.GetIndex()]

        menu = PopupMenu(target=target, event=evt, items=[
            PopupMenuItem("Copy Value", self.copy_value)
        ])
        pos = evt.GetPoint()
        self.PopupMenu(menu, pos)
        menu.Destroy()

    def copy_value(self, target, event):
        value = target[event.GetColumn()]

        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(str(value)))
            wx.TheClipboard.Close()

            self.app.frame.statusbar.SetStatusText(f"Copied: {trim_string(value)}")

class MetadataDialog(wx.Dialog):
    def __init__(self, parent, item, app=None):
        super().__init__(parent=parent, id=wx.ID_ANY, title="Model Metadata", size=parent.FromDIP(wx.Size(600, 700)))

        self.SetEscapeId(12345)

        self.item = item
        self.app = app

        self.list = MetadataList(self, item, app=self.app)
        self.buttonOk = wx.Button(self, wx.ID_OK)

        self.sizerB = wx.StdDialogButtonSizer()
        self.sizerB.AddButton(self.buttonOk)
        self.sizerB.Realize()

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.list, proportion=10, border=2, flag=wx.EXPAND|wx.ALIGN_TOP|wx.ALL)
        self.sizer.Add(self.sizerB, border=2, flag=wx.EXPAND|wx.ALL)

        self.SetSizer(self.sizer)

class ResultsListCtrl(ultimatelistctrl.UltimateListCtrl):
    def __init__(self, parent, app=None):
        ultimatelistctrl.UltimateListCtrl.__init__(self, parent, -1,
                                                   agwStyle=ultimatelistctrl.ULC_VIRTUAL|ultimatelistctrl.ULC_REPORT|wx.LC_HRULES|wx.LC_VRULES|ultimatelistctrl.ULC_SHOW_TOOLTIPS)

        self.app = app

        self.results = []
        self.text = {}
        self.values = {}
        self.colmap = {}
        self.filtered = []
        self.filter = None
        self.clicked = False

        # EVT_LIST_ITEM_SELECTED and ULC_VIRTUAL don't mix
        # https://github.com/wxWidgets/wxWidgets/issues/4541
        self.Bind(wx.EVT_LIST_CACHE_HINT, self.OnListItemSelected)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnListItemActivated)
        self.Bind(wx.EVT_LIST_DELETE_ALL_ITEMS, self.OnListItemSelected)
        wxasync.AsyncBind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.OnListItemRightClicked, self)
        self.Bind(wx.EVT_LIST_COL_RIGHT_CLICK, self.OnColumnRightClicked)
        self.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)
        self.Bind(wx.EVT_KEY_UP, self.OnKeyUp)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnClick)
        self.Bind(wx.EVT_RIGHT_DOWN, self.OnClick)

        self.pub = aiopubsub.Publisher(hub, Key("events"))
        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "tree_filter_changed"), self.SubTreeFilterChanged)

        for col, column in enumerate(COLUMNS):
            self.InsertColumn(col, column.name)
            self.SetColumnShown(col, column.is_visible)

        self.refresh_columns()

    async def SubTreeFilterChanged(self, key, path):
        self.pub.publish(Key("item_selected"), [])

    def ClearSelection(self):
        i = self.GetFirstSelected()
        while i != -1:
            self.Select(i, 0)
            i = self.GetNextSelected(i)

    def OnKeyUp(self, evt):
        self.clicked = True
        evt.Skip()

    def OnKeyDown(self, evt):
        self.clicked = True
        evt.Skip()

    def set_results(self, results):
        self.results = results
        self.filter = None
        self.text = {}
        self.values = {}

        self.refresh_filter()

    def refresh_filter(self):
        data = self.results["data"]
        self.filtered = []
        if self.filter is None:
            self.filtered = data
        else:
            for d in data:
                p = os.path.normpath(os.path.join(d["root_path"], d["filepath"]))
                if p.startswith(self.filter):
                    self.filtered.append(d)
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
        for i, data in enumerate(self.filtered):
            data["_index"] = i
            self.refresh_one_text(data)

        count = len(self.filtered)
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
        return [self.filtered[i] for i in selection]

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

    def OnListItemActivated(self, evt):
        target = self.filtered[evt.GetIndex()]
        dialog = MetadataDialog(self, target, app=self.app)
        dialog.CenterOnParent(wx.BOTH)
        dialog.ShowModal()
        dialog.Destroy()

    async def OnListItemRightClicked(self, evt):
        self.ClearSelection()
        self.Select(evt.GetIndex())
        selection = self.get_selection()
        await self.app.frame.ForceSelect(selection)

        target = self.filtered[evt.GetIndex()]

        menu = create_popup_menu_for_item(target, evt, self.app, colmap=self.colmap)

        pos = evt.GetPoint()
        self.PopupMenu(menu, pos)
        menu.Destroy()

    def OnColumnRightClicked(self, evt):
        items = []
        for i, col in enumerate(COLUMNS):
            def check(target, event, col=col):
                col.is_visible = not col.is_visible
                self.SetColumnShown(i, col.is_visible)
                self.refresh_columns()
            items.append(PopupMenuItem(col.name, check, checked=col.is_visible))
        menu = PopupMenu(target=self, items=items)
        pos = evt.GetPoint()
        self.PopupMenu(menu, pos)
        menu.Destroy()
        pass

class ResultsNotebook(wx.Panel):
    def __init__(self, parent, app=None):
        self.app = app

        wx.Panel.__init__(self, parent, id=wx.ID_ANY)

        self.results = {}
        self.notebook = wx.Notebook(self)
        self.thumbs_need_update = False

        self.results_panel = ResultsPanel(self.notebook, app=self.app)
        self.results_gallery = ResultsGallery(self.notebook, app=self.app)

        self.notebook.AddPage(self.results_panel, "List")
        self.notebook.AddPage(self.results_gallery, "Gallery")

        self.pub = aiopubsub.Publisher(hub, Key("events"))
        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "tree_filter_changed"), self.SubTreeFilterChanged)

        self.search_box = wx.TextCtrl(self, wx.ID_ANY, style=wx.TE_PROCESS_ENTER)
        self.button = wx.Button(self, label="Search")

        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnSearch, self.button)
        wxasync.AsyncBind(wx.EVT_TEXT_ENTER, self.OnSearch, self.search_box)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.OnPageChanged)

        self.sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer2.Add(self.search_box, proportion=5, flag=wx.LEFT | wx.EXPAND | wx.ALL, border=5)
        self.sizer2.Add(self.button, proportion=1, flag=wx.ALL, border=5)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.notebook, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.sizer.Add(self.sizer2, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    def OnPageChanged(self, evt):
        sel = evt.GetSelection()
        if sel == 1: # gallery page
            self.results_gallery.SetThumbs(self.results_panel.list.filtered)

    async def SubTreeFilterChanged(self, key, path):
        list = self.results_panel.list
        list.filter = path
        list.refresh_filter()

        if len(list.filtered) > 0:
            list.Select(0, 1)
            list.Focus(0)
            self.pub.publish(Key("item_selected"), list.get_selection())

        self.results_gallery.needs_update = True
        if self.notebook.GetSelection() == 1:
            self.results_gallery.SetThumbs(list.filtered)

    async def search(self, query):
        self.pub.publish(Key("item_selected"), [])
        self.results = {}

        try_load_image.cache_clear()

        list = self.results_panel.list
        list.DeleteAllItems()
        list.Arrange(ultimatelistctrl.ULC_ALIGN_DEFAULT)

        self.results = await self.app.api.get_loras(query)
        list.set_results(self.results)

        if len(list.filtered) > 0:
            list.Select(0, 1)
            list.Focus(0)
            self.pub.publish(Key("item_selected"), list.get_selection())

        self.results_gallery.needs_update = True
        if self.notebook.GetSelection() == 1:
            self.results_gallery.SetThumbs(list.filtered)

    async def OnSearch(self, evt):
        await self.app.frame.search(self.search_box.GetValue())

class GalleryThumbnailHandler(PILImageHandler):
    def Load(self, filename):
        try:
            with Image.open(filename) as pil:
                pil.thumbnail((512, 512), Image.Resampling.LANCZOS)

                originalsize = pil.size

                img = wx.Image(pil.size[0], pil.size[1])

                img.SetData(pil.convert("RGB").tobytes())

                alpha = False
                if "A" in pil.getbands():
                    img.SetAlpha(pil.convert("RGBA").tobytes()[3::4])
                    alpha = True
        except:
            img = file_broken.GetImage()
            originalsize = (img.GetWidth(), img.GetHeight())
            alpha = False

        return img, originalsize, alpha

class ResultsGallery(wx.Panel):
    def __init__(self, parent, app=None, **kwargs):
        self.app = app
        self.thumbs = []
        self.needs_update = True

        wx.Panel.__init__(self, parent, id=wx.ID_ANY, **kwargs)

        self.gallery_font = wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False)

        self.gallery = ScrolledThumbnail(self, -1)
        self.gallery.SetThumbSize(256, 240)
        self.gallery.SetCaptionFont(font=self.gallery_font)
        self.gallery._tTextHeight = 32

        self.gallery.Bind(EVT_THUMBNAILS_SEL_CHANGED, self.OnThumbnailSelected)
        self.gallery.Bind(EVT_THUMBNAILS_DCLICK, self.OnThumbnailActivated)
        self.gallery.Bind(EVT_THUMBNAILS_RCLICK, self.OnThumbnailRightClicked)

        self.pub = aiopubsub.Publisher(hub, Key("events"))

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.gallery, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    def get_selection(self):
        selected = []
        for ii in self.gallery._selectedarray:
            sel = self.gallery.GetItem(ii)
            if sel is not None:
                selected.append(sel.GetData())
        return selected

    def OnThumbnailSelected(self, evt):
        selected = self.get_selection()
        list = self.app.frame.results_panel.results_panel.list

        list.ClearSelection()
        for item in selected:
            list.Select(item["_index"], 1)
        # list.Focus(item["_index"])
        self.pub.publish(Key("item_selected"), list.get_selection())

    def OnThumbnailActivated(self, evt):
        selected = self.gallery.GetSelectedItem()
        if selected is None:
            return
        item = selected.GetData()
        dialog = MetadataDialog(self, item, app=self.app)
        dialog.CenterOnParent(wx.BOTH)
        dialog.ShowModal()
        dialog.Destroy()

    def OnThumbnailRightClicked(self, evt):
        selected = self.get_selection()
        if not selected:
            return

        target = selected[0]
        menu = create_popup_menu_for_item(target, evt, self.app)

        pos = evt.GetPoint()
        self.PopupMenu(menu, pos)
        menu.Destroy()

    def SetThumbs(self, filtered):
        if not self.needs_update:
            return

        self.app.frame.statusbar.SetStatusText("Refreshing thumbnails...")
        self.gallery.Clear()
        self.gallery.Refresh()

        self.needs_update = False
        to_show = []
        MAX_THUMBS = 250

        for item in filtered:
            image_path = find_image_path_for_model(item)

            if image_path is not None:
                thumb = Thumb(os.path.dirname(image_path), os.path.basename(image_path), caption=os.path.splitext(os.path.basename(item["filepath"]))[0], imagehandler=GalleryThumbnailHandler, data=item)
                thumb.SetId(len(to_show))
                to_show.append(thumb)

            if len(to_show) >= MAX_THUMBS:
                break

        self.gallery.ShowThumbs(to_show)

        self.app.frame.statusbar.SetStatusText(f"Done. ({len(to_show)} entries)")

class ResultsPanel(wx.Panel):
    def __init__(self, parent, app=None, **kwargs):
        self.app = app
        self.results = []

        wx.Panel.__init__(self, parent, id=wx.ID_ANY, **kwargs)

        self.list = ResultsListCtrl(self, app)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

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
            image, path = find_image_for_model(items[0])

        if image:
            width, height = image.size
            bitmap = wx.Bitmap.FromBuffer(width, height, image.tobytes())
            self.image_view.LoadBitmap(bitmap)
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
        self.sub.add_async_listener(Key("events", "tree_filter_changed"), self.SubTreeFilterChanged)

        self.ctrls = {}

        self.selected_items = []
        self.changes = {}
        self.values = {}
        self.is_committing = False

        ctrls = [
            ("display_name", "Name", None, None),
            ("version", "Version", None, None),
            ("author", "Author", None, None),
            ("source", "Source", None, None),
            ("tags", "Tags", None, None),
            ("keywords", "Keywords", wx.TE_MULTILINE, self.Parent.FromDIP(wx.Size(250, 40))),
            ("negative_keywords", "Negative Keywords", wx.TE_MULTILINE, self.Parent.FromDIP(wx.Size(250, 40))),
            ("description", "Description", wx.TE_MULTILINE, self.Parent.FromDIP(wx.Size(250, 300))),
            ("notes", "Notes", wx.TE_MULTILINE, self.Parent.FromDIP(wx.Size(250, 300)))
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
        self.sizer.Add(self.ctrls["version"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["version"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["source"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["source"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["tags"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["tags"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["keywords"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["keywords"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["negative_keywords"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["negative_keywords"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.label_rating, flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrl_rating, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["description"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["description"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(self.ctrls["notes"][1], flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.ctrls["notes"][0], flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        # self.sizer.Add(wx.StaticText(self, label="Preview Image"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        # self.sizer.Add(self.text_preview_image, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        self.sizer.Add(wx.StaticText(self, label="ID"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        self.sizer.Add(self.text_id, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)
        # self.sizer.Add(wx.StaticText(self, label="Tags"), flag=wx.ALL | wx.ALIGN_TOP, border=2)
        # self.sizer.Add(self.list_tags, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5)

        self.SetSizerAndFit(self.sizer)
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
        progress = wx.ProgressDialog("Saving", f"Saving changes... ({0}/{len(self.selected_items)})", parent=self.app.frame,
                                     maximum=len(self.selected_items), style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)

        for item in self.selected_items:
            result = await self.app.api.update_lora(item["id"], changes)
            count += 1
            updated += result['fields_updated']
            progress.Update(count, f"Saving changes... ({count}/{len(self.selected_items)})")

            self.app.frame.results_panel.results_panel.list.refresh_one_text(item)

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
        if items == self.selected_items:
            return

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
                rating = None
                for item in items:
                    nrating = item.get("rating") or 0
                    if rating is None:
                        rating = nrating
                        self.ctrl_rating.ChangeValue(rating)
                    elif rating != nrating:
                        self.ctrl_rating.SetMultiple()
                        break
            self.text_filename.ChangeValue(filename)
            self.text_id.ChangeValue(id)
            # self.list_tags.set_tags(tags)

        self.clear_changes()

    async def SubTreeFilterChanged(self, key, sel):
        pass

class FilePanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.roots = []

        wx.Panel.__init__(self, *args, **kwargs)

        icon_size = (16, 16)
        self.icons = wx.ImageList(icon_size[0], icon_size[1])

        self.icon_folder_closed = self.icons.Add(wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, icon_size))
        self.icon_folder_open = self.icons.Add(wx.ArtProvider.GetBitmap(wx.ART_FOLDER_OPEN, wx.ART_OTHER, icon_size))
        self.icon_file = self.icons.Add(wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, icon_size))

        self.dir_tree = wx.TreeCtrl(self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TR_HAS_BUTTONS)
        self.dir_tree.SetImageList(self.icons)
        self.button_clear = wx.Button(self, label="Clear Filter")
        self.button_clear.Disable()

        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnTreeSelectionChanged)
        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnClearFilter, self.button_clear)

        self.pub = aiopubsub.Publisher(hub, Key("events"))
        self.sub = aiopubsub.Subscriber(hub, Key("events"))
        self.sub.add_async_listener(Key("events", "search_finished"), self.SubSearchFinished)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.dir_tree, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.sizer.Add(self.button_clear, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    async def OnClearFilter(self, evt):
        self.button_clear.Disable()
        self.pub.publish(Key("tree_filter_changed"), None)

    def OnTreeSelectionChanged(self, evt):
        self.button_clear.Enable()
        index = self.dir_tree.GetSelection()
        segments = []

        while index.IsOk():
            segments.append(self.dir_tree.GetItemText(index))
            index = self.dir_tree.GetItemParent(index)

        path = os.path.normpath(os.path.join(*list(reversed(segments))))

        self.pub.publish(Key("tree_filter_changed"), path)

    async def SubSearchFinished(self, key, results):
        self.dir_tree.DeleteAllItems()
        self.button_clear.Disable()
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

        for root in self.roots:
            self.dir_tree.Expand(root)


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

        self.totals = combine_tag_freq(self.tags)

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

        self.results_panel = ResultsNotebook(self, app=self.app)
        self.aui_mgr.AddPane(self.results_panel, wx.aui.AuiPaneInfo().Caption("Search Results").Center().CloseButton(False).MinSize(self.FromDIP(wx.Size(300, 300))))

        self.file_panel = FilePanel(self, app=self.app)
        self.aui_mgr.AddPane(self.file_panel, wx.aui.AuiPaneInfo().Caption("Files").Top().Right().CloseButton(False).MinSize(self.FromDIP(wx.Size(300, 300))).BestSize(self.FromDIP(wx.Size(400, 400))))

        self.tag_freq_panel = TagFrequencyPanel(self, app=self.app)
        self.aui_mgr.AddPane(self.tag_freq_panel, wx.aui.AuiPaneInfo().Caption("Tag Frequency").Bottom().Right().CloseButton(False).MinSize(self.FromDIP(wx.Size(300, 300))).BestSize(self.FromDIP(wx.Size(400, 400))))

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

    async def ForceSelect(self, selection):
        await self.SubItemSelected(None, selection)
        await self.properties_panel.SubItemSelected(None, selection)
        await self.tag_freq_panel.SubItemSelected(None, selection)
        await self.image_panel.SubItemSelected(None, selection)

    async def OnSave(self, evt):
        await self.properties_panel.commit_changes()
        self.Refresh()

    async def SubItemSelected(self, key, items):
        self.toolbar.EnableTool(wx.ID_SAVE, False)

    async def search(self, query):
        self.statusbar.SetStatusText("Searching...")

        await self.results_panel.search(query)

        results = self.results_panel.results

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
