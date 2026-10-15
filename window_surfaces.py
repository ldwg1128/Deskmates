"""Read-only Windows window ledges, converted from native pixels to Qt coordinates.

No foreign process is controlled. See EnumWindows/GetWindowRect/DWM documentation:
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-enumwindows
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getwindowrect
"""
from __future__ import annotations
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
import sys
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class WindowSurface:
    handle: int
    rect: QRectF


def select_ledge(surfaces, point, body_height, area):
    """Surfaces are front-to-back; don't perch on an obscured lower window."""
    tolerance=max(18,body_height*.16)
    for index,surface in enumerate(surfaces):
        rect=surface.rect
        corner=max(24,body_height*.22)
        side=-1 if abs(point.x()-rect.left())<=corner else 1 if abs(point.x()-rect.right())<=corner else 0
        on_side=side and rect.top()-tolerance<=point.y()<=rect.bottom()
        on_top=(rect.left()<=point.x()<=rect.right() and abs(point.y()-rect.top())<=tolerance
                and rect.top()>=area.top()+body_height*.65+8)
        if not (on_side or on_top): continue
        if not on_side: side=0
        contact=QPointF(rect.left()+2 if side<0 else rect.right()-2 if side>0 else point.x(),
                        max(rect.top()+2,min(rect.bottom()-2,point.y())) if side else rect.top()+2)
        if any(other.rect.contains(contact) for other in surfaces[:index]): continue
        return surface,side
    return None


class WindowsSurfaces:
    def __init__(self, *, enabled=True, exclude_process=None):
        self.enabled=enabled and sys.platform=='win32'
        self.exclude_process=os.getpid() if exclude_process is None else exclude_process
        if not self.enabled: return
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.dwm=ctypes.WinDLL('dwmapi',use_last_error=True)
        self.callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        self.user.EnumWindows.argtypes=[self.callback_type,wintypes.LPARAM]
        self.user.EnumWindows.restype=wintypes.BOOL
        for name in ('IsWindowVisible','IsIconic','IsWindow'):
            fn=getattr(self.user,name); fn.argtypes=[wintypes.HWND]; fn.restype=wintypes.BOOL
        self.user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowThreadProcessId.restype=wintypes.DWORD
        self.user.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int]; self.user.GetWindowLongW.restype=wintypes.LONG
        self.user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]; self.user.GetWindowRect.restype=wintypes.BOOL
        self.user.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD]; self.user.MonitorFromWindow.restype=wintypes.HMONITOR
        self.user.GetMonitorInfoW.argtypes=[wintypes.HMONITOR,ctypes.c_void_p]; self.user.GetMonitorInfoW.restype=wintypes.BOOL
        self.dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        self.dwm.DwmGetWindowAttribute.restype=wintypes.LONG

    def get(self,handle):
        if not self.enabled or not self.user.IsWindow(handle) or not self.user.IsWindowVisible(handle) or self.user.IsIconic(handle): return None
        pid=wintypes.DWORD()
        self.user.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        if pid.value==self.exclude_process: return None
        if not self.user.GetWindowLongW(handle,-16)&0x00C00000: return None  # caption
        if self.user.GetWindowLongW(handle,-20)&0x80: return None  # tool window
        cloaked=wintypes.DWORD()
        if self.dwm.DwmGetWindowAttribute(handle,14,ctypes.byref(cloaked),ctypes.sizeof(cloaked))==0 and cloaked.value: return None
        rect=wintypes.RECT()
        if self.dwm.DwmGetWindowAttribute(handle,9,ctypes.byref(rect),ctypes.sizeof(rect))!=0:
            if not self.user.GetWindowRect(handle,ctypes.byref(rect)): return None
        if rect.right-rect.left<160 or rect.bottom-rect.top<80: return None
        class MonitorInfo(ctypes.Structure):
            _fields_=[('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),
                      ('flags',wintypes.DWORD),('device',wintypes.WCHAR*32)]
        info=MonitorInfo(); info.size=ctypes.sizeof(info)
        screen=None
        if self.user.GetMonitorInfoW(self.user.MonitorFromWindow(handle,2),ctypes.byref(info)):
            screen=next((s for s in QGuiApplication.screens() if s.name().casefold()==info.device.casefold()),None)
        if screen:
            origin=screen.geometry().topLeft(); ratio=screen.devicePixelRatio()
            mapped=QRectF(origin.x()+(rect.left-info.monitor.left)/ratio,
                          origin.y()+(rect.top-info.monitor.top)/ratio,
                          (rect.right-rect.left)/ratio,(rect.bottom-rect.top)/ratio)
        else: mapped=QRectF(rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top)
        return WindowSurface(int(handle),mapped)

    def all(self):
        if not self.enabled: return []
        result=[]
        @self.callback_type
        def visit(handle,_):
            surface=self.get(handle)
            if surface: result.append(surface)
            return True
        self.user.EnumWindows(visit,0)
        return result
