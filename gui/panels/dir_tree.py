import os
import pathlib
import aiopubsub
from aiopubsub import Key

import wx
import wx.aui
import wx.lib.newevent
import wxasync

from gui.utils import PUBSUB_HUB


class DirTreePanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.roots = []

        wx.Panel.__init__(self, *args, **kwargs)

        icon_size = (16, 16)
        self.icons = wx.ImageList(icon_size[0], icon_size[1])

        self.icon_folder_closed = self.icons.Add(
            wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, icon_size)
        )
        self.icon_folder_open = self.icons.Add(
            wx.ArtProvider.GetBitmap(wx.ART_FOLDER_OPEN, wx.ART_OTHER, icon_size)
        )
        self.icon_file = self.icons.Add(
            wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, icon_size)
        )

        self.dir_tree = wx.TreeCtrl(
            self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TR_HAS_BUTTONS
        )
        self.dir_tree.SetImageList(self.icons)
        self.button_clear = wx.Button(self, label="Clear Filter")
        self.button_clear.Disable()

        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnTreeSelectionChanged)
        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnClearFilter, self.button_clear)

        self.pub = aiopubsub.Publisher(PUBSUB_HUB, Key("events"))
        self.sub = aiopubsub.Subscriber(PUBSUB_HUB, Key("events"))
        self.sub.add_async_listener(
            Key("events", "search_finished"), self.SubSearchFinished
        )

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

            root = next(
                r
                for r in self.roots
                if self.dir_tree.GetItemText(r) == result["root_path"]
            )
            for i, part in enumerate(path.parts):
                exist = find(root, part)
                if exist:
                    root = exist
                else:
                    root = self.dir_tree.AppendItem(root, part)

                    is_file = i == len(path.parts) - 1
                    if is_file:
                        self.dir_tree.SetItemImage(
                            root, self.icon_file, wx.TreeItemIcon_Normal
                        )
                    else:
                        self.dir_tree.SetItemImage(
                            root, self.icon_folder_closed, wx.TreeItemIcon_Normal
                        )
                        self.dir_tree.SetItemImage(
                            root, self.icon_folder_open, wx.TreeItemIcon_Expanded
                        )

        for root in self.roots:
            self.dir_tree.Expand(root)
