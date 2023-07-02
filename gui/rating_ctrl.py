import wx
import wx.lib.scrolledpanel as scrolled
from PIL import Image


RatingChangedEvent, EVT_RATING_CHANGED = wx.lib.newevent.NewCommandEvent()


def load_image(filepath):
    image = Image.open(filepath)
    image.load()
    image.thumbnail((24, 24), Image.Resampling.LANCZOS)
    width, height = image.size
    return wx.Bitmap.FromBufferRGBA(width, height, image.tobytes())


class RatingCtrl(wx.ScrolledCanvas):
    def __init__(self, parent, id=wx.ID_ANY, style=1):
        super().__init__(parent, id)

        self.rating = 0
        self.style = style

        self.bitmap_star_off = load_image("star_off.png")
        self.bitmap_star_on = load_image("star_on.png")

        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnClick)
        self.Bind(wx.EVT_RIGHT_DOWN, self.OnClick)

    def GetValue(self):
        return self.rating

    def ChangeValue(self, rating):
        self.rating = rating
        self.Refresh()

    def DoGetBestSize(self):
        return wx.Size((4 + (5 * (self.style * 2)) + 21, (self.style * 2) + 24))

    def OnPaint(self, event):
        dc = wx.PaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackgroundMode(wx.TRANSPARENT)
        dc.Clear()
        w = (self.style * 2) + 24

        for x in range(5):
            is_off = x >= self.rating / 2
            bitmap = self.bitmap_star_off if is_off else self.bitmap_star_on
            dc.DrawBitmap(bitmap, 3 + (w * x), 2, True)

    def OnClick(self, event):
        rating = self.rating
        if event.RightDown():
            self.rating = 0
        else:
            w = (self.style * 2) + 24
            if (event.GetX() < 3):
                self.rating = 0
            else:
                self.rating = int(min(10, (max(0, (event.GetX() - 3) * 2) / w + 1)))
        if rating == self.rating:
            self.rating = 0
        if rating != self.rating:
            self.Refresh()
            evt = RatingChangedEvent(wx.ID_ANY, rating=self.rating)
            wx.PostEvent(self, evt)
