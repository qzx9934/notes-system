# -*- coding: utf-8 -*-
"""生成 PWA 图标（纯标准库，无需 Pillow）。

绘制一个"笔记本"风格图标：深蓝底（品牌主色）+ 白色卡片 + 顶部色带 + 几行文字线。
底色满铺，天然适配 maskable（安全区不会被裁切）。

用法：
    python tools/make_icons.py
会在 frontend/icons/ 下生成 icon-192.png / icon-512.png / apple-touch-icon.png
"""
import os
import zlib
import struct

# 品牌色（取自前端 :root）
PRIMARY = (31, 78, 121)        # #1F4E79
PRIMARY_LIGHT = (46, 117, 182) # #2E75B6
WHITE = (255, 255, 255)
LINE = (190, 198, 208)         # 文字线浅灰
ACCENT = (243, 156, 18)        # ★ 橙（等级色）

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, '..', 'frontend', 'icons')


def write_png(path, width, height, pixels):
    """pixels: bytearray, 长度 = width*height*4 (RGBA)。"""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # 每行 filter type 0
        raw.extend(pixels[y * stride:(y + 1) * stride])
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(typ, data):
        return (struct.pack('>I', len(data)) + typ + data
                + struct.pack('>I', zlib.crc32(typ + data) & 0xffffffff))

    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)))
        f.write(chunk(b'IDAT', compressed))
        f.write(chunk(b'IEND', b''))


def make_icon(size):
    buf = bytearray(size * size * 4)

    def put(x, y, color):
        if 0 <= x < size and 0 <= y < size:
            i = (y * size + x) * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = color[0], color[1], color[2], 255

    def fill_rect(x0, y0, x1, y1, color):
        for y in range(max(0, y0), min(size, y1)):
            for x in range(max(0, x0), min(size, x1)):
                put(x, y, color)

    def fill_round_rect(x0, y0, x1, y1, r, color):
        for y in range(max(0, y0), min(size, y1)):
            for x in range(max(0, x0), min(size, x1)):
                # 四角圆角判断
                cx = x0 + r if x < x0 + r else (x1 - 1 - r if x > x1 - 1 - r else x)
                cy = y0 + r if y < y0 + r else (y1 - 1 - r if y > y1 - 1 - r else y)
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    put(x, y, color)

    # 1) 满铺主色背景
    fill_rect(0, 0, size, size, PRIMARY)

    # 2) 白色卡片（控制在中央安全区内）
    m = int(size * 0.20)
    fill_round_rect(m, int(size * 0.16), size - m, size - int(size * 0.16),
                    int(size * 0.06), WHITE)

    # 3) 顶部色带
    fill_rect(m, int(size * 0.16), size - m, int(size * 0.30), PRIMARY_LIGHT)
    # 顶部色带圆角修饰（盖住下方直角即可，简单处理略）

    # 4) 文字线（4 行，宽度递减）
    left = m + int(size * 0.07)
    right_full = size - m - int(size * 0.07)
    widths = [1.0, 0.85, 0.95, 0.6]
    y = int(size * 0.40)
    gap = int(size * 0.10)
    th = max(2, int(size * 0.022))
    for w in widths:
        x_end = left + int((right_full - left) * w)
        fill_rect(left, y, x_end, y + th, LINE)
        y += gap

    # 5) 右下角一个橙色小方块作为"等级"点缀
    s = int(size * 0.07)
    fill_round_rect(size - m - s - int(size * 0.04), size - int(size * 0.16) - s - int(size * 0.04),
                    size - m - int(size * 0.04), size - int(size * 0.16) - int(size * 0.04),
                    int(s * 0.25), ACCENT)

    return buf


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, size in [('icon-192.png', 192), ('icon-512.png', 512),
                       ('apple-touch-icon.png', 180)]:
        write_png(os.path.join(OUT_DIR, name), size, size, make_icon(size))
        print('生成', name, f'({size}x{size})')


if __name__ == '__main__':
    main()
