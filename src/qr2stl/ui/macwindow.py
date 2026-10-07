"""Barra de título unificada en macOS: el contenido de Qt se extiende debajo de la barra de
título (los semáforos quedan encima, centrados en una barra de 52 px como en las apps
nativas) y la barra superior propia de la app hace de toolbar.

Se habla con AppKit por ctypes (runtime de Objective-C), sin dependencias extra. PySide 6.11
no expone Qt::ExpandedClientAreaHint.
"""
import ctypes
import ctypes.util
import sys

NS_FULL_SIZE_CONTENT_VIEW = 1 << 15
NS_WINDOW_TITLE_HIDDEN = 1
NS_TOOLBAR_STYLE_UNIFIED = 3
TITLEBAR_HEIGHT = 52          # alto de la barra con NSWindowToolbarStyleUnified
TRAFFIC_LIGHTS_WIDTH = 78     # espacio que ocupan cerrar/minimizar/zoom

_objc = None


def _lib():
    global _objc
    if _objc is None:
        _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        _objc.objc_getClass.restype = ctypes.c_void_p
        _objc.objc_getClass.argtypes = [ctypes.c_char_p]
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.sel_registerName.argtypes = [ctypes.c_char_p]
        ctypes.cdll.LoadLibrary(ctypes.util.find_library("AppKit"))
    return _objc


def _send(obj, selector, *args, restype=ctypes.c_void_p, argtypes=()):
    """objc_msgSend con el prototipo exacto (en arm64 no se puede llamar como variádica)."""
    lib = _lib()
    proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
    fn = proto(ctypes.cast(lib.objc_msgSend, ctypes.c_void_p).value)
    return fn(obj, lib.sel_registerName(selector.encode()), *args)


def _cls(name):
    return _lib().objc_getClass(name.encode())


def _nsstring(text):
    return _send(_cls("NSString"), "stringWithUTF8String:", text.encode(),
                 argtypes=[ctypes.c_char_p])


def supported():
    return sys.platform == "darwin"


def unify_title_bar(widget) -> bool:
    """Aplica el estilo a la ventana nativa del widget. Devuelve False si no se pudo."""
    if not supported():
        return False
    try:
        view = ctypes.c_void_p(int(widget.winId()))
        window = _send(view, "window")
        if not window:
            return False
        mask = _send(window, "styleMask", restype=ctypes.c_ulong)
        _send(window, "setStyleMask:", mask | NS_FULL_SIZE_CONTENT_VIEW,
              restype=None, argtypes=[ctypes.c_ulong])
        _send(window, "setTitlebarAppearsTransparent:", True,
              restype=None, argtypes=[ctypes.c_bool])
        _send(window, "setTitleVisibility:", NS_WINDOW_TITLE_HIDDEN,
              restype=None, argtypes=[ctypes.c_long])
        if not _send(window, "toolbar"):
            toolbar = _send(_send(_cls("NSToolbar"), "alloc"), "initWithIdentifier:",
                            _nsstring("qr2stl"), argtypes=[ctypes.c_void_p])
            _send(window, "setToolbar:", toolbar, restype=None, argtypes=[ctypes.c_void_p])
        _send(window, "setToolbarStyle:", NS_TOOLBAR_STYLE_UNIFIED,
              restype=None, argtypes=[ctypes.c_long])
        return True
    except (OSError, AttributeError, ValueError):
        return False
