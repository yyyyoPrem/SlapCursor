# -*- coding: utf-8 -*-
"""SlapCursor - แอปโง่ๆ เอาไว้ตีหน้าจอ (เวอร์ชัน physics)
อยู่ใน system tray -> เลือกอาวุธ -> คลิกซ้ายที่ไหนก็ได้บนจอ = ฟาด + เสียง + ข้อความ
Ctrl+Shift+F12 = เปิด/ปิดการทำงาน (โปรแกรมยังอยู่ใน tray)

หลัก physics ที่ใช้
- มือ (มุมของด้ามจับ) = สปริง + ตัวหน่วง : เงื้อ -> ฟาด -> เด้งกลับ -> สั่นจนหยุด
- แส้ / เข็มขัด = เชือกแบบ Verlet (จุดต่อกันเป็นโซ่ มีแรงโน้มถ่วง + ความแข็งการงอ)
- ไม้ / รองเท้าแตะ / มือ = ของแข็งที่งอได้นิดหน่อย (flex) ตามความเร่งเชิงมุม
- ขยับเมาส์เร็วๆ อาวุธจะเหวี่ยงตามแรงเฉื่อย
"""
import ctypes
import math
import os
import random
import sys
import time
import wave
import winreg
import winsound

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)

HERE = os.path.dirname(os.path.abspath(__file__))
SOUND_DIR = os.path.join(HERE, "sounds")
user32 = ctypes.windll.user32

# ================================================================ เสียง
SR = 44100


def _lowpass(x, k):
    return np.convolve(x, np.ones(k) / k, "same")


def _decay(n, tau):
    return np.exp(-np.arange(n) / SR / tau)


def _noise(n, seed):
    return np.random.default_rng(seed).uniform(-1, 1, n)


def _sine(n, f):
    return np.sin(2 * np.pi * f * np.arange(n) / SR)


def synth(kind):
    """สังเคราะห์เสียงเอง ไม่ต้องมีไฟล์เสียงจากที่อื่น"""
    if kind == "whip":  # เปรี้ยะ! (เสียงแตกสั้นคม + หางก้อง)
        n = int(SR * 0.30)
        c = _noise(n, 2)
        c = c - _lowpass(c, 4)
        out = c * (_decay(n, 0.008) + 0.25 * _decay(n, 0.07))
    elif kind == "belt":  # เพี๊ยะ! หนังฟาด
        n = int(SR * 0.25)
        c = _lowpass(_noise(n, 3), 3)
        out = c * (_decay(n, 0.018) + 0.15 * _decay(n, 0.06))
        out += 0.5 * _sine(n, 190) * _decay(n, 0.03)
    elif kind == "flipflop":  # ป้าบ! ยางนุ่มๆ
        n = int(SR * 0.25)
        out = _lowpass(_noise(n, 4), 10) * _decay(n, 0.03) * 2.2
        out += 0.8 * _sine(n, 140) * _decay(n, 0.05)
    elif kind == "stick":  # โป๊ก! ไม้
        n = int(SR * 0.22)
        out = sum(a * _sine(n, f) for f, a in ((520, 1), (1130, .6), (1740, .35)))
        out = out * _decay(n, 0.03)
        nc = int(SR * 0.004)
        out[:nc] += _noise(nc, 5) * 1.2
    elif kind == "hand":  # เพี๊ยะ! ตบ
        n = int(SR * 0.28)
        c = _noise(n, 6)
        c = _lowpass(c, 3) - _lowpass(c, 14)
        out = c * (_decay(n, 0.022) + 0.22 * _decay(n, 0.09)) * 2
    elif kind == "larb":  # แผละ! เปียกๆ มันๆ
        n = int(SR * 0.5)
        t = np.arange(n) / SR
        out = 1.1 * np.sin(2 * np.pi * (95 - 60 * t) * t) * _decay(n, 0.05)   # ตุ้บ ทุ้มๆ
        out += _lowpass(_noise(n, 7), 22) * _decay(n, 0.04) * 5.0             # แปะ
        sq = _noise(n, 8)
        sq = _lowpass(sq, 5) - _lowpass(sq, 45)                               # เสียงแฉะ
        out += sq * _decay(n, 0.11) * 1.3 * (0.55 + 0.45 * np.sin(2 * np.pi * 27 * t))
        rng = np.random.default_rng(9)
        for s0 in rng.integers(int(SR * 0.06), int(SR * 0.33), 9):            # เศษกระเด็น
            m = int(SR * 0.012)
            out[s0:s0 + m] += _lowpass(_noise(m, int(s0)), 6) * _decay(m, 0.004) * 0.9
    else:  # bear: กริ๊งๆ น่ารัก
        n = int(SR * 0.75)
        out = np.zeros(n)
        for i, f in enumerate((1047, 1319, 1568, 2093)):
            s = int(SR * 0.085 * i)
            m = n - s
            out[s:] += (_sine(m, f) + 0.3 * _sine(m, f * 2)) * _decay(m, 0.16)
    out = out / np.max(np.abs(out)) * 0.85
    return (out * 32767).astype(np.int16)


SOUND_VERSION = "4"
_BASE = {}


def ensure_sounds(volume=100):
    """เขียนไฟล์ wav ตามระดับเสียง (winsound ปรับ volume ตรงๆ ไม่ได้ เลยคูณความดังลงไฟล์แทน)"""
    os.makedirs(SOUND_DIR, exist_ok=True)
    stamp = os.path.join(SOUND_DIR, "version.txt")
    want = "%s:%d" % (SOUND_VERSION, volume)
    if os.path.exists(stamp) and open(stamp).read().strip() == want:
        return
    gain = (volume / 100.0) ** 1.6      # หูคนได้ยินแบบ log เลยใช้ยกกำลังให้รู้สึกลดสม่ำเสมอ
    for kind in ("whip", "belt", "flipflop", "stick", "hand", "bear", "larb"):
        if kind not in _BASE:
            _BASE[kind] = synth(kind).astype(np.float64)
        with wave.open(os.path.join(SOUND_DIR, kind + ".wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((_BASE[kind] * gain).astype(np.int16).tobytes())
    with open(stamp, "w") as f:
        f.write(want)


def play(kind):
    try:
        winsound.PlaySound(
            os.path.join(SOUND_DIR, kind + ".wav"),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except RuntimeError:
        pass


# ================================================================ วาดอาวุธ
# พิกัดในฟังก์ชันวาด: (0,0) = จุดที่มือจับ (ตำแหน่งเมาส์) ตัวอาวุธยื่นขึ้นไปทาง -y
OUTLINE = QColor(40, 22, 12)


def _pen(color, w):
    return QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def _grad(x0, x1, stops):
    g = QLinearGradient(x0, 0, x1, 0)
    for pos, col in stops:
        g.setColorAt(pos, QColor(*col))
    return g


GOLD = ((0, (140, 96, 16)), (0.3, (255, 228, 130)), (0.6, (212, 164, 52)), (1, (112, 76, 12)))
SILVER = ((0, (104, 110, 122)), (0.3, (244, 246, 250)), (0.6, (172, 178, 190)), (1, (84, 90, 102)))
_CACHE = {}


def _flipflop_shapes():
    if "ff" not in _CACHE:
        s = QPainterPath()
        s.moveTo(0, -8)                               # ส้นเท้า -> วนขึ้นไปปลายเท้า
        s.cubicTo(20, -8, 29, -30, 25, -60)
        s.cubicTo(22, -85, 36, -104, 36, -128)
        s.cubicTo(36, -152, 21, -165, 2, -165)
        s.cubicTo(-18, -165, -32, -150, -32, -125)
        s.cubicTo(-32, -100, -23, -85, -24, -60)
        s.cubicTo(-26, -30, -20, -8, 0, -8)
        inner = QTransform().translate(2, -86).scale(0.84, 0.9).translate(-2, 86).map(s)
        dots = QPainterPath()
        for r, y in enumerate(range(-160, -8, 7)):
            for x in range(-32, 38, 7):
                dots.addEllipse(QPointF(x + (3.5 if r % 2 else 0), y), 1.0, 1.0)
        _CACHE["ff"] = (s, inner, dots)
    return _CACHE["ff"]


def draw_flipflop(p):
    sole, inner, dots = _flipflop_shapes()
    p.setPen(_pen(OUTLINE, 2.5))
    p.setBrush(QColor(20, 66, 138))
    p.drawPath(sole.translated(3.5, 4.5))             # ความหนาของพื้นยาง
    p.setBrush(_grad(-34, 38, ((0, (30, 104, 196)), (0.45, (66, 150, 236)), (1, (28, 96, 184)))))
    p.drawPath(sole)
    p.save()
    p.setClipPath(inner)
    p.setPen(Qt.NoPen)
    p.setBrush(_grad(-30, 34, ((0, (96, 172, 246)), (0.5, (140, 206, 255)), (1, (92, 166, 240)))))
    p.drawPath(inner)
    p.setBrush(QColor(30, 100, 186, 95))              # ลายกันลื่น
    p.drawPath(dots)
    p.setBrush(QColor(20, 80, 160, 55))               # รอยเท้าสึก
    p.drawEllipse(QPointF(0, -40), 14, 18)
    p.drawEllipse(QPointF(3, -118), 19, 16)
    p.restore()
    strap = QPainterPath()
    strap.moveTo(-25, -70)
    strap.quadTo(-23, -108, 2, -134)
    strap.quadTo(25, -108, 27, -70)
    p.setBrush(Qt.NoBrush)
    for col, w in ((OUTLINE, 12.5), (QColor(238, 180, 30), 8.5), (QColor(255, 236, 150, 210), 2.4)):
        p.setPen(_pen(col, w))
        p.drawPath(strap)
    p.setPen(_pen(OUTLINE, 2))
    p.setBrush(QColor(206, 148, 20))
    for x, y in ((-25, -70), (27, -70), (2, -134)):
        p.drawEllipse(QPointF(x, y), 5.2, 5.2)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 240, 170))
    p.drawEllipse(QPointF(0.5, -135.5), 1.8, 1.8)


def draw_stick(p):
    """ไม้กระดานเก่า: ปลายแตก มีลายไม้ ตาไม้ ตะปู และผ้าพันด้าม"""
    body = QPainterPath()
    body.moveTo(-10, 12)
    for x, y in ((-11, -150), (-9, -172), (-4, -165), (0, -179), (5, -169), (10, -176),
                 (11, -150), (10, 12)):
        body.lineTo(x, y)
    body.closeSubpath()
    p.setPen(_pen(OUTLINE, 2.5))
    p.setBrush(_grad(-11, 11, ((0, (112, 68, 34)), (0.28, (196, 138, 80)), (0.62, (168, 110, 58)),
                               (1, (96, 56, 26)))))
    p.drawPath(body)
    p.save()
    p.setClipPath(body)
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(QColor(104, 62, 30, 190), 1.2))     # ลายไม้
    for x0, wob in ((-7, 2), (-3.5, -2), (2, 3), (6.5, -2)):
        g = QPainterPath()
        g.moveTo(x0, 12)
        g.cubicTo(x0 + wob, -40, x0 - wob, -100, x0 + wob * 0.5, -180)
        p.drawPath(g)
    for r in (2.0, 4.2, 6.6):                         # ตาไม้
        p.drawEllipse(QPointF(1.5, -112), r * 0.8, r * 1.25)
    p.setPen(_pen(QColor(240, 196, 140, 110), 2.2))   # แสงสะท้อน
    p.drawLine(QPointF(-6.5, 0), QPointF(-7, -150))
    p.setPen(_pen(QColor(50, 26, 10), 1.3))           # รอยแตก
    p.drawPolyline(QPolygonF([QPointF(0, -179), QPointF(1.5, -160), QPointF(-1, -148),
                              QPointF(1, -134)]))
    p.restore()
    for x, y in ((4, -146), (-4, -70)):               # ตะปู
        p.setPen(_pen(QColor(50, 52, 58), 1.2))
        p.setBrush(QColor(170, 176, 186))
        p.drawEllipse(QPointF(x, y), 2.6, 2.6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(245, 247, 250))
        p.drawEllipse(QPointF(x - 0.8, y - 0.8), 0.9, 0.9)
    grip = QRectF(-12, -40, 24, 50)                   # ผ้าพันด้าม
    p.setPen(_pen(OUTLINE, 2.2))
    p.setBrush(_grad(-12, 12, ((0, (150, 140, 122)), (0.3, (238, 230, 212)), (1, (132, 122, 104)))))
    p.drawRoundedRect(grip, 4, 4)
    p.save()
    p.setClipRect(grip.adjusted(1, 1, -1, -1))
    p.setPen(_pen(QColor(120, 108, 90, 200), 1.3))
    for y in range(-52, 16, 8):
        p.drawLine(QPointF(-13, y + 9), QPointF(13, y))
    p.restore()


SKIN = ((0, (214, 152, 112)), (0.3, (255, 216, 180)), (0.7, (246, 198, 160)), (1, (204, 140, 100)))
SKIN_LINE = QColor(138, 82, 50)


def _finger(p, x, y, length, w, rot):
    p.save()
    p.translate(x, y)
    p.rotate(rot)
    p.setPen(_pen(SKIN_LINE, 2.2))
    p.setBrush(_grad(-w / 2, w / 2, SKIN))
    p.drawRoundedRect(QRectF(-w / 2, -length, w, length + 16), w / 2, w / 2)
    p.setPen(_pen(QColor(160, 96, 62, 190), 1.3))     # ข้อนิ้ว
    for f in (0.36, 0.68):
        p.drawArc(QRectF(-w / 2 + 2.5, -length * f - 3, w - 5, 6), 200 * 16, 140 * 16)
    p.restore()


def draw_hand(p):
    """ฝ่ามือหันเข้าหาเรา (ท่าตบ)"""
    arm = QPainterPath()
    arm.addPolygon(QPolygonF([QPointF(-14, -6), QPointF(-16, -72), QPointF(16, -72), QPointF(14, -6)]))
    p.setPen(_pen(SKIN_LINE, 2.2))
    p.setBrush(_grad(-16, 16, SKIN))
    p.drawPath(arm)
    p.setPen(_pen(QColor(24, 44, 110), 2.2))          # แขนเสื้อ + ปลายแขน
    p.setBrush(_grad(-21, 21, ((0, (40, 70, 170)), (0.35, (96, 136, 240)), (1, (34, 60, 150)))))
    p.drawRoundedRect(QRectF(-21, -30, 42, 44), 4, 4)
    p.setBrush(_grad(-23, 23, ((0, (70, 104, 210)), (0.35, (140, 172, 252)), (1, (60, 92, 196)))))
    p.drawRoundedRect(QRectF(-23, -40, 46, 14), 4, 4)
    p.setPen(_pen(QColor(24, 44, 110), 1.2))
    p.setBrush(QColor(240, 244, 255))
    p.drawEllipse(QPointF(13, -33), 2.6, 2.6)
    _finger(p, 33, -80, 40, 17, 50)                   # โป้ง
    for x, y, ln, w, rot in ((-25, -124, 44, 13.5, -10), (-9, -129, 58, 15, -3),
                             (7.5, -130, 64, 15.5, 2), (23, -126, 56, 15, 8)):
        _finger(p, x, y, ln, w, rot)
    palm = QPainterPath()
    palm.addRoundedRect(QRectF(-33, -134, 66, 76), 20, 20)
    mound = QPainterPath()
    mound.addEllipse(QPointF(22, -84), 18, 25)
    palm = palm.united(mound)
    g = QRadialGradient(QPointF(-6, -100), 52)
    g.setColorAt(0, QColor(255, 220, 188))
    g.setColorAt(1, QColor(232, 174, 134))
    p.setPen(_pen(SKIN_LINE, 2.2))
    p.setBrush(g)
    p.drawPath(palm)
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(QColor(170, 104, 70, 200), 1.5))    # ลายมือ
    for pts in (((8, -128), (-4, -98), (12, -66)), ((-27, -104), (-6, -112), (12, -120)),
                ((-29, -116), (-10, -126), (16, -130))):
        c = QPainterPath()
        c.moveTo(*pts[0])
        c.quadTo(QPointF(*pts[1]), QPointF(*pts[2]))
        p.drawPath(c)


def heart_path():
    h = QPainterPath()
    h.moveTo(0, 8)
    h.cubicTo(-16, -4, -9, -16, 0, -6)
    h.cubicTo(9, -16, 16, -4, 0, 8)
    return h


HEART = None  # สร้างหลังมี QApplication


def draw_bear(p, color):
    """หมีตัวเล็ก จุดกึ่งกลางอยู่ที่ (0,0) สูงราว 56px"""
    dark = color.darker(170)
    p.setPen(_pen(dark, 2))
    p.setBrush(color)
    p.drawEllipse(QPointF(-12, 22), 7, 8)
    p.drawEllipse(QPointF(12, 22), 7, 8)
    p.drawEllipse(QPointF(-19, 6), 6, 8)
    p.drawEllipse(QPointF(19, 6), 6, 8)
    p.drawEllipse(QPointF(0, 10), 16, 17)
    p.drawEllipse(QPointF(-13, -24), 7, 7)
    p.drawEllipse(QPointF(13, -24), 7, 7)
    p.drawEllipse(QPointF(0, -12), 17, 15)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 230))
    p.drawEllipse(QPointF(0, -7), 8, 6)
    p.drawEllipse(QPointF(0, 11), 9, 10)
    p.setBrush(QColor(50, 30, 30))
    p.drawEllipse(QPointF(-7, -15), 2.2, 2.6)
    p.drawEllipse(QPointF(7, -15), 2.2, 2.6)
    p.drawEllipse(QPointF(0, -9), 2.6, 1.8)
    p.save()
    p.translate(0, 11)
    p.scale(0.55, 0.55)
    p.setBrush(QColor(255, 80, 120))
    p.drawPath(HEART)
    p.restore()


LARB_PORK = [(168, 120, 84), (190, 142, 104), (150, 102, 70), (205, 165, 128), (178, 128, 92)]
LARB_BITS = LARB_PORK + [(58, 150, 60), (96, 180, 70), (206, 48, 28), (236, 196, 210)]


def _blob(rng, r):
    """ก้อนขอบมนไม่สม่ำเสมอ (หมูสับ 1 ก้อน / คราบน้ำมัน)"""
    n = rng.randint(6, 8)
    pts = []
    for i in range(n):
        a = i / n * 6.283 + rng.uniform(-0.25, 0.25)
        rr = r * rng.uniform(0.7, 1.15)
        pts.append(QPointF(math.cos(a) * rr, math.sin(a) * rr * rng.uniform(0.75, 1.0)))

    def mid(a, b):
        return QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
    path = QPainterPath()
    path.moveTo(mid(pts[-1], pts[0]))
    for i in range(n):
        path.quadTo(pts[i], mid(pts[i], pts[(i + 1) % n]))
    return path


def draw_larb(p, seed, R, splat=False):
    """ลาบ 1 ก้อน รัศมีราว R (splat=True คือตอนแปะจอ: แผ่กว้าง + คราบน้ำมันกระเด็น)"""
    rng = random.Random(seed)
    p.setPen(Qt.NoPen)
    if splat:
        p.setBrush(QColor(232, 150, 40, 100))             # คราบน้ำลาบ/น้ำมัน
        p.drawPath(_blob(rng, R * 1.3))
        p.setBrush(QColor(246, 190, 80, 70))
        p.drawPath(_blob(rng, R * 1.0))
        for _ in range(16):                               # ริ้วกระเด็นออกรอบๆ
            a, d = rng.uniform(0, 6.283), R * rng.uniform(1.0, 1.9)
            p.save()
            p.translate(math.cos(a) * d, math.sin(a) * d)
            p.rotate(math.degrees(a))
            p.setBrush(QColor(236, 160, 50, rng.randint(90, 160)))
            p.drawEllipse(QPointF(0, 0), R * rng.uniform(0.2, 0.55), R * rng.uniform(0.035, 0.08))
            p.restore()
        for _ in range(22):                               # หยดน้ำมันเล็กๆ
            a, d = rng.uniform(0, 6.283), R * rng.uniform(1.1, 2.25)
            r = R * rng.uniform(0.025, 0.075)
            p.setBrush(QColor(238, 156, 44, rng.randint(110, 190)))
            p.drawEllipse(QPointF(math.cos(a) * d, math.sin(a) * d), r, r)
    spread = R * (1.0 if splat else 0.72)
    spots = []
    for _ in range(50 if splat else 36):                  # หมูสับ
        a = rng.uniform(0, 6.283)
        d = spread * (math.sqrt(rng.random()) if splat else rng.random() ** 0.8)
        spots.append((math.sin(a) * d, math.cos(a) * d * (1.0 if splat else 0.85)))
    spots.sort(key=lambda q: q[1])
    for x, y in spots:
        col = QColor(*rng.choice(LARB_PORK))
        r = R * rng.uniform(0.13, 0.24)
        p.save()
        p.translate(x, y)
        p.rotate(rng.uniform(0, 360))
        g = QRadialGradient(QPointF(-r * 0.3, -r * 0.3), r * 1.4)
        g.setColorAt(0, col.lighter(128))
        g.setColorAt(1, col.darker(118))
        p.setPen(_pen(col.darker(170), max(0.8, R * 0.022)))
        p.setBrush(g)
        p.drawPath(_blob(rng, r))
        p.restore()
    p.setPen(Qt.NoPen)
    for _ in range(46):                                   # ข้าวคั่ว + พริกป่น
        a, d = rng.uniform(0, 6.283), spread * math.sqrt(rng.random()) * 1.05
        p.setBrush(QColor(*rng.choice([(226, 196, 138), (206, 48, 28), (240, 120, 40), (150, 30, 20)])))
        r = R * rng.uniform(0.018, 0.04)
        p.drawEllipse(QPointF(math.sin(a) * d, math.cos(a) * d), r, r)
    for _ in range(5):                                    # หอมแดงซอย
        a, d = rng.uniform(0, 6.283), spread * rng.random() * 0.85
        rr = R * rng.uniform(0.16, 0.26)
        p.save()
        p.translate(math.sin(a) * d, math.cos(a) * d)
        p.rotate(rng.uniform(0, 180))
        p.setPen(_pen(QColor(170, 88, 136), R * 0.04))
        p.setBrush(QColor(246, 216, 228, 185))
        p.drawEllipse(QPointF(0, 0), rr, rr * 0.5)
        p.setPen(_pen(QColor(190, 120, 160, 160), R * 0.02))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), rr * 0.6, rr * 0.28)
        p.restore()
    for _ in range(14):                                   # ผักชี ต้นหอม
        a, d = rng.uniform(0, 6.283), spread * math.sqrt(rng.random())
        p.save()
        p.translate(math.sin(a) * d, math.cos(a) * d)
        p.rotate(rng.uniform(0, 180))
        col = QColor(*rng.choice([(58, 150, 60), (96, 180, 70), (40, 120, 50)]))
        p.setPen(_pen(col.darker(160), R * 0.015))
        p.setBrush(col)
        w = R * rng.uniform(0.1, 0.2)
        p.drawRoundedRect(QRectF(-w, -R * 0.03, 2 * w, R * 0.06), R * 0.03, R * 0.03)
        p.restore()
    for _ in range(2 if splat else 1):                    # ใบสะระแหน่
        a, d = rng.uniform(0, 6.283), spread * rng.random() * 0.6
        L, W = R * rng.uniform(0.26, 0.36), R * rng.uniform(0.2, 0.26)
        leaf = QPainterPath()
        leaf.moveTo(-L, 0)
        leaf.quadTo(0, -W * 1.5, L, 0)
        leaf.quadTo(0, W * 1.5, -L, 0)
        p.save()
        p.translate(math.sin(a) * d, math.cos(a) * d - (0 if splat else R * 0.25))
        p.rotate(rng.uniform(0, 360))
        g = QLinearGradient(0, -W, 0, W)
        g.setColorAt(0, QColor(110, 196, 96))
        g.setColorAt(1, QColor(52, 140, 64))
        p.setPen(_pen(QColor(26, 96, 40), R * 0.025))
        p.setBrush(g)
        p.drawPath(leaf)
        p.setPen(_pen(QColor(26, 96, 40, 190), R * 0.018))
        p.drawLine(QPointF(-L * 0.85, 0), QPointF(L * 0.85, 0))
        for f in (-0.4, 0.0, 0.4):
            p.drawLine(QPointF(L * f, 0), QPointF(L * f + L * 0.22, -W * 0.45))
            p.drawLine(QPointF(L * f, 0), QPointF(L * f + L * 0.22, W * 0.45))
        p.restore()
    p.setPen(Qt.NoPen)
    for _ in range(12):                                   # ความมันเงา
        a, d = rng.uniform(0, 6.283), spread * math.sqrt(rng.random()) * 0.9
        p.save()
        p.translate(math.sin(a) * d, math.cos(a) * d)
        p.rotate(rng.uniform(0, 180))
        p.setBrush(QColor(255, 255, 255, rng.randint(90, 170)))
        p.drawEllipse(QPointF(0, 0), R * rng.uniform(0.03, 0.07), R * rng.uniform(0.012, 0.025))
        p.restore()


def larb_pixmap(seed, R, splat, dpr):
    """วาดลาบลงรูปครั้งเดียว แล้วใช้รูปนั้นซ้ำทุกเฟรม (ถูกกว่าวาดใหม่ทุกเฟรมมาก)"""
    half = int(R * (2.45 if splat else 1.25)) + 4
    pm = QPixmap(int(2 * half * dpr), int(2 * half * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(half, half)
    draw_larb(p, seed, R, splat)
    p.end()
    return pm, half


BEAR_COLORS = [QColor(255, 150, 196), QColor(130, 190, 255), QColor(255, 212, 100)]

# ================================================================ physics
REST, WIND, HIT = -35.0, 55.0, -105.0   # องศา: ท่าพัก / เงื้อ / จุดกระทบ
H = 1.0 / 240                           # ขั้นเวลาของ physics (วินาที)
FLEX_GAIN = 4.7e-4


def lerp(a, b, t):
    return a + (b - a) * t


class RigidSim:
    """ของแข็ง: ไม้ รองเท้าแตะ มือ - งอได้นิดหน่อยตามความเร่งเชิงมุม"""

    def __init__(self, tool):
        self.tool = tool
        self.flex = 0.0
        self.flexv = 0.0

    def reset(self, base, ang, S, straight=False):
        self.flex = self.flexv = 0.0

    def step(self, h, base, ang, alpha, S):
        k = self.tool["flexk"]
        acc = -520 * self.flex - 16 * self.flexv + alpha * FLEX_GAIN * k
        self.flexv += acc * h
        self.flex = max(-0.55, min(0.55, self.flex + self.flexv * h))

    def kick(self, dvel):
        self.flexv += dvel * FLEX_GAIN * self.tool["flexk"]

    def tip(self, base, ang, S):
        a, L = math.radians(ang), self.tool["tip"] * S
        return QPointF(base.x() + L * math.sin(a), base.y() - L * math.cos(a))

    def motion(self):
        return abs(self.flex) * 20 + abs(self.flexv)

    def bounds(self, base, S):
        r = (self.tool["tip"] + 70) * S + 20
        return QtCore.QRectF(base.x() - r, base.y() - r, 2 * r, 2 * r)

    def draw(self, p, base, ang, S):
        p.save()
        p.translate(base)
        p.rotate(ang)
        p.scale(S, S)
        p.shear(self.flex, 0)
        self.tool["draw"](p)
        p.restore()


class RopeSim:
    """เชือกแบบ Verlet: แส้ เข็มขัด
    p = ตำแหน่งปัจจุบันของแต่ละจุด, q = ตำแหน่งเฟรมก่อน (ความเร็ว = p - q)"""

    def __init__(self, tool):
        self.tool = tool
        self.n = tool["n"]
        self.seg = tool["seg"]
        self.hl = tool["handle"]
        s0, s1 = tool["stiff"]
        self.stiff = [lerp(s0, s1, i / (self.n - 3)) for i in range(self.n - 2)]
        self.p = [[0.0, 0.0] for _ in range(self.n)]
        self.q = [[0.0, 0.0] for _ in range(self.n)]

    def _anchor(self, base, ang, S):
        a = math.radians(ang)
        dx, dy = math.sin(a), -math.cos(a)
        return dx, dy, base.x() + dx * self.hl * S, base.y() + dy * self.hl * S

    def reset(self, base, ang, S, straight=False):
        dx, dy, hx, hy = self._anchor(base, ang, S)
        if not straight:
            dx, dy = 0.3, 1.0   # ห้อยลง
        for i in range(self.n):
            self.p[i] = [hx + dx * self.seg * S * i, hy + dy * self.seg * S * i]
            self.q[i] = list(self.p[i])

    def step(self, h, base, ang, alpha, S):
        dx, dy, hx, hy = self._anchor(base, ang, S)
        P, Q, n = self.p, self.q, self.n
        seg = self.seg * S
        g = self.tool["grav"] * S * h * h
        d = self.tool["damp"]
        vmax = 40.0 * S
        for i in range(2, n):
            x, y = P[i]
            vx, vy = (x - Q[i][0]) * d, (y - Q[i][1]) * d + g
            sp = math.hypot(vx, vy)
            if sp > vmax:
                vx, vy = vx * vmax / sp, vy * vmax / sp
            Q[i][0], Q[i][1] = x, y
            P[i][0], P[i][1] = x + vx, y + vy
        # สองจุดแรกยึดกับด้าม -> ส่งแรงหมุนของมือเข้าเชือก
        for i, m in ((0, 0.0), (1, 1.0)):
            Q[i][0], Q[i][1] = P[i]
            P[i][0], P[i][1] = hx + dx * seg * m, hy + dy * seg * m
        for _ in range(self.tool["iters"]):
            for i in range(1, n - 1):          # ความยาวแต่ละท่อนต้องคงที่
                a, b = P[i], P[i + 1]
                ex, ey = b[0] - a[0], b[1] - a[1]
                dist = math.hypot(ex, ey) or 1e-6
                f = (dist - seg) / dist
                if i == 1:
                    b[0] -= ex * f
                    b[1] -= ey * f
                else:
                    f *= 0.5
                    a[0] += ex * f
                    a[1] += ey * f
                    b[0] -= ex * f
                    b[1] -= ey * f
            for i in range(n - 2):             # ความแข็งการงอ (กันพับหักมุม)
                mn = 2 * seg * self.stiff[i]
                a, c = P[i], P[i + 2]
                ex, ey = c[0] - a[0], c[1] - a[1]
                dist = math.hypot(ex, ey) or 1e-6
                if dist < mn:
                    f = (mn - dist) / dist
                    if i < 2:
                        c[0] += ex * f
                        c[1] += ey * f
                    else:
                        f *= 0.5
                        a[0] -= ex * f
                        a[1] -= ey * f
                        c[0] += ex * f
                        c[1] += ey * f

    def kick(self, dvel):
        pass

    def tip(self, base, ang, S):
        return QPointF(*self.p[-1])

    def motion(self):
        return max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(self.p, self.q)) * 4

    def bounds(self, base, S):
        xs = [a[0] for a in self.p] + [base.x()]
        ys = [a[1] for a in self.p] + [base.y()]
        m = 40 * S + 12
        return QtCore.QRectF(min(xs) - m, min(ys) - m, max(xs) - min(xs) + 2 * m,
                             max(ys) - min(ys) + 2 * m)

    def draw(self, p, base, ang, S):
        if self.tool["key"] == "whip":
            self._draw_whip(p, base, ang, S)
        else:
            self._draw_belt(p, base, ang, S)

    def _draw_whip(self, p, base, ang, S):
        P, n, hl = self.p, self.n, self.hl
        p.save()                                          # ห่วงคล้องข้อมือ (อยู่หลังด้าม)
        p.translate(base)
        p.rotate(ang)
        p.scale(S, S)
        p.setBrush(Qt.NoBrush)
        for col, w in ((OUTLINE, 5.0), (QColor(128, 72, 34), 2.6)):
            p.setPen(_pen(col, w))
            p.drawEllipse(QRectF(-3, 12, 15, 26))
        p.restore()

        widths = [lerp(8.5, 1.5, (i / (n - 2)) ** 1.4) * S for i in range(n - 1)]
        pieces, prev = [], QPointF(*P[0])
        for i in range(1, n):                             # โค้งเรียบผ่านจุดกึ่งกลาง
            end = QPointF(*P[i]) if i == n - 1 else \
                QPointF((P[i][0] + P[i + 1][0]) / 2, (P[i][1] + P[i + 1][1]) / 2)
            piece = QPainterPath(prev)
            piece.quadTo(QPointF(*P[i]), end)
            pieces.append((piece, widths[i - 1]))
            prev = end
        p.setBrush(Qt.NoBrush)
        for layer in range(3):                            # ขอบ -> หนัง -> แสงสะท้อน (ให้ดูกลม)
            for piece, w in pieces:
                thin = w < 3.2 * S                        # ช่วงปลาย = สายหนังเส้นเล็กสีอ่อน
                if layer == 0:
                    p.setPen(_pen(OUTLINE, w + 3.0 * S))
                elif layer == 1:
                    p.setPen(_pen(QColor(176, 124, 70) if thin else QColor(104, 56, 26), w))
                else:
                    if thin:
                        continue
                    p.setPen(_pen(QColor(198, 130, 68, 220), w * 0.36))
                p.drawPath(piece)
        p.setPen(_pen(QColor(48, 24, 10, 210), max(1.0, 1.15 * S)))   # ลายถักหนัง
        for i in range(1, n - 1):
            w = widths[i - 1]
            if w < 3.2 * S:
                continue
            for cx, cy, sg in ((P[i][0], P[i][1], 1),
                               ((P[i][0] + P[i + 1][0]) / 2, (P[i][1] + P[i + 1][1]) / 2, -1)):
                tx, ty = P[i + 1][0] - P[i - 1][0], P[i + 1][1] - P[i - 1][1]
                d = math.hypot(tx, ty) or 1
                tx, ty = tx / d, ty / d
                nx, ny = -ty * w * 0.42, tx * w * 0.42
                ox, oy = tx * w * 0.3 * sg, ty * w * 0.3 * sg
                p.drawLine(QPointF(cx - nx - ox, cy - ny - oy), QPointF(cx + nx + ox, cy + ny + oy))
        ex, ey = P[-1][0] - P[-2][0], P[-1][1] - P[-2][1]   # ปลายแส้แตกเป็นพู่ (cracker)
        a0 = math.atan2(ey, ex)
        p.setPen(_pen(QColor(246, 236, 212), 1.2 * S))
        for da in (-0.35, 0.0, 0.35):
            p.drawLine(QPointF(*P[-1]), QPointF(P[-1][0] + math.cos(a0 + da) * 13 * S,
                                                P[-1][1] + math.sin(a0 + da) * 13 * S))
        p.save()                                          # ด้าม
        p.translate(base)
        p.rotate(ang)
        p.scale(S, S)
        body = QPainterPath()
        body.addPolygon(QPolygonF([QPointF(-5.5, -hl - 2), QPointF(5.5, -hl - 2),
                                   QPointF(8, 9), QPointF(-8, 9)]))
        body.closeSubpath()
        p.setPen(_pen(OUTLINE, 2))
        p.setBrush(_grad(-8, 8, ((0, (54, 26, 10)), (0.35, (156, 90, 44)), (0.65, (110, 60, 28)),
                                 (1, (42, 20, 8)))))
        p.drawPath(body)
        p.save()
        p.setClipPath(body)
        p.setPen(_pen(QColor(36, 18, 6, 190), 1.2))       # ลายถักไขว้
        for y in range(-hl - 14, 22, 7):
            p.drawLine(QPointF(-9, y), QPointF(9, y + 10))
            p.drawLine(QPointF(-9, y + 10), QPointF(9, y))
        p.restore()
        p.setBrush(_grad(-8, 8, GOLD))                    # ปลอกโลหะ
        p.drawRoundedRect(QRectF(-7, -hl - 6, 14, 7), 2, 2)
        p.drawRoundedRect(QRectF(-8.8, 1, 17.6, 6), 2, 2)
        g = QRadialGradient(QPointF(-3, 11), 12)          # ปุ่มท้ายด้าม
        g.setColorAt(0, QColor(170, 100, 50))
        g.setColorAt(1, QColor(56, 28, 12))
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 14), 9.5, 7.5)
        p.restore()

    def _draw_belt(self, p, base, ang, S):
        P = self.p
        path = QPainterPath()
        path.moveTo(base)
        path.lineTo(QPointF(*P[0]))
        for i in range(1, self.n - 1):
            mid = QPointF((P[i][0] + P[i + 1][0]) / 2, (P[i][1] + P[i + 1][1]) / 2)
            path.quadTo(QPointF(*P[i]), mid)
        path.lineTo(QPointF(*P[-1]))
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(OUTLINE, 21 * S))
        p.drawPath(path)
        p.setPen(_pen(QColor(92, 48, 20), 17 * S))        # ขอบหนังสีเข้ม
        p.drawPath(path)
        stitch = QPen(QColor(236, 202, 150), 12.6 * S)    # ด้ายเย็บ: ขีดประกว้างๆ แล้วทับตรงกลาง
        stitch.setCapStyle(Qt.FlatCap)                    # เหลือให้เห็นแค่สองขอบ = ฝีเข็มสองแถว
        stitch.setDashPattern([0.22, 0.36])
        p.setPen(stitch)
        p.drawPath(path)
        p.setPen(QPen(QColor(136, 76, 36), 9.8 * S, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setPen(QPen(QColor(184, 112, 58, 120), 3.6 * S, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
        p.drawPath(path)
        for i in (-2, -3, -4, -5):                        # รูเข็มขัดพร้อมตาไก่
            c = QPointF(*P[i])
            p.setPen(_pen(QColor(196, 200, 208), 1.3 * S))
            p.setBrush(QColor(34, 18, 8))
            p.drawEllipse(c, 2.6 * S, 2.6 * S)
        p.save()
        p.translate(base)
        p.rotate(ang)
        p.scale(S, S)
        p.setPen(_pen(OUTLINE, 1.8))                      # ห่วงเก็บสาย
        p.setBrush(_grad(-12, 12, ((0, (60, 30, 12)), (0.4, (130, 74, 36)), (1, (54, 26, 10)))))
        p.drawRoundedRect(QRectF(-12, -43, 24, 8), 2, 2)
        frame = QPainterPath()                            # หัวเข็มขัดโลหะ (มีรูตรงกลาง)
        frame.addRoundedRect(QRectF(-17, -27, 34, 31), 6, 6)
        frame.addRoundedRect(QRectF(-11, -21, 22, 19), 2.5, 2.5)
        p.setBrush(_grad(-17, 17, GOLD))
        p.drawPath(frame)
        p.setPen(_pen(OUTLINE, 5.4))                      # เข็มหัวเข็มขัด
        p.drawLine(QPointF(0, -24), QPointF(0, 1))
        p.setPen(_pen(QColor(226, 230, 238), 3.0))
        p.drawLine(QPointF(0, -24), QPointF(0, 1))
        p.restore()


# ================================================================ รายการอาวุธ + ข้อความ
TOOLS = [
    dict(key="whip", sim="rope", color=QColor(255, 90, 60), tip=235, wind=0.17, crack=2600,
         n=17, seg=11.5, handle=52, recoil=0.25, stiff=(0.96, 0.30), grav=2200, damp=0.996, iters=10,
         name=dict(th="แส้", en="Whip"),
         words=dict(th=["เปรี้ยะ!", "เฟี้ยว!", "ควับ!"], en=["CRACK!", "SNAP!", "WHIP!"])),
    dict(key="belt", sim="rope", color=QColor(255, 170, 40), tip=175, wind=0.15, crack=1700,
         n=10, seg=17, handle=20, recoil=0.08, stiff=(0.975, 0.95), grav=2600, damp=0.988, iters=10,
         name=dict(th="เข็มขัด", en="Belt"),
         words=dict(th=["เพี๊ยะ!", "ฟ้าบ!", "ขวับ!"], en=["THWACK!", "WHAP!", "SNAP!"])),
    dict(key="flipflop", sim="rigid", draw=draw_flipflop, tip=120, flexk=1.6, wind=0.10,
         bounce=0.22, color=QColor(70, 180, 255),
         name=dict(th="รองเท้าแตะ", en="Flip-flop"),
         words=dict(th=["ป้าบ!", "แปะ!", "ผัวะ!"], en=["SMACK!", "PAP!", "WHAP!"])),
    dict(key="stick", sim="rigid", draw=draw_stick, tip=165, flexk=0.15, wind=0.11,
         bounce=0.15, color=QColor(255, 200, 60),
         name=dict(th="ไม้เรียว", en="Stick"),
         words=dict(th=["โป๊ก!", "ปั้ก!", "ตุ้บ!"], en=["BONK!", "WHACK!", "THUD!"])),
    dict(key="hand", sim="rigid", draw=draw_hand, tip=125, flexk=0.55, wind=0.10,
         bounce=0.20, color=QColor(255, 80, 110),
         name=dict(th="มือตบ", en="Slap hand"),
         words=dict(th=["เพี๊ยะ!", "ฉาด!", "เปรี้ยะ!"], en=["SLAP!", "SMACK!", "POW!"])),
    dict(key="bear", sim="bear", tip=0, color=QColor(255, 110, 170),
         name=dict(th="ตุ๊กตาหมี (ให้กำลังใจ)", en="Care bears (cheer up)"),
         words=dict(th=["รักนะ", "น่ารักจัง", "จุ๊บ", "เก่งมาก", "สู้ๆ นะ"],
                    en=["Love you", "So cute", "Mwah!", "Good job", "You got this"])),
    dict(key="larb", sim="throw", tip=0, color=QColor(255, 150, 40),
         name=dict(th="ลาบไอฟร้อง", en="Ai-Frong's Larb"),
         words=dict(th=["แผละ!", "เละ!", "โครม!", "แซ่บ!"], en=["SPLAT!", "SPLOSH!", "SQUISH!", "YUM?!"])),
]
LARB = TOOLS[-1]
LARB_DEFAULT_NAME = dict(LARB["name"])
LARB_LIVES = (9.0, 5.0, 2.5, 1.2)      # ลาบติดจออยู่นานกี่วินาทีก่อนหายหมด


def clean_name(name):
    """ชื่อลาบที่ผู้ใช้ตั้ง: เอาเฉพาะตัวอักษรที่พิมพ์ได้ ยาวไม่เกิน 30 ตัว"""
    name = name if isinstance(name, str) else ""
    return "".join(c for c in name if c.isprintable()).strip()[:30]


def set_larb_name(name):
    LARB["name"] = dict(th=name, en=name) if name else dict(LARB_DEFAULT_NAME)
    LARB["custom"] = bool(name)

STR = dict(
    th=dict(title="เลือกอาวุธ", turn_off="⏻  เปิดอยู่ — กดเพื่อปิด", turn_on="⏻  ปิดอยู่ — กดเพื่อเปิด",
            volume="ระดับเสียงเอฟเฟกต์", mute="ปิดเสียง", size="ขนาด", rename="✎  เปลี่ยนชื่อลาบ…", rename_prompt="ตั้งชื่อลาบ (เว้นว่าง = กลับไปใช้ชื่อเดิม)",
            fade="ลาบจางหายเร็วแค่ไหน", fades=("ช้า", "ปกติ", "เร็ว", "เร็วมาก"), lang="ภาษา / Language", autostart="เปิดพร้อม Windows", quit="ออกจากโปรแกรม",
            off_tip="ปิดอยู่", hello="SlapCursor เปิดแล้ว",
            hello2="คลิกซ้ายที่ไหนก็ได้เพื่อฟาด · คลิกไอคอนนี้เพื่อเปลี่ยนอาวุธหรือปิด-เปิด"),
    en=dict(title="Choose your weapon", turn_off="⏻  ON — click to turn off",
            turn_on="⏻  OFF — click to turn on", volume="Effect volume", mute="Mute", size="Size", rename="✎  Rename the larb…", rename_prompt="Name your larb (empty = default name)",
            fade="Larb fade speed", fades=("Slow", "Normal", "Fast", "Very fast"),
            lang="Language / ภาษา", autostart="Start with Windows", quit="Quit program", off_tip="off",
            hello="SlapCursor is running",
            hello2="Left-click anywhere to hit · click this icon to switch weapon or turn off"),
)
SIZES = (50, 75, 100, 125, 150, 200)
VOLUMES = (0, 10, 25, 50, 75, 100)


def make_sim(tool):
    return RopeSim(tool) if tool["sim"] == "rope" else RigidSim(tool)


def make_icon(tool, dim=False):
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if dim:
        p.setOpacity(0.35)
    if tool["sim"] == "bear":
        p.translate(32, 34)
        p.scale(1.05, 1.05)
        draw_bear(p, BEAR_COLORS[0])
    elif tool["sim"] == "throw":
        p.translate(32, 34)
        draw_larb(p, 5, 26)
    else:
        S = 0.27 if tool["key"] == "whip" else 0.36
        base = QPointF(50, 60) if tool["sim"] == "rope" else QPointF(46, 60)
        sim = make_sim(tool)
        sim.reset(base, REST, S, straight=True)
        for _ in range(26 if tool["sim"] == "rope" else 0):
            sim.step(H, base, REST, 0, S)
        sim.draw(p, base, REST, S)
    p.end()
    return QIcon(pm)


# ================================================================ หน้าต่างโปร่งใส
class Overlay(QtWidgets.QWidget):
    def __init__(self, tool_index=0, scale=1.0, lang="th"):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(QtWidgets.QApplication.primaryScreen().virtualGeometry())

        self.enabled = True
        self.sound_on = True
        self.mute = False           # ใช้ตอน selftest
        self.S = scale
        self.lang = lang
        self.t = 0.0
        self.cur = QPointF(300, 300)
        self.particles = []
        self.combo = 0
        self.last_click = -9.0
        self.prev_down = False
        self.prev_hot = False
        self.prev_dirty = QtCore.QRect()
        self.last_t = time.perf_counter()
        self.text_cache = {}
        self.menu = None
        self.on_toggle = None
        self.frame = 0
        self.log = None             # selftest: เก็บเหตุการณ์
        self.block = False          # True ตอนมีกล่องโต้ตอบเปิดอยู่ -> ไม่รับคลิก
        self.splats = []            # ลาบที่ติดจออยู่
        self.shots = []             # ลาบที่กำลังลอยไปหาจอ
        self.larb_life = 5.0
        self.reload_t = -9.0
        self.pix_cache = {}
        self.set_tool(TOOLS[tool_index])

    def set_tool(self, tool):
        self.tool = tool
        self.sim = make_sim(tool) if tool["sim"] in ("rope", "rigid") else None
        self.reset_motion()

    def reset_motion(self):
        self.ang, self.vel = REST, 0.0
        self.phase, self.ph_t = "rest", 0.0
        self.armed = False
        self.quick = False
        self.prev_sp = 0.0
        self.acc = 0.0
        self.cvel = [0.0, 0.0]
        self.cacc = [0.0, 0.0]
        self.idle = 0
        if self.sim:
            self.sim.reset(self.cur, self.ang, self.S)
        self.bears = [dict(x=self.cur.x(), y=self.cur.y(), vx=0.0, vy=0.0, z=0.0, vz=0.0,
                           hop_at=-1.0) for _ in BEAR_COLORS]
        self.held = dict(x=self.cur.x() + 30 * self.S, y=self.cur.y() + 36 * self.S, vx=0.0, vy=0.0)

    # ---------- เหตุการณ์
    def click(self):
        gap = self.t - self.last_click
        self.combo = self.combo + 1 if gap < 0.8 else 1
        self.last_click = self.t
        self.idle = 0
        if self.tool["sim"] == "bear":
            for i, b in enumerate(self.bears):
                b["hop_at"] = self.t + i * 0.07
            self.love(self.cur)
        elif self.tool["sim"] == "throw":
            self.throw()
        else:
            if self.armed:
                # กดรัว: ครั้งก่อนยังฟาดไม่ถึง -> ให้โดนเดี๋ยวนี้เลย ทุกคลิกต้องได้ตี 1 ที
                self.impact(self.sim.tip(self.cur, self.ang, self.S))
            self.quick = gap < 0.35           # กดรัว = เงื้อสั้นลง ฟาดถี่ขึ้น
            self.phase, self.ph_t = "wind", 0.0
            self.armed = True

    def add_text(self, pos, text, color, size):
        S = self.S
        self.particles.append(dict(kind="text", x=pos.x(), y=pos.y(), vx=random.uniform(-25, 25) * S,
                                   vy=-70 * S, age=0, life=0.85, text=text, color=color,
                                   size=max(10, int(size * S)), rot=random.uniform(-16, 16)))

    def add_combo(self, pos):
        if self.combo >= 3:
            self.add_text(QPointF(pos.x(), pos.y() - 62 * self.S), "x%d COMBO!" % self.combo,
                          QColor(255, 255, 255), 24)

    def impact(self, pos, power=1.0):
        S = self.S
        self.armed = False
        if self.log is not None:
            self.log.append("impact t=%.3f" % self.t)
        self.particles.append(dict(kind="burst", x=pos.x(), y=pos.y(), vx=0, vy=0, age=0,
                                   life=0.24, rot=random.uniform(0, 36)))
        for _ in range(7):
            a, v = random.uniform(0, 6.283), random.uniform(160, 380) * S
            self.particles.append(dict(kind="star", x=pos.x(), y=pos.y(), vx=math.cos(a) * v,
                                       vy=math.sin(a) * v - 80 * S, g=900 * S, age=0,
                                       life=random.uniform(0.35, 0.6), size=random.uniform(6, 11) * S))
        self.add_text(QPointF(pos.x(), pos.y() - 30 * S),
                      random.choice(self.tool["words"][self.lang]), self.tool["color"],
                      random.randint(40, 50))
        self.add_combo(pos)
        if self.sound_on and not self.mute:
            play(self.tool["key"])

    def love(self, pos):
        S = self.S
        for _ in range(12):
            a, v = random.uniform(0, 6.283), random.uniform(60, 230) * S
            self.particles.append(dict(
                kind="heart", x=pos.x(), y=pos.y(), vx=math.cos(a) * v, vy=math.sin(a) * v - 60 * S,
                g=-170 * S, drag=1.6, age=0, life=random.uniform(0.7, 1.2),
                size=random.uniform(9, 20) * S,
                color=random.choice([QColor(255, 70, 110), QColor(255, 130, 180),
                                     QColor(255, 60, 60)])))
        self.add_text(QPointF(pos.x(), pos.y() - 46 * S),
                      random.choice(self.tool["words"][self.lang]), self.tool["color"],
                      random.randint(34, 42))
        self.add_combo(QPointF(pos.x(), pos.y() - 20 * S))
        if self.sound_on and not self.mute:
            play("bear")

    # ---------- ลาบ: ปา -> แปะจอ -> ไหลลง -> จางหาย
    def dpr(self):
        return self.devicePixelRatioF() if self.isVisible() else 1.0

    def held_pix(self):
        key = ("held", self.S, self.dpr())
        if key not in self.pix_cache:
            self.pix_cache = {key: larb_pixmap(11, 30 * self.S, False, self.dpr())}
        return self.pix_cache[key]

    def throw(self):
        S = self.S
        tx, ty = self.cur.x(), self.cur.y()
        self.shots.append(dict(
            x0=tx + random.uniform(-170, 170) * S, y0=ty + random.uniform(250, 340) * S,
            tx=tx, ty=ty, x=tx, y=ty, age=0.0, dur=0.2, spin=random.uniform(-520, 520),
            seed=random.randrange(10 ** 9)))
        self.reload_t = self.t

    def shot_pos(self, sh, f):
        """ตำแหน่ง + ขนาดของลาบที่ลอยอยู่ (f = 0..1) เริ่มใหญ่เพราะอยู่ใกล้ตาเรา แล้วเล็กลงตอนถึงจอ"""
        e = f * f                                     # เร่งเข้าหาจอ
        x = lerp(sh["x0"], sh["tx"], e)
        y = lerp(sh["y0"], sh["ty"], e) - math.sin(f * math.pi) * 42 * self.S
        return x, y, lerp(3.0, 1.15, e)

    def splat(self, sh):
        S = self.S
        R = 56.0 * S
        pm, half = larb_pixmap(sh["seed"], R, True, self.dpr())
        life = self.larb_life
        vt = 150.0 * S / life                         # ความเร็วไหลปลายทาง (ยิ่งหายเร็วยิ่งไหลเร็ว)
        rng = random.Random(sh["seed"])
        drips = [dict(dx=rng.uniform(-0.75, 0.75) * R, v=vt * rng.uniform(1.6, 3.4),
                      w=rng.uniform(3.0, 6.5) * S, t0=rng.uniform(0.02, 0.14) * life, len=0.0,
                      max=rng.uniform(60, 180) * S) for _ in range(6)]
        self.splats.append(dict(x=sh["tx"], y0=sh["ty"], off=0.0, vy=0.0, age=0.0, life=life,
                                vt=vt, ph=rng.uniform(0, 6.283), R=R, pix=pm, half=half,
                                drips=drips))
        if len(self.splats) > 40:
            self.splats.pop(0)
        if self.log is not None:
            self.log.append("impact t=%.3f" % self.t)
        for _ in range(16):                           # เศษลาบ + หยดน้ำมันกระเด็น
            a, v = random.uniform(0, 6.283), random.uniform(150, 540) * S
            oil = random.random() < 0.35
            col = QColor(240, 160, 46, 210) if oil else QColor(*random.choice(LARB_BITS))
            self.particles.append(dict(
                kind="bit", x=sh["tx"], y=sh["ty"], vx=math.cos(a) * v, vy=math.sin(a) * v - 90 * S,
                g=1500 * S, age=0, life=random.uniform(0.4, 0.85), color=col,
                size=random.uniform(2.5, 6.5) * S, spin=random.uniform(-700, 700), oil=oil))
        words = list(self.tool["words"][self.lang])
        if self.tool.get("custom"):
            words.append(self.tool["name"][self.lang] + "!")
        pos = QPointF(sh["tx"], sh["ty"])
        self.add_text(QPointF(pos.x(), pos.y() - 74 * S), random.choice(words), self.tool["color"],
                      random.randint(40, 50))
        self.add_combo(QPointF(pos.x(), pos.y() - 44 * S))
        if self.sound_on and not self.mute:
            play("larb")

    def step_held(self, dt):
        """ก้อนลาบในมือ ตามเมาส์แบบสปริง"""
        S, b = self.S, self.held
        tx, ty = self.cur.x() + 30 * S, self.cur.y() + 36 * S
        n = max(1, int(dt / H))
        h = dt / n
        for _ in range(n):
            b["vx"] += (190 * (tx - b["x"]) - 17 * b["vx"]) * h
            b["vy"] += (190 * (ty - b["y"]) - 17 * b["vy"]) * h
            b["x"] += b["vx"] * h
            b["y"] += b["vy"] * h
        return abs(b["vx"]) + abs(b["vy"])

    def step_larb(self, dt):
        for sh in list(self.shots):
            sh["age"] += dt
            f = min(1.0, sh["age"] / sh["dur"])
            sh["x"], sh["y"], _ = self.shot_pos(sh, f)
            if f >= 1.0:
                self.shots.remove(sh)
                self.splat(sh)
        for sp in self.splats:
            sp["age"] += dt
            # ของมันๆ บนกระจก: ติดอยู่แป๊บนึง แล้วไหลแบบ หนืด-ลื่น-หนืด (stick-slip)
            if sp["age"] > 0.035 * sp["life"]:
                target = sp["vt"] * (0.3 + 0.9 * abs(math.sin(sp["age"] * 9.0 / sp["life"] + sp["ph"])))
                sp["vy"] += (target - sp["vy"]) * min(1.0, dt * 5)
                sp["off"] += sp["vy"] * dt
            for d in sp["drips"]:                     # น้ำมันหยดไหลนำหน้าไปก่อน
                if sp["age"] > d["t0"]:
                    d["len"] = min(d["max"], d["len"] + d["v"] * dt)
        self.splats = [sp for sp in self.splats if sp["age"] < sp["life"]]
        return bool(self.shots or self.splats)

    def paint_splats(self, p):
        for sp in self.splats:
            k = sp["age"] / sp["life"]
            R, x, y0, off = sp["R"], sp["x"], sp["y0"], sp["off"]
            p.save()
            p.setOpacity(1.0 if k < 0.6 else max(0.0, (1 - k) / 0.4))
            p.setPen(Qt.NoPen)
            if off > 1:                               # คราบมันที่ทิ้งไว้ตามทางที่ไหลผ่าน
                g = QLinearGradient(0, y0 - R * 0.3, 0, y0 + off)
                g.setColorAt(0, QColor(236, 160, 50, 0))
                g.setColorAt(1, QColor(236, 160, 50, 70))
                p.setBrush(g)
                p.drawRoundedRect(QRectF(x - R * 0.66, y0 - R * 0.3, R * 1.32, off + R * 0.5),
                                  R * 0.4, R * 0.4)
            for d in sp["drips"]:
                if d["len"] <= 0:
                    continue
                xa, ya = x + d["dx"], y0 + R * 0.45
                yb = ya + off + d["len"]
                p.setPen(_pen(QColor(238, 156, 44, 150), d["w"]))
                p.drawLine(QPointF(xa, ya), QPointF(xa, yb))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(244, 172, 60, 225))
                p.drawEllipse(QPointF(xa, yb), d["w"] * 0.95, d["w"] * 1.25)
                p.setBrush(QColor(255, 250, 225, 200))
                p.drawEllipse(QPointF(xa - d["w"] * 0.3, yb - d["w"] * 0.3), d["w"] * 0.25, d["w"] * 0.35)
            sq = 1 + 0.30 * math.exp(-sp["age"] * 16) * math.cos(sp["age"] * 38)   # สั่นตอนกระแทก
            p.translate(x, y0 + off)
            p.scale(sq, 1 / sq)
            p.drawPixmap(QPointF(-sp["half"], -sp["half"]), sp["pix"])
            p.restore()

    def paint_larb(self, p):
        pm, half = self.held_pix()
        if self.tool["sim"] == "throw":
            since = self.t - self.reload_t
            grow = 1.0 if since > 0.42 else max(0.0, (since - 0.2) / 0.22)   # หยิบก้อนใหม่
            if grow > 0:
                b = self.held
                sp = math.hypot(b["vx"], b["vy"])
                st = 1 + min(0.25, sp / (2600 * self.S))
                p.save()
                p.translate(b["x"], b["y"])
                p.rotate(math.degrees(math.atan2(b["vy"], b["vx"])) if sp > 30 else 0)
                p.scale(st * grow, grow / st)                                # ยืดตามความเร็ว
                p.rotate(-math.degrees(math.atan2(b["vy"], b["vx"])) if sp > 30 else 0)
                p.drawPixmap(QPointF(-half, -half), pm)
                p.restore()
        for sh in self.shots:
            f = min(1.0, sh["age"] / sh["dur"])
            for back, alpha in ((0.16, 0.18), (0.08, 0.35), (0.0, 1.0)):     # motion blur
                ff = max(0.0, f - back)
                x, y, sc = self.shot_pos(sh, ff)
                p.save()
                p.setOpacity(alpha)
                p.translate(x, y)
                p.rotate(sh["spin"] * sh["age"])
                p.scale(sc, sc)
                p.drawPixmap(QPointF(-half, -half), pm)
                p.restore()

    # ---------- physics ของมือ (มุมด้ามจับ)
    def drive(self, h, base):
        tool, ph = self.tool, self.phase
        if ph == "wind":                       # เงื้อ
            tgt, k, c = (0.0 if self.quick else WIND), 1100.0, 50.0
            self.ph_t += h
            if self.ph_t >= tool["wind"] * (0.5 if self.quick else 1.0):
                self.phase = "strike"
        elif ph == "strike":                   # ฟาดลง
            tgt, k, c = HIT - 30, (2800.0 if tool["sim"] == "rope" else 1600.0), 20.0
        elif ph == "follow":                   # (เชือก) ค้างมือรอปลายแส้ตามมา
            tgt, k, c = HIT + 8, 420.0, 34.0
            self.ph_t += h
            if self.ph_t > 0.34:
                self.phase = "rest"
        else:                                  # กลับท่าพัก - สปริงหน่วงน้อย จึงสั่นนิดๆ
            tgt, k, c = REST, 260.0, 18.0
        a = math.radians(self.ang)
        nx, ny = math.cos(a), math.sin(a)
        L = max(60.0, tool["tip"] * 0.6) * self.S
        inert = -(self.cacc[0] * nx + self.cacc[1] * ny) * 57.3 * 1.5 / L
        inert = max(-26000.0, min(26000.0, inert))
        alpha = k * (tgt - self.ang) - c * self.vel + inert
        self.vel += alpha * h
        self.ang = max(-200.0, min(140.0, self.ang + self.vel * h))
        if self.phase == "strike" and self.ang <= HIT:
            if tool["sim"] == "rope":
                self.phase, self.ph_t = "follow", 0.0
            else:                              # ของแข็ง: กระทบแล้วเด้งกลับ
                new_vel = -self.vel * tool["bounce"]
                self.sim.kick(new_vel - self.vel)
                self.vel, self.ang = new_vel, HIT
                self.phase = "rest"
                self.impact(self.sim.tip(base, HIT, self.S))
        return alpha

    def step_particles(self, dt):
        for q in self.particles:
            q["age"] += dt
            if "drag" in q:
                f = math.exp(-q["drag"] * dt)
                q["vx"] *= f
                q["vy"] *= f
            q["vy"] += q.get("g", 0) * dt
            q["x"] += q["vx"] * dt
            q["y"] += q["vy"] * dt
        self.particles = [q for q in self.particles if q["age"] < q["life"]]

    def step_bears(self, dt):
        S = self.S
        lead_x, lead_y = self.cur.x(), self.cur.y()
        moving = 0.0
        for i, b in enumerate(self.bears):
            tx = lead_x + (38 if i == 0 else 40) * S
            ty = lead_y + (40 if i == 0 else 4) * S
            n = max(1, int(dt / H))
            h = dt / n
            for _ in range(n):                 # สปริงดึงหมีตามเมาส์ (เด้งดึ๋ง)
                ax = 150 * (tx - b["x"]) - 13 * b["vx"]
                ay = 150 * (ty - b["y"]) - 13 * b["vy"]
                b["vx"] += ax * h
                b["vy"] += ay * h
                b["x"] += b["vx"] * h
                b["y"] += b["vy"] * h
                if 0 <= b["hop_at"] <= self.t:  # กระโดด
                    b["vz"], b["hop_at"] = -430.0 * S, -1.0
                b["vz"] += 2400 * S * h        # แรงโน้มถ่วง
                b["z"] += b["vz"] * h
                if b["z"] > 0:                 # ตกถึงพื้น -> เด้ง
                    b["z"] = 0.0
                    b["vz"] = -b["vz"] * 0.45 if b["vz"] > 60 * S else 0.0
            moving += abs(b["vx"]) + abs(b["vy"]) + abs(b["vz"]) + abs(b["z"])
            lead_x, lead_y = b["x"], b["y"]
        return moving

    # ---------- เดินเวลา 1 เฟรม
    def advance(self, dt, cur, clicked):
        """คืน True ถ้ามีอะไรขยับ (ต้องวาดใหม่)"""
        self.t += dt
        prev = self.cur
        moved = cur != prev
        vx, vy = (cur.x() - prev.x()) / dt, (cur.y() - prev.y()) / dt
        ax, ay = (vx - self.cvel[0]) / dt, (vy - self.cvel[1]) / dt
        m = math.hypot(ax, ay)
        if m > 50000:
            ax, ay = ax * 50000 / m, ay * 50000 / m
        self.cacc = [lerp(self.cacc[0], ax, 0.5), lerp(self.cacc[1], ay, 0.5)]
        self.cvel = [vx, vy]
        self.cur = cur
        if clicked:
            self.click()

        busy = moved or bool(self.particles) or clicked
        if self.step_larb(dt):
            busy = True
        if self.tool["sim"] == "throw":
            if self.step_held(dt) > 2.0 or self.t - self.reload_t < 0.5:
                busy = True
        elif self.tool["sim"] == "bear":
            if self.step_bears(dt) > 2.0 or any(b["hop_at"] >= 0 for b in self.bears):
                busy = True
        elif busy or self.idle < 20 or self.phase != "rest":
            self.acc += dt
            steps = min(16, int(self.acc / H))
            self.acc -= steps * H
            for i in range(steps):
                f = (i + 1) / steps
                base = QPointF(lerp(prev.x(), cur.x(), f), lerp(prev.y(), cur.y(), f))
                alpha = self.drive(H, base)
                self.sim.step(H, base, self.ang, alpha, self.S)
                if self.armed and self.tool["sim"] == "rope" and self.phase in ("follow", "rest"):
                    # แส้แตก (crack) ตอนเชือกเหยียดตึงไปทางที่ฟาด
                    sim = self.sim
                    P, Q, A = sim.p[-1], sim.q[-1], sim.p[0]
                    sp = math.hypot(P[0] - Q[0], P[1] - Q[1]) / H / self.S
                    ex, ey = P[0] - A[0], P[1] - A[1]
                    dist = math.hypot(ex, ey) or 1e-6
                    full = sim.seg * self.S * (sim.n - 1)
                    a = math.radians(self.ang)
                    facing = (ex * math.sin(a) - ey * math.cos(a)) / dist
                    if (dist > 0.9 * full and facing > 0.45 and sp > 900) or self.phase == "rest":
                        if self.log is not None:
                            self.log.append("tip speed %.0f px/s" % sp)
                        self.impact(QPointF(*P))
                        for a_, b_ in zip(sim.p, sim.q):   # โดนเป้าแล้ว: หยุด + เด้งกลับนิดหน่อย
                            b_[0] = a_[0] + (a_[0] - b_[0]) * self.tool["recoil"]
                            b_[1] = a_[1] + (a_[1] - b_[1]) * self.tool["recoil"]
                    self.prev_sp = sp
                else:
                    self.prev_sp = 0.0
            still = (self.sim.motion() < 0.06 and abs(self.vel) < 2 and abs(self.ang - REST) < 0.3
                     and self.phase == "rest")
            self.idle = self.idle + 1 if still and not moved else 0
            if self.idle < 20:
                busy = True
        self.step_particles(dt)
        return busy

    def tick(self):
        now = time.perf_counter()
        dt = max(0.004, min(0.05, now - self.last_t))
        self.last_t = now
        self.frame += 1

        hot = all(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x11, 0x10, 0x7B))
        if hot and not self.prev_hot and self.on_toggle:
            self.on_toggle()
        self.prev_hot = hot
        down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
        clicked = down and not self.prev_down
        self.prev_down = down
        if not self.enabled:
            return
        menu_open = self.menu is not None and self.menu.isVisible()
        if self.frame % 120 == 0 and not menu_open:
            self.raise_()
        cur = QPointF(QtGui.QCursor.pos() - self.geometry().topLeft())
        busy = self.advance(dt, cur, clicked and not menu_open and not self.block)
        if not busy and self.prev_dirty.isNull():
            return
        dirty = self.dirty_rect() if busy else QtCore.QRect()
        self.update(dirty.united(self.prev_dirty))
        self.prev_dirty = dirty

    def dirty_rect(self):
        S = self.S

        def box(x, y, r):
            return QtCore.QRectF(x - r, y - r, 2 * r, 2 * r)
        if self.sim:
            r = self.sim.bounds(self.cur, S)
        else:
            r = box(self.cur.x(), self.cur.y(), 40)
            for b in self.bears:
                r = r.united(box(b["x"], b["y"], 80 * S + 20))
        for q in self.particles:
            r = r.united(box(q["x"], q["y"], 170 * S + 30))
        if self.tool["sim"] == "throw":
            r = r.united(box(self.held["x"], self.held["y"], 80 * S + 20))
        for sh in self.shots:
            r = r.united(box(sh["x"], sh["y"], 150 * S + 30))
            r = r.united(box(sh["x0"], sh["y0"], 150 * S + 30))
        for sp in self.splats:
            hf = sp["half"] + 12
            r = r.united(QtCore.QRectF(sp["x"] - hf, sp["y0"] - hf, 2 * hf,
                                       2 * hf + sp["off"] + 200 * S))
        return r.toAlignedRect()

    # ---------- วาด
    def text_path(self, text, size):
        key = (text, size)
        if key not in self.text_cache:
            f = QFont("Leelawadee UI")
            f.setPixelSize(size)
            f.setWeight(QFont.Black)
            path = QPainterPath()
            path.addText(0, 0, f, text)
            c = path.boundingRect().center()
            path.translate(-c.x(), -c.y())
            self.text_cache[key] = path
        return self.text_cache[key]

    def paint_scene(self, p):
        S = self.S
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self.paint_splats(p)
        if self.sim:
            self.sim.draw(p, self.cur, self.ang, S)
        elif self.tool["sim"] == "bear":
            for i in reversed(range(len(self.bears))):
                b = self.bears[i]
                p.save()
                p.translate(b["x"], b["y"] + b["z"])
                p.rotate(max(-25, min(25, b["vx"] * 0.06)))   # เอียงตามความเร็ว
                squash = 1 + max(-0.18, min(0.18, -b["vz"] / (2600 * S)))
                p.scale(S / squash, S * squash)
                draw_bear(p, BEAR_COLORS[i])
                p.restore()

        self.paint_larb(p)
        for q in self.particles:
            k = q["age"] / q["life"]
            p.save()
            p.translate(q["x"], q["y"])
            if q["kind"] == "burst":
                p.rotate(q["rot"])
                r1 = (16 + 62 * k) * S
                r2 = r1 + 30 * (1 - k) * S
                for i in range(10):
                    a = i * math.pi / 5
                    c, s = math.cos(a), math.sin(a)
                    p.setPen(_pen(QColor(255, 255, 255), (7 * (1 - k) + 1) * S))
                    p.drawLine(QPointF(c * r1, s * r1), QPointF(c * r2, s * r2))
                    p.setPen(_pen(QColor(255, 214, 50), (4 * (1 - k) + 1) * S))
                    p.drawLine(QPointF(c * r1, s * r1), QPointF(c * r2, s * r2))
            elif q["kind"] == "star":
                p.setOpacity(1 - k * k)
                p.rotate(q["age"] * 500)
                s = q["size"]
                pts = [QPointF(math.sin(i * math.pi / 5) * (s if i % 2 == 0 else s * 0.45),
                               -math.cos(i * math.pi / 5) * (s if i % 2 == 0 else s * 0.45))
                       for i in range(10)]
                p.setPen(_pen(QColor(190, 110, 0), 1.5))
                p.setBrush(QColor(255, 226, 70))
                p.drawPolygon(QPolygonF(pts))
            elif q["kind"] == "heart":
                p.setOpacity(1 - k ** 3)
                s = q["size"] / 14 * (0.5 + 0.5 * min(1, q["age"] / 0.12))
                p.rotate(math.sin(q["age"] * 7 + q["size"]) * 18)
                p.scale(s, s)
                p.setPen(_pen(QColor(255, 255, 255), 2.2))
                p.setBrush(q["color"])
                p.drawPath(HEART)
            elif q["kind"] == "bit":
                p.setOpacity(1 - k ** 3)
                p.rotate(q["age"] * q["spin"])
                s = q["size"]
                p.setPen(Qt.NoPen if q["oil"] else _pen(q["color"].darker(160), 1))
                p.setBrush(q["color"])
                if q["oil"]:
                    p.drawEllipse(QPointF(0, 0), s * 0.7, s)
                else:
                    p.drawRoundedRect(QRectF(-s, -s * 0.7, 2 * s, 1.4 * s), s * 0.6, s * 0.6)
            else:  # text
                age, size = q["age"], q["size"]
                if age < 0.1:
                    s = 0.4 + 0.95 * age / 0.1
                elif age < 0.2:
                    s = 1.35 - 0.35 * (age - 0.1) / 0.1
                else:
                    s = 1.0
                p.setOpacity(1.0 if k < 0.6 else max(0.0, 1 - (k - 0.6) / 0.4))
                p.rotate(q["rot"])
                p.scale(s, s)
                path = self.text_path(q["text"], size)
                p.setBrush(Qt.NoBrush)
                p.setPen(_pen(QColor(35, 14, 20), size * 0.30))
                p.drawPath(path)
                p.setPen(_pen(QColor(255, 255, 255), size * 0.13))
                p.drawPath(path)
                p.setPen(Qt.NoPen)
                p.setBrush(q["color"])
                p.drawPath(path)
            p.restore()

    def paintEvent(self, ev):
        if not self.enabled:
            return
        p = QPainter(self)
        self.paint_scene(p)


# ================================================================ selftest (ไม่เปิดหน้าต่าง ไม่มีเสียง)
def selftest(out_dir):
    """จำลองการฟาดจริงด้วย physics แล้ววาดทีละเฟรมลงรูป ไว้ตรวจความสมจริง"""
    DT, CW, CH, NF, SKIP = 1 / 60, 250, 300, 12, 2
    S = 0.62
    tools = [t for t in TOOLS if t["sim"] != "bear"]
    img = QtGui.QImage(CW * NF, CH * len(tools), QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(24, 26, 32))
    p = QPainter(img)
    random.seed(3)
    for row, tool in enumerate(tools):
        ov = Overlay(TOOLS.index(tool), S, "en" if row % 2 else "th")
        ov.mute, ov.log = True, []
        cur = QPointF(170, 120)
        ov.cur = cur
        ov.reset_motion()
        for _ in range(90):                     # ปล่อยให้นิ่งก่อน
            ov.advance(DT, cur, False)
        t0 = ov.t
        for f in range(NF * SKIP):
            ov.advance(DT, cur, f == 0)
            if f % SKIP == SKIP - 1:
                c = f // SKIP
                p.save()
                p.setClipRect(c * CW, row * CH, CW, CH)
                p.translate(c * CW, row * CH)
                ov.paint_scene(p)
                p.setPen(QColor(120, 120, 130))
                p.drawText(8, 16, "%s  %.0f ms" % (tool["key"], (ov.t - t0) * 1000))
                p.restore()
        print(tool["key"], [s if "speed" in s else "impact +%.0f ms" % ((float(s.split("=")[1]) - t0) * 1000)
                            for s in ov.log])
    p.end()
    img.save(os.path.join(out_dir, "selftest_strip.png"))

    # รูปที่ 2: ท่าพัก + ลากเมาส์เร็วๆ (แรงเฉื่อย) + หมี + ไอคอน
    img = QtGui.QImage(1500, 420, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(24, 26, 32))
    p = QPainter(img)
    for i, tool in enumerate(TOOLS):
        ov = Overlay(i, 0.7, "en")
        ov.mute = True
        cur = QPointF(90 + i * 250, 150)
        ov.cur = cur
        ov.reset_motion()
        for _ in range(120):
            ov.advance(DT, cur, False)
        ov.paint_scene(p)                       # ท่าพัก
        for f in range(9):                      # ลากไปทางขวาเร็วๆ
            cur = QPointF(cur.x() + 9, cur.y() + 22)
            ov.advance(DT, cur, f == 3 and tool["sim"] == "bear")
        ov.paint_scene(p)
        p.drawPixmap(60 + i * 250, 10, make_icon(tool).pixmap(48, 48))
    p.end()
    img.save(os.path.join(out_dir, "selftest_rest.png"))

    # รูปที่ 3: โมเดลขยายใหญ่ ไว้ดูรายละเอียด
    img = QtGui.QImage(1720, 640, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(24, 26, 32))
    p = QPainter(img)
    for i, tool in enumerate(t for t in TOOLS if t["sim"] != "bear"):
        ov = Overlay(TOOLS.index(tool), 2.3, "en")
        ov.mute = True
        cur = QPointF(200 + i * 275, 560 if tool["sim"] == "rigid" else 330)
        ov.cur = cur
        ov.reset_motion()
        for _ in range(150):
            ov.advance(DT, cur, False)
        ov.ang = -12 if tool["sim"] == "rigid" else ov.ang
        ov.paint_scene(p)
    p.end()
    img.save(os.path.join(out_dir, "selftest_models.png"))

    # รูปที่ 4: ลาบ - ปา แปะ ไหล จาง (เวลาเป็นวินาทีหลังคลิก)
    times = (0.07, 0.14, 0.23, 0.6, 1.5, 3.0, 4.0, 4.7)
    CW2, CH2 = 330, 520
    img = QtGui.QImage(CW2 * len(times), CH2, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(24, 26, 32))
    p = QPainter(img)
    ov = Overlay(TOOLS.index(LARB), 1.3, "th")
    ov.mute = True
    cur = QPointF(160, 150)
    ov.cur = cur
    ov.reset_motion()
    for _ in range(30):
        ov.advance(DT, cur, False)
    t0, first = ov.t, True
    for c, tt in enumerate(times):
        while ov.t - t0 < tt:
            ov.advance(DT, cur, first)
            first = False
        p.save()
        p.setClipRect(c * CW2, 0, CW2, CH2)
        p.translate(c * CW2, 0)
        ov.paint_scene(p)
        p.setPen(QColor(150, 150, 160))
        p.drawText(8, 16, "larb  %.2f s" % tt)
        p.restore()
    p.end()
    img.save(os.path.join(out_dir, "selftest_larb.png"))
    print("selftest ok")


# ================================================================ tray + main
# ================================================================ เปิดพร้อม Windows
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "SlapCursor"


def autostart_command():
    """คำสั่งที่ Windows จะรันตอนล็อกอิน: pythonw (ไม่มีหน้าต่างดำ) + ไฟล์นี้ ใส่ quote กัน path มีช่องว่าง"""
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return '"%s" "%s"' % (exe, os.path.abspath(__file__))


def autostart_get():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_NAME)[0]
    except OSError:
        return None


def autostart_set(on):
    """เขียน/ลบค่าเฉพาะของแอปนี้ใน HKCU Run (ระดับผู้ใช้ ไม่ต้องใช้สิทธิ์ admin)"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def main():
    global HEART
    QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    HEART = heart_path()

    if len(sys.argv) > 2 and sys.argv[1] == "--autostart":
        ok = autostart_set(sys.argv[2] == "on")
        print("autostart", sys.argv[2], "ok" if ok else "failed", "->", autostart_get())
        return 0 if ok else 1

    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
        return 0

    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "SlapCursor_single_instance")
    if ctypes.windll.kernel32.GetLastError() == 183:   # เปิดอยู่แล้ว
        return 0

    settings = QtCore.QSettings("SlapCursor", "SlapCursor")
    if autostart_get() not in (None, autostart_command()):
        autostart_set(True)

    def read_int(key, default, allowed):
        """อ่านค่าตั้งค่าแบบปลอดภัย: ค่าเพี้ยน/ถูกแก้ใน registry -> ใช้ค่าเริ่มต้น ไม่ crash"""
        try:
            v = int(settings.value(key, default))
        except (TypeError, ValueError):
            return default
        return v if v in allowed else default

    vol = read_int("volume", 100, VOLUMES)
    ensure_sounds(vol or 100)
    idx = read_int("tool", 0, range(len(TOOLS)))
    size = read_int("size", 100, SIZES)
    lang = settings.value("lang", "th")
    lang = lang if lang in STR else "th"
    ov = Overlay(idx, size / 100.0, lang)
    ov.sound_on = vol > 0
    fade = read_int("larb_fade", 1, range(len(LARB_LIVES)))
    ov.larb_life = LARB_LIVES[fade]
    set_larb_name(clean_name(settings.value("larb_name", "")))

    tray = QtWidgets.QSystemTrayIcon()
    menu = QtWidgets.QMenu()
    state = dict(tool=idx, size=size, vol=vol, fade=fade)

    def refresh_tray():
        tray.setIcon(make_icon(ov.tool, dim=not ov.enabled))
        tip = "SlapCursor - " + ov.tool["name"][ov.lang]
        if not ov.enabled:
            tip += " (%s)" % STR[ov.lang]["off_tip"]
        tray.setToolTip(tip)

    def later(fn):
        # สร้างเมนูใหม่หลังเมนูปิดแล้ว (ห้ามลบ action ระหว่างที่มันกำลังทำงาน)
        QtCore.QTimer.singleShot(0, fn)

    def set_enabled(on):
        ov.enabled = on
        ov.particles = []
        ov.splats = []
        ov.shots = []
        ov.prev_dirty = QtCore.QRect()
        if on:
            ov.cur = QPointF(QtGui.QCursor.pos() - ov.geometry().topLeft())
            ov.reset_motion()
            ov.show()
        else:
            ov.hide()
        later(build_menu)

    def choose(i):
        state["tool"] = i
        ov.set_tool(TOOLS[i])
        settings.setValue("tool", i)
        ov.update()
        later(build_menu)

    def set_size(pct):
        state["size"] = pct
        ov.S = pct / 100.0
        ov.reset_motion()
        settings.setValue("size", pct)
        ov.update()
        later(build_menu)

    def set_lang(code):
        ov.lang = code
        settings.setValue("lang", code)
        later(build_menu)

    def set_volume(v):
        state["vol"] = v
        ov.sound_on = v > 0
        settings.setValue("volume", v)
        if v:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)   # หยุดเสียงก่อนเขียนไฟล์ทับ
                ensure_sounds(v)
                play(ov.tool["key"])                           # เล่นให้ฟังว่าดังแค่ไหน
            except (OSError, RuntimeError):
                pass
        later(build_menu)

    def toggle_autostart(on):
        autostart_set(on)
        later(build_menu)

    def set_fade(i):
        state["fade"] = i
        ov.larb_life = LARB_LIVES[i]
        settings.setValue("larb_fade", i)
        later(build_menu)

    def rename_larb():
        T = STR[ov.lang]
        dlg = QtWidgets.QInputDialog()
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.setWindowTitle("SlapCursor")
        dlg.setLabelText(T["rename_prompt"])
        dlg.setTextValue(LARB["name"][ov.lang])
        ov.block = True                 # ระหว่างพิมพ์ชื่อ ไม่ต้องปาลาบใส่กล่องนี้
        ok = dlg.exec_()
        ov.block = False
        if ok:
            name = clean_name(dlg.textValue())
            settings.setValue("larb_name", name)
            set_larb_name(name)
            later(build_menu)

    def build_menu():
        T = STR[ov.lang]
        menu.clear()
        power = menu.addAction(T["turn_off"] if ov.enabled else T["turn_on"])
        f = power.font()
        f.setBold(True)
        power.setFont(f)
        power.triggered.connect(lambda: set_enabled(not ov.enabled))
        menu.addSeparator()
        menu.addAction(T["title"]).setEnabled(False)
        for i, tool in enumerate(TOOLS):
            act = menu.addAction(make_icon(tool), tool["name"][ov.lang])
            act.setCheckable(True)
            act.setChecked(i == state["tool"])
            act.triggered.connect(lambda _=False, i=i: choose(i))
        menu.addSeparator()
        menu.addAction(T["rename"]).triggered.connect(lambda: later(rename_larb))
        sub = menu.addMenu(T["fade"])
        for i, label in enumerate(T["fades"]):
            a = sub.addAction("%s  (%g s)" % (label, LARB_LIVES[i]))
            a.setCheckable(True)
            a.setChecked(i == state["fade"])
            a.triggered.connect(lambda _=False, i=i: set_fade(i))
        menu.addSeparator()
        sub = menu.addMenu(T["size"])
        for pct in SIZES:
            a = sub.addAction("%d%%" % pct)
            a.setCheckable(True)
            a.setChecked(pct == state["size"])
            a.triggered.connect(lambda _=False, pct=pct: set_size(pct))
        sub = menu.addMenu(T["lang"])
        for code, label in (("th", "ไทย"), ("en", "English")):
            a = sub.addAction(label)
            a.setCheckable(True)
            a.setChecked(code == ov.lang)
            a.triggered.connect(lambda _=False, code=code: set_lang(code))
        sub = menu.addMenu(T["volume"])
        for v in VOLUMES:
            a = sub.addAction(T["mute"] if v == 0 else "%d%%" % v)
            a.setCheckable(True)
            a.setChecked(v == state["vol"])
            a.triggered.connect(lambda _=False, v=v: set_volume(v))
        menu.addSeparator()
        auto = menu.addAction(T["autostart"])
        auto.setCheckable(True)
        auto.setChecked(autostart_get() is not None)
        auto.toggled.connect(toggle_autostart)
        menu.addSeparator()
        menu.addAction(T["quit"]).triggered.connect(app.quit)
        refresh_tray()

    build_menu()
    ov.on_toggle = lambda: set_enabled(not ov.enabled)
    ov.menu = menu
    tray.setContextMenu(menu)
    tray.activated.connect(lambda why: menu.popup(QtGui.QCursor.pos())
                           if why == QtWidgets.QSystemTrayIcon.Trigger else None)
    tray.show()
    ov.show()
    tray.showMessage(STR[ov.lang]["hello"], STR[ov.lang]["hello2"], make_icon(ov.tool), 4000)

    timer = QtCore.QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.timeout.connect(ov.tick)
    timer.start(16)
    code = app.exec_()
    tray.hide()
    return code


if __name__ == "__main__":
    sys.exit(main())
