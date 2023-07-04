import os
import aiopubsub
from PIL import Image
from aiopubsub import Key

import wx
import wx.aui
import wx.lib.newevent
from wx.lib.agw import ultimatelistctrl
import wxasync

from sd_model_manager.utils.common import try_load_image
from gui.scrolledthumbnail import (
    ScrolledThumbnail,
    Thumb,
    PILImageHandler,
    file_broken,
    EVT_THUMBNAILS_SEL_CHANGED,
    EVT_THUMBNAILS_DCLICK,
    EVT_THUMBNAILS_RCLICK,
)
from gui.dialogs.metadata import MetadataDialog
from gui.utils import PUBSUB_HUB, COLUMNS, find_image_path_for_model
from gui.popup_menu import PopupMenu, PopupMenuItem, create_popup_menu_for_item


class ResultsListCtrl(ultimatelistctrl.UltimateListCtrl):
    def __init__(self, parent, app=None):
        ultimatelistctrl.UltimateListCtrl.__init__(
            self,
            parent,
            -1,
            agwStyle=ultimatelistctrl.ULC_VIRTUAL
            | ultimatelistctrl.ULC_REPORT
            | wx.LC_HRULES
            | wx.LC_VRULES
            | ultimatelistctrl.ULC_SHOW_TOOLTIPS,
        )

        self.app = app

        self.results = []
        self.text = {}
        self.values = {}
        self.colmap = {}
        self.filtered = []
        self.filter = None
        self.clicked = False
        self.primary_item = None

        # EVT_LIST_ITEM_SELECTED and ULC_VIRTUAL don't mix
        # https://github.com/wxWidgets/wxWidgets/issues/4541
        self.Bind(wx.EVT_LIST_CACHE_HINT, self.OnListItemSelected)
        wxasync.AsyncBind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnListItemActivated, self)
        self.Bind(wx.EVT_LIST_DELETE_ALL_ITEMS, self.OnListItemSelected)
        wxasync.AsyncBind(
            wx.EVT_LIST_ITEM_RIGHT_CLICK, self.OnListItemRightClicked, self
        )
        self.Bind(wx.EVT_LIST_COL_RIGHT_CLICK, self.OnColumnRightClicked)
        self.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)
        self.Bind(wx.EVT_KEY_UP, self.OnKeyUp)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnClick)
        self.Bind(wx.EVT_RIGHT_DOWN, self.OnClick)

        self.pub = aiopubsub.Publisher(PUBSUB_HUB, Key("events"))
        self.sub = aiopubsub.Subscriber(PUBSUB_HUB, Key("events"))
        self.sub.add_async_listener(
            Key("events", "tree_filter_changed"), self.SubTreeFilterChanged
        )

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
                p = d["filepath"]
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

        count = len(self.filtered)
        self.SetItemCount(count)

        self.text = {}
        self.values = {}
        for i, data in enumerate(self.filtered):
            data["_index"] = i
            self.refresh_one_text(data)

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

        filepath = data["filepath"]
        data["file_exists"] = os.path.isfile(filepath)
        if data["file_exists"]:
            colour = "white"
        else:
            colour = "red"
        self.SetItemBackgroundColour(i, colour)

    def get_selection(self):
        item = self.GetFirstSelected()
        num = self.GetSelectedItemCount()
        selection = [item]
        for i in range(1, num):
            item = self.GetNextSelected(item)
            selection.append(item)
        selection = [self.filtered[i] for i in selection]

        if len(selection) == 0:
            self.primary_item = None

        if self.primary_item is not None:
            if self.primary_item in selection:
                selection.insert(0, selection.pop(selection.index(self.primary_item)))
        return selection

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

    async def OnListItemActivated(self, evt):
        target = self.filtered[evt.GetIndex()]
        dialog = MetadataDialog(self, target, app=self.app)
        dialog.CenterOnParent(wx.BOTH)
        await wxasync.AsyncShowDialogModal(dialog)
        dialog.Destroy()

    async def OnListItemRightClicked(self, evt):
        idx = evt.GetIndex()
        self.Select(idx)
        self.Focus(idx)
        self.primary_item = self.filtered[idx]
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
        menu = PopupMenu(target=self, items=items, app=self.app)
        pos = evt.GetPoint()
        self.PopupMenu(menu, pos)
        menu.Destroy()
        pass


class GalleryThumbnailHandler(PILImageHandler):
    def Load(self, filename):
        try:
            with Image.open(filename) as pil:
                originalsize = pil.size

                pil.thumbnail((512, 512), Image.Resampling.LANCZOS)

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

        self.gallery_font = wx.Font(
            16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False
        )

        self.gallery = ScrolledThumbnail(self, -1)
        self.gallery.SetThumbSize(256, 240)
        self.gallery.SetCaptionFont(font=self.gallery_font)
        self.gallery.EnableToolTips()
        self.gallery._tTextHeight = 32

        self.gallery.Bind(EVT_THUMBNAILS_SEL_CHANGED, self.OnThumbnailSelected)
        wxasync.AsyncBind(
            EVT_THUMBNAILS_DCLICK, self.OnThumbnailActivated, self.gallery
        )
        self.gallery.Bind(EVT_THUMBNAILS_RCLICK, self.OnThumbnailRightClicked)

        self.pub = aiopubsub.Publisher(PUBSUB_HUB, Key("events"))

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

    def refresh_one_thumbnail(self, item):
        ii = self.gallery._id_to_idx.get(item["id"])
        if ii is not None and ii in self.gallery._cache:
            del self.gallery._cache[ii]
        else:
            self.gallery._cache = {}

    def OnThumbnailSelected(self, evt):
        selected = self.get_selection()
        list = self.app.frame.results_panel.results_panel.list

        list.ClearSelection()
        for item in selected:
            list.Select(item["_index"], 1)
        # list.Focus(item["_index"])
        self.pub.publish(Key("item_selected"), list.get_selection())

    async def OnThumbnailActivated(self, evt):
        selected = self.gallery.GetSelectedItem()
        if selected is None:
            return
        item = selected.GetData()
        dialog = MetadataDialog(self, item, app=self.app)
        dialog.CenterOnParent(wx.BOTH)
        await wxasync.AsyncShowDialogModal(dialog)
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

        for item in filtered:
            image_path = find_image_path_for_model(item)

            if image_path is not None:
                thumb = Thumb(
                    os.path.dirname(image_path),
                    os.path.basename(image_path),
                    caption=os.path.splitext(os.path.basename(item["filepath"]))[0],
                    imagehandler=GalleryThumbnailHandler,
                    lastmod=os.path.getmtime(image_path),
                    data=item,
                )
                thumb.SetId(len(to_show))
                to_show.append(thumb)

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

    def get_selection(self):
        return self.list.get_selection()


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

        self.pub = aiopubsub.Publisher(PUBSUB_HUB, Key("events"))
        self.sub = aiopubsub.Subscriber(PUBSUB_HUB, Key("events"))
        self.sub.add_async_listener(
            Key("events", "tree_filter_changed"), self.SubTreeFilterChanged
        )

        self.search_box = wx.TextCtrl(self, wx.ID_ANY, style=wx.TE_PROCESS_ENTER)
        self.button = wx.Button(self, label="Search")

        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnSearch, self.button)
        wxasync.AsyncBind(wx.EVT_TEXT_ENTER, self.OnSearch, self.search_box)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.OnPageChanged)

        self.sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer2.Add(
            self.search_box, proportion=5, flag=wx.LEFT | wx.EXPAND | wx.ALL, border=5
        )
        self.sizer2.Add(self.button, proportion=1, flag=wx.ALL, border=5)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.notebook, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.sizer.Add(self.sizer2, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    def get_selection(self):
        return self.results_panel.get_selection()

    async def refresh_one_item(self, item):
        try_load_image.cache_clear()
        self.results_panel.list.refresh_one_text(item)
        self.results_gallery.refresh_one_thumbnail(item)
        self.Refresh()
        selection = self.get_selection()
        if item in selection:
            await self.app.frame.ForceSelect(selection)

    def OnPageChanged(self, evt):
        sel = evt.GetSelection()
        if sel == 1:  # gallery page
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
