import os
import aiopubsub
from aiopubsub import Key

import wx
import wx.aui
import wx.lib.newevent
import wxasync

from gui.utils import PUBSUB_HUB
from gui.panels.dir_tree import DirTreePanel
from gui.panels.preview_image import PreviewImagePanel
from gui.panels.properties import PropertiesPanel
from gui.panels.results import ResultsNotebook
from gui.panels.tag_frequency import TagFrequencyPanel
import gui.dialogs.download
from gui import ids, utils
from gui.dialogs.generate_previews import GeneratePreviewsDialog


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

        utils.set_icons(self)

        icon_size = (32, 32)
        self.toolbar = self.CreateToolBar()
        self.tool_save = self.toolbar.AddTool(
            wx.ID_SAVE,
            "Save",
            wx.ArtProvider.GetBitmap(wx.ART_FILE_SAVE, wx.ART_OTHER, icon_size),
            wx.NullBitmap,
            wx.ITEM_NORMAL,
            "Save",
            "Save current changes to database",
            None,
        )
        self.tool_open_folder = self.toolbar.AddTool(
            ids.ID_OPEN_FOLDER,
            "Open Folder",
            utils.load_bitmap("images/icons/32/folder_go.png"),
            wx.NullBitmap,
            wx.ITEM_NORMAL,
            "Open Folder",
            "Open the folder containing this model",
            None,
        )
        self.tool_generate_previews = self.toolbar.AddTool(
            ids.ID_GENERATE_PREVIEWS,
            "Generate Previews...",
            utils.load_bitmap("images/icons/32/picture_add.png"),
            wx.NullBitmap,
            wx.ITEM_NORMAL,
            "Generate Previews...",
            "Create previews for the selected models",
            None,
        )

        self.toolbar.Realize()

        self.toolbar.EnableTool(wx.ID_SAVE, False)
        self.toolbar.EnableTool(ids.ID_OPEN_FOLDER, False)
        self.toolbar.EnableTool(ids.ID_GENERATE_PREVIEWS, False)

        wxasync.AsyncBind(wx.EVT_TOOL, self.OnSave, self, id=wx.ID_SAVE)
        wxasync.AsyncBind(wx.EVT_TOOL, self.OnOpenFolder, self, id=ids.ID_OPEN_FOLDER)
        wxasync.AsyncBind(
            wx.EVT_TOOL, self.OnGeneratePreviews, self, id=ids.ID_GENERATE_PREVIEWS
        )

        self.accel_tbl = wx.AcceleratorTable(
            [
                (wx.ACCEL_CTRL, ord("S"), wx.ID_SAVE),
                (wx.ACCEL_CTRL, ord("P"), ids.ID_GENERATE_PREVIEWS),
            ]
        )
        self.SetAcceleratorTable(self.accel_tbl)

        # self.aui_mgr.AddPane(self.toolbar, wx.aui.AuiPaneInfo().
        #                      Name("Toolbar").CaptionVisible(False).
        #                      ToolbarPane().Top().CloseButton(False).
        #                      DockFixed(True).Floatable(False).
        #                      LeftDockable(False).RightDockable(False))

        self.results_panel = ResultsNotebook(self, app=self.app)
        self.aui_mgr.AddPane(
            self.results_panel,
            wx.aui.AuiPaneInfo()
            .Caption("Search Results")
            .Center()
            .CloseButton(False)
            .MinSize(self.FromDIP(wx.Size(300, 300))),
        )

        self.dir_tree_panel = DirTreePanel(self, app=self.app)
        self.aui_mgr.AddPane(
            self.dir_tree_panel,
            wx.aui.AuiPaneInfo()
            .Caption("Files")
            .Top()
            .Right()
            .CloseButton(False)
            .MinSize(self.FromDIP(wx.Size(300, 300)))
            .BestSize(self.FromDIP(wx.Size(400, 400))),
        )

        self.tag_freq_panel = TagFrequencyPanel(self, app=self.app)
        self.aui_mgr.AddPane(
            self.tag_freq_panel,
            wx.aui.AuiPaneInfo()
            .Caption("Tag Frequency")
            .Bottom()
            .Right()
            .CloseButton(False)
            .MinSize(self.FromDIP(wx.Size(300, 300)))
            .BestSize(self.FromDIP(wx.Size(400, 400))),
        )

        self.properties_panel = PropertiesPanel(self, app=self.app)
        self.aui_mgr.AddPane(
            self.properties_panel,
            wx.aui.AuiPaneInfo()
            .Caption("Properties")
            .Top()
            .Left()
            .CloseButton(False)
            .MinSize(self.FromDIP(wx.Size(325, 325))),
        )

        self.image_panel = PreviewImagePanel(self, app=self.app)
        self.aui_mgr.AddPane(
            self.image_panel,
            wx.aui.AuiPaneInfo()
            .Caption("Preview Image")
            .Bottom()
            .Left()
            .CloseButton(False)
            .MinSize(wx.Size(250, 250))
            .BestSize(self.FromDIP(wx.Size(250, 250))),
        )

        self.aui_mgr.Update()

        self.statusbar = self.CreateStatusBar(1)

        self.sub = aiopubsub.Subscriber(PUBSUB_HUB, Key("events"))
        self.sub.add_async_listener(
            Key("events", "item_selected"), self.SubItemSelected
        )
        self.pub = aiopubsub.Publisher(PUBSUB_HUB, Key("events"))

        self.Show()

    async def ForceSelect(self, selection):
        await self.SubItemSelected(None, selection)
        await self.properties_panel.SubItemSelected(None, selection)
        await self.tag_freq_panel.SubItemSelected(None, selection)
        await self.image_panel.SubItemSelected(None, selection)

    async def OnSave(self, evt):
        await self.properties_panel.commit_changes()
        self.Refresh()

    async def OnOpenFolder(self, evt):
        selection = self.results_panel.get_selection()
        if not selection:
            return
        item = selection[0]
        path = item["filepath"]
        utils.open_on_file(path)

    async def OnGeneratePreviews(self, evt):
        selection = self.results_panel.get_selection()
        if len(selection) == 0:
            return

        await gui.dialogs.download.run(self.app, selection)
        # dialog = GeneratePreviewsDialog(self, selection, app=self.app)
        # dialog.CenterOnParent(wx.BOTH)
        # result = dialog.ShowModal()
        # if result == wx.ID_OK:
        #     print("OK")
        #     print(dialog.result)
        # dialog.Destroy()
        # self.Refresh()

    async def SubItemSelected(self, key, items):
        selected = len(items) > 0
        self.toolbar.EnableTool(wx.ID_SAVE, False)
        self.toolbar.EnableTool(ids.ID_GENERATE_PREVIEWS, selected)
        self.toolbar.EnableTool(ids.ID_OPEN_FOLDER, selected)

    async def search(self, query):
        self.statusbar.SetStatusText("Searching...")

        await self.results_panel.search(query)

        results = self.results_panel.results

        self.pub.publish(Key("search_finished"), results)
