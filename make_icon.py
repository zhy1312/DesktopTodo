# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico（蓝色圆角方块 + 白色对勾）。"""
from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([10, 10, S - 10, S - 10], radius=58, fill=(59, 130, 246, 255))
d.line([(72, 134), (116, 178), (188, 88)], fill=(255, 255, 255, 255),
       width=26, joint="curve")
img.save("icon.ico",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                (64, 64), (128, 128), (256, 256)])
print("icon.ico generated")
