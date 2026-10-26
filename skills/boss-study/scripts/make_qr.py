#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给学习站生成一张手机扫码直达二维码（可选步骤）。

依赖：pip install qrcode pillow
用法：python scripts/make_qr.py --url https://ccccty.github.io/study/ --out ../my-study/qr.png
"""

import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser(description="生成站点二维码")
    ap.add_argument("--url", required=True, help="站点地址")
    ap.add_argument("--out", required=True, help="输出 PNG 路径")
    ap.add_argument("--title", default="", help="二维码下方标题，默认取 URL")
    args = ap.parse_args()

    try:
        import qrcode
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        sys.exit("[错误] 缺依赖：pip install qrcode pillow（这一步是可选的，跳过也不影响站点）")

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=12, border=2)
    qr.add_data(args.url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1b1f2a", back_color="white").convert("RGB")

    W, H = img.size
    pad = 70
    canvas = Image.new("RGB", (W, H + pad), "white")
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)

    font = font2 = None
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
              "/System/Library/Fonts/PingFang.ttc",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"):
        try:
            font = ImageFont.truetype(p, 26)
            break
        except Exception:
            continue
    for p in (r"C:\Windows\Fonts\arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            font2 = ImageFont.truetype(p, 17)
            break
        except Exception:
            continue

    title = args.title or "扫码打开"
    sub = args.url.replace("https://", "").replace("http://", "").rstrip("/")
    if font:
        d.text(((W - d.textlength(title, font=font)) / 2, H + 18), title,
               fill="#1b1f2a", font=font)
    if font2:
        d.text(((W - d.textlength(sub, font=font2)) / 2, H + 46), sub,
               fill="#8b93a5", font=font2)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    canvas.save(args.out)
    print("saved", args.out, canvas.size)


if __name__ == "__main__":
    main()
