# -*- coding: utf-8 -*-
"""สร้างรูปตัวอย่างสำหรับ README (ไม่แคปหน้าจอจริง: จำลองด้วย physics ตัวเดียวกับแอปแล้ววาดลงรูป)

    python tools/make_demo.py

ได้ไฟล์:
    docs/demo.gif    ภาพเคลื่อนไหวการใช้ทุกอาวุธ
    docs/menu.png    หน้าตาเมนูที่ tray (ไทย + English)
"""
import math
import os
import random
import sys

from PIL import Image
from PyQt5 import QtGui, QtWidgets
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPolygonF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import slap_cursor as sc  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
W, H = 720, 405
FPS = 25
DT = 1.0 / FPS


def qimage_to_pil(img):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    ptr = img.constBits()
    ptr.setsize(img.byteCount())
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(ptr), "raw", "RGBA", 0, 1)


def draw_desktop(p):
    """พื้นหลังแบบเดสก์ท็อปทั่วไป (ไม่มีโลโก้/ข้อมูลจริง)"""
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor(40, 48, 78))
    g.setColorAt(1, QColor(22, 24, 36))
    p.fillRect(0, 0, W, H, g)
    p.setPen(Qt.NoPen)
    for x, y, w, h, a in ((40, 40, 300, 190, 46), (390, 70, 290, 220, 34)):   # หน้าต่างจางๆ
        p.setBrush(QColor(255, 255, 255, a))
        p.drawRoundedRect(QRectF(x, y, w, h), 10, 10)
        p.setBrush(QColor(255, 255, 255, a + 14))
        p.drawRoundedRect(QRectF(x, y, w, 26), 10, 10)
        for i in range(4):
            p.setBrush(QColor(255, 255, 255, a - 10))
            p.drawRoundedRect(QRectF(x + 18, y + 46 + i * 30, w * (0.75 - 0.12 * (i % 3)), 12), 6, 6)
    p.setBrush(QColor(12, 13, 20, 235))                                       # taskbar
    p.drawRect(QRectF(0, H - 34, W, 34))
    for i in range(5):
        p.setBrush(QColor(255, 255, 255, 60 if i else 120))
        p.drawRoundedRect(QRectF(W / 2 - 95 + i * 40, H - 27, 22, 20), 5, 5)


def draw_cursor(p, pos, pressed):
    pts = [(0, 0), (0, 17), (4.5, 13), (8, 20), (11, 19), (7.5, 12), (13, 12)]
    poly = QPolygonF([QPointF(pos.x() + x, pos.y() + y) for x, y in pts])
    p.setPen(QtGui.QPen(QColor(0, 0, 0), 1.4))
    p.setBrush(QColor(255, 220, 120) if pressed else QColor(255, 255, 255))
    p.drawPolygon(poly)


def draw_caption(p, text):
    f = QFont("Leelawadee UI")
    f.setPixelSize(17)
    f.setBold(True)
    p.setFont(f)
    r = QRectF(14, 12, p.fontMetrics().horizontalAdvance(text) + 26, 32)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 150))
    p.drawRoundedRect(r, 16, 16)
    p.setPen(QColor(255, 255, 255))
    p.drawText(r, Qt.AlignCenter, text)


def scene(key, caption, path, clicks, seconds, size=1.0, life=None):
    """path(t) = ตำแหน่งเมาส์ตามเวลา, clicks = เวลาที่คลิก (วินาที)"""
    ov = sc.Overlay(next(i for i, t in enumerate(sc.TOOLS) if t["key"] == key), size, "th")
    ov.mute = True
    if life:
        ov.larb_life = life
    ov.cur = path(0.0)
    ov.reset_motion()
    for _ in range(40):                        # ให้ของนิ่งก่อนเริ่มถ่าย
        ov.advance(DT, ov.cur, False)
    frames, pending, t = [], sorted(clicks), 0.0
    while t < seconds:
        click = bool(pending) and t >= pending[0]
        if click:
            pending.pop(0)
        cur = path(t)
        ov.advance(DT, cur, click)
        img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        draw_desktop(p)
        ov.paint_scene(p)
        draw_cursor(p, cur, click)
        draw_caption(p, caption)
        p.end()
        frames.append(qimage_to_pil(img))
        t += DT
    return frames


def still(x, y):
    return lambda t: QPointF(x, y)


def drift(x0, y0, x1, y1, period):
    return lambda t: QPointF(lerp(x0, x1, 0.5 - 0.5 * math.cos(t * 6.283 / period)),
                             lerp(y0, y1, 0.5 - 0.5 * math.cos(t * 6.283 / period)))


def lerp(a, b, k):
    return a + (b - a) * k


def make_gif():
    random.seed(4)
    frames = []
    frames += scene("whip", "แส้ · Whip", still(470, 120), [0.2, 1.1], 1.9)
    frames += scene("belt", "เข็มขัด · Belt", still(430, 150), [0.2, 0.9], 1.6)
    frames += scene("flipflop", "รองเท้าแตะ · Flip-flop", drift(330, 260, 470, 240, 2.4),
                    [0.2, 0.55, 0.9, 1.25], 1.8)
    frames += scene("stick", "ไม้เรียว · Stick", still(400, 270), [0.2, 0.75], 1.4)
    frames += scene("hand", "มือตบ · Slap", still(380, 260), [0.2, 0.5, 0.8], 1.5)
    frames += scene("bear", "ตุ๊กตาหมี · Care bears", drift(250, 200, 470, 230, 2.8),
                    [0.6, 1.4], 2.2)
    frames += scene("larb", "ลาบไอฟร้อง · Throw larb", drift(300, 150, 460, 170, 4.0),
                    [0.2, 0.55, 0.95], 3.6, life=2.5)
    pal = [f.convert("RGB").quantize(colors=255, method=Image.FASTOCTREE, dither=Image.NONE)
           for f in frames]
    out = os.path.join(DOCS, "demo.gif")
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=int(1000 / FPS), loop=0,
                optimize=True, disposal=1)
    print("demo.gif", len(frames), "frames", os.path.getsize(out) // 1024, "KB")


def make_menu(lang):
    """สร้างเมนูหน้าตาเดียวกับใน tray แล้วถ่ายรูปเมนู"""
    T = sc.STR[lang]
    menu = QtWidgets.QMenu()
    power = menu.addAction(T["turn_off"])
    f = power.font()
    f.setBold(True)
    power.setFont(f)
    menu.addSeparator()
    menu.addAction(T["title"]).setEnabled(False)
    for i, tool in enumerate(sc.TOOLS):
        a = menu.addAction(sc.make_icon(tool), tool["name"][lang])
        a.setCheckable(True)
        a.setChecked(tool["key"] == "larb")
    menu.addSeparator()
    menu.addAction(T["rename"])
    menu.addMenu(T["fade"])
    menu.addSeparator()
    menu.addMenu(T["size"])
    menu.addMenu(T["lang"])
    menu.addMenu(T["volume"])
    menu.addSeparator()
    menu.addAction(T["quit"])
    menu.ensurePolished()
    menu.adjustSize()
    return menu.grab().toImage()


def make_menus():
    th, en = make_menu("th"), make_menu("en")
    pad = 24
    img = QImage(th.width() + en.width() + pad * 3, max(th.height(), en.height()) + pad * 2,
                 QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    g = QLinearGradient(0, 0, img.width(), img.height())
    g.setColorAt(0, QColor(40, 48, 78))
    g.setColorAt(1, QColor(22, 24, 36))
    p.fillRect(img.rect(), g)
    p.drawImage(pad, pad, th)
    p.drawImage(pad * 2 + th.width(), pad, en)
    p.end()
    img.save(os.path.join(DOCS, "menu.png"))
    print("menu.png", img.width(), "x", img.height())


if __name__ == "__main__":
    QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QtWidgets.QApplication(sys.argv)
    sc.HEART = sc.heart_path()
    os.makedirs(DOCS, exist_ok=True)
    make_menus()
    make_gif()
