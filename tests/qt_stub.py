"""A fake PySide6 so GUI code can be import- and smoke-tested where Qt isn't installed.
It only catches Python mistakes (typos, wrong names), not wrong Qt usage."""
import sys
import types


class Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Dummy()


class Dummy(metaclass=Meta):
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Dummy()

    def __call__(self, *a, **k):
        return Dummy()

    def __or__(self, o):
        return Dummy()

    __ror__ = __and__ = __rand__ = __or__

    def __int__(self):
        return 0

    __index__ = __int__

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return True


class QLineEdit(Dummy):
    class EchoMode:
        Password = 1
        Normal = 0

    def __init__(self, text="", *a):
        self._t = text if isinstance(text, str) else ""
        self._ch = []
        self.textChanged = _Sig(self._ch)
        self.textEdited = _Sig([])

    def setText(self, t):
        self._t = t
        for f in self._ch:
            f(t)

    def text(self):
        return self._t


class _Sig:
    def __init__(self, store):
        self.store = store

    def connect(self, f):
        self.store.append(f)

    def emit(self, *a):
        for f in self.store:
            f(*a)


class QSpinBox(Dummy):
    def __init__(self, *a):
        self._v = 0

    def setValue(self, v):
        self._v = v

    def value(self):
        return self._v


class QCheckBox(Dummy):
    def __init__(self, *a):
        self._c = False

    def setChecked(self, c):
        self._c = bool(c)

    def isChecked(self):
        return self._c


class QComboBox(Dummy):
    def __init__(self, *a):
        self._items = []
        self._i = 0

    def addItem(self, text, data=None):
        self._items.append((text, data))

    def findData(self, data):
        for i, (_t, d) in enumerate(self._items):
            if d == data:
                return i
        return -1

    def setCurrentIndex(self, i):
        self._i = i

    def currentData(self):
        return self._items[self._i][1] if self._items else None


class QPointF:
    def __init__(self, x=0.0, y=0.0):
        self._x = x if isinstance(x, (int, float)) else 0.0
        self._y = y if isinstance(y, (int, float)) else 0.0

    def x(self):
        return self._x

    def y(self):
        return self._y


class QRectF:
    def __init__(self, x=0.0, y=0.0, w=400.0, h=120.0):
        if not isinstance(x, (int, float)):
            x, y, w, h = 0.0, 0.0, 400.0, 120.0
        self.x0, self.y0, self.w, self.h = float(x), float(y), float(w), float(h)

    def left(self): return self.x0
    def top(self): return self.y0
    def right(self): return self.x0 + self.w
    def bottom(self): return self.y0 + self.h
    def width(self): return self.w
    def height(self): return self.h
    def setWidth(self, w): self.w = w
    def center(self): return QPointF(self.x0 + self.w / 2, self.y0 + self.h / 2)

    def adjusted(self, a, b, c, d):
        return QRectF(self.x0 + a, self.y0 + b, self.w - a + c, self.h - b + d)


class Signal:
    def __init__(self, *a):
        pass

    def __set_name__(self, owner, name):
        self.name = "_sig_" + name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        if self.name not in obj.__dict__:
            obj.__dict__[self.name] = _Sig([])
        return obj.__dict__[self.name]


SPECIAL = {"QLineEdit": QLineEdit, "QSpinBox": QSpinBox, "QCheckBox": QCheckBox, "QComboBox": QComboBox, "QRectF": QRectF, "QPointF": QPointF, "Signal": Signal}


def install():
    root = types.ModuleType("PySide6")
    root.__path__ = []
    sys.modules["PySide6"] = root
    for name in ("QtCore", "QtGui", "QtWidgets", "QtSvg"):
        mod = types.ModuleType("PySide6." + name)

        def getattr_(attr, _mod=mod):
            if attr.startswith("__"):
                raise AttributeError(attr)
            cls = SPECIAL.get(attr) or Meta(attr, (Dummy,), {})
            setattr(_mod, attr, cls)
            return cls

        mod.__getattr__ = getattr_
        sys.modules["PySide6." + name] = mod
        setattr(root, name, mod)
