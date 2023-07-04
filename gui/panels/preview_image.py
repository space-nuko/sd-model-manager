import aiopubsub
from aiopubsub import Key

import wx
import wx.aui
import wx.lib.newevent

from gui.image_panel import ImagePanel
from gui.utils import PUBSUB_HUB, find_image_for_model


class PreviewImagePanel(wx.Panel):
    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        self.roots = []

        wx.Panel.__init__(self, *args, **kwargs)

        self.image_view = ImagePanel(self, style=wx.SUNKEN_BORDER)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(
            self.image_view, 1, flag=wx.ALL | wx.EXPAND | wx.ALIGN_TOP, border=5
        )

        self.SetSizerAndFit(self.sizer)

        self.sub = aiopubsub.Subscriber(PUBSUB_HUB, Key("events"))
        self.sub.add_async_listener(
            Key("events", "item_selected"), self.SubItemSelected
        )

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
