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
        self.config = config
        self.api = ModelManagerAPI(config)
        self.frame = None

        wxasync.WxAsyncApp.__init__(self, *args, **kwargs)

    def OnInit(self):
        self.frame = MainWindow(self, None, -1, self.title)
        self.frame.SetClientSize(self.frame.FromDIP(wx.Size(1600, 800)))
        self.frame.Show()
        self.SetTopWindow(self.frame)

        wxasync.StartCoroutine(self.on_init_callback, self.frame)

        return True

    def SetStatusText(self, *args):
        self.frame.statusbar.SetStatusText(*args)

    def FromDIP(self, *args):
        if len(args) == 2 and isinstance(args[0], (int, float)):
            return self.frame.FromDIP(wx.Size(args[0], args[1]))
        elif len(args) == 1 and isinstance(args[0], tuple):
            return self.frame.FromDIP(wx.Size(args[0][0], args[0][1]))
        return self.frame.FromDIP(*args)

    async def on_init_callback(self):
        await self.frame.search("")
