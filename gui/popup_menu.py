import os
from typing import Callable, Optional

import wx
import wx.aui
import wx.lib.newevent

from sd_model_manager.prompt import infotext
from gui import utils
from gui.dialogs.generate_previews import GeneratePreviewsDialog


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
    utils.open_on_file(path)


def copy_item_value(target, event, colmap, app):
    col = colmap[event.GetColumn()]
    column = utils.COLUMNS[col]
    value = column.callback(target)

    copy_to_clipboard(value, app)


def copy_top_n_tags(tag_freq, app, n=None):
    totals = utils.combine_tag_freq(tag_freq)
    sort = list(sorted(totals.items(), key=lambda p: p[1], reverse=True))
    tags = [p[0] for p in sort]
    if n is not None:
        tags = tags[:n]
    s = ", ".join(tags)
    copy_to_clipboard(s, app)


def copy_to_clipboard(value, app=None):
    if wx.TheClipboard.Open():
        wx.TheClipboard.SetData(wx.TextDataObject(str(value)))
        wx.TheClipboard.Close()

        if app:
            app.frame.statusbar.SetStatusText(f"Copied: {utils.trim_string(value)}")


async def generate_previews(app):
    await app.frame.OnGeneratePreviews(None)


def create_popup_menu_for_item(target, evt, app, colmap=None):
    tag_freq = target.get("tag_frequency")

    image_prompt = None
    image_tags = None
    image_neg_tags = None
    image, image_path = utils.find_image_for_model(target)
    if image is not None:
        if "parameters" in image.info:
            image_prompt = image.info["parameters"]
            image_tags = infotext.parse_a1111_prompt(image_prompt)
        elif "prompt" in image.info:
            image_prompt = image.info["prompt"]
            image_tags = infotext.parse_comfyui_prompt(image_prompt)
        if image_tags is not None:
            image_neg_tags = next(
                iter(i for i in image_tags if i.startswith("negative:")), "negative:"
            ).lstrip("negative:")
            image_tags = infotext.remove_metatags(image_tags)
            image_tags = ", ".join([t for t in image_tags])

    icon_copy = utils.load_bitmap("images/icons/16/page_copy.png")
    icon_folder_go = utils.load_bitmap("images/icons/16/folder_go.png")
    icon_picture_add = utils.load_bitmap("images/icons/16/picture_add.png")

    items = [
        PopupMenuItem("Open Folder", open_folder, icon=icon_folder_go),
        PopupMenuItem("Copy Value", lambda t, e: copy_item_value(t, e, colmap, app))
        if colmap is not None
        else None,
        PopupMenuSeparator(),
        PopupMenuItem(
            "Generate Previews...",
            lambda t, e: generate_previews(app),
            icon=icon_picture_add,
        ),
        PopupMenuSeparator(),
        PopupMenuItem(
            "Image Prompt",
            lambda t, e: copy_to_clipboard(image_prompt, app),
            enabled=image_prompt is not None,
            icon=icon_copy,
        ),
        PopupMenuItem(
            "Image Tags",
            lambda t, e: copy_to_clipboard(image_tags, app),
            enabled=image_tags is not None,
            icon=icon_copy,
        ),
        PopupMenuItem(
            "Image Neg. Tags",
            lambda t, e: copy_to_clipboard(image_neg_tags, app),
            enabled=image_neg_tags is not None,
            icon=icon_copy,
        ),
        PopupMenuItem(
            "Top 10 Tags",
            lambda t, e: copy_top_n_tags(tag_freq, app, 10),
            enabled=tag_freq is not None,
            icon=icon_copy,
        ),
        PopupMenuItem(
            "Top 20 Tags",
            lambda t, e: copy_top_n_tags(tag_freq, app, 20),
            enabled=tag_freq is not None,
            icon=icon_copy,
        ),
        PopupMenuItem(
            "Top 50 Tags",
            lambda t, e: copy_top_n_tags(tag_freq, app, 50),
            enabled=tag_freq is not None,
            icon=icon_copy,
        ),
        PopupMenuItem(
            "All Tags",
            lambda t, e: copy_top_n_tags(tag_freq, app),
            enabled=tag_freq is not None,
            icon=icon_copy,
        ),
    ]
    items = [i for i in items if i]

    return PopupMenu(target=target, event=evt, items=items)
