import wx
import wx.aui
import wx.lib.newevent
import wxasync

from gui.api import ModelManagerAPI
from gui.main_window import MainWindow


class App(wxasync.WxAsyncApp):
    def __init__(self, server, config, *args, **kwargs):
        self.server = server
        self.title = "sd-model-manager"
        self.api = ModelManagerAPI(config)

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
