import asyncio
import ctypes
import io
import os
import pathlib
import re
import subprocess
from typing import Callable, Optional

import aiohttp
import aiopubsub
import simplejson
import wx
import wx.aui
import wx.lib.mixins.listctrl as listmix
import wx.lib.newevent
import wxasync
from aiohttp import web
from aiopubsub import Key
from PIL import Image
from wx.lib.agw import ultimatelistctrl

from gui.utils import PUBSUB_HUB, combine_tag_freq


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

        self.itemIndexMap = list(
            sorted(self.itemIndexMap, key=sort, reverse=self.sortReverse)
        )

        # redraw the list
        self.Refresh()

    def OnColClick(self, event):
        self.SortByColumn(event.GetColumn())


class TagFrequencyPanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app

        wx.Panel.__init__(self, *args, **kwargs)

        self.list = TagFrequencyList(
            self,
            id=wx.ID_ANY,
            style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_HRULES | wx.LC_VRULES,
            app=app,
        )

        self.sub = aiopubsub.Subscriber(PUBSUB_HUB, Key("events"))
        self.sub.add_async_listener(
            Key("events", "item_selected"), self.SubItemSelected
        )

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        self.SetSizerAndFit(self.sizer)

    async def SubItemSelected(self, key, items):
        item = {}
        if len(items) == 1:
            item = items[0]
        tags = item.get("tag_frequency", {})
        self.list.set_tags(tags)
