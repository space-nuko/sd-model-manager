import wx
import wxasync
import asyncio
from asyncio.locks import Event
from wx._html import HtmlHelpDialog
from wx._adv import PropertySheetDialog


async def on_button(dlg, event):
    # Same code as in wxwidgets:/src/common/dlgcmn.cpp:OnButton
    # to automatically handle OK, CANCEL, APPLY,... buttons
    id = event.GetId()
    if id == dlg.GetAffirmativeId():
        if dlg.Validate() and dlg.TransferDataFromWindow():
            dlg.AsyncEndModal(id)
    elif id == wx.ID_APPLY:
        if dlg.Validate():
            dlg.TransferDataFromWindow()
    elif id == dlg.GetEscapeId() or (
        id == wx.ID_CANCEL and dlg.GetEscapeId() == wx.ID_ANY
    ):
        dlg.AsyncEndModal(wx.ID_CANCEL)
    else:
        event.Skip()


async def on_close(dlg, event):
    dlg._closed.set()
    dlg.Hide()


async def AsyncShowDialog(dlg):
    if type(dlg) in [
        wx.FileDialog,
        wx.DirDialog,
        wx.FontDialog,
        wx.ColourDialog,
        wx.MessageDialog,
    ]:
        raise Exception(
            "This type of dialog cannot be shown modalless, please use 'AsyncShowDialogModal'"
        )
    closed = Event()

    def end_dialog(return_code):
        dlg.SetReturnCode(return_code)
        dlg.Hide()
        closed.set()

    dlg._closed = closed
    dlg.AsyncEndModal = end_dialog

    # wxasync.AsyncBind(wx.EVT_CLOSE, on_close, dlg)
    # wxasync.AsyncBind(wx.EVT_BUTTON, on_button, dlg)
    dlg.Show()
    await closed.wait()
    return dlg.GetReturnCode()


async def AsyncShowDialogModal(dlg):
    if type(dlg) in [
        HtmlHelpDialog,
        wx.FileDialog,
        wx.DirDialog,
        wx.FontDialog,
        wx.ColourDialog,
        wx.MessageDialog,
    ]:
        return await wxasync.ShowModalInExecutor(dlg)
    else:
        frames = set(wx.GetTopLevelWindows()) - set([dlg])
        states = {frame: frame.IsEnabled() for frame in frames}
        try:
            for frame in frames:
                frame.Disable()
            return await AsyncShowDialog(dlg)
        finally:
            try:
                for frame in frames:
                    if bool(frame):
                        frame.Enable(states[frame])
            finally:
                parent = dlg.GetParent()
                if parent:
                    parent.SetFocus()
