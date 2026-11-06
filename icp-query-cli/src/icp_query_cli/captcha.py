# -*- coding: utf-8 -*-
"""滑块验证码缺口识别（移植自 ICP_Query v0.7.6，纯 numpy 实现，无需 onnx）。"""
from __future__ import annotations

import base64
import io
import logging

import numpy as np
from PIL import Image

logger = logging.getLogger("icp-query")


def find_slider_offset(small_image_b64: str, big_image_b64: str) -> tuple[bool, int | str]:
    """在大图中定位与滑块同尺寸的纯色缺口，返回其 2x 下采样前的 x 偏移。"""
    small_bytes = base64.b64decode(small_image_b64)
    big_bytes = base64.b64decode(big_image_b64)

    with Image.open(io.BytesIO(small_bytes)) as sm:
        sw, sh = sm.size

    big_img = np.asarray(Image.open(io.BytesIO(big_bytes)).convert("RGB"))
    resized = big_img[::2, ::2]
    h, w = resized.shape[:2]
    min_side = max(1, int(min(sw, sh) * 0.25))
    skip_left = sw // 4
    good_enough = (min_side * min_side * 3) // 2

    q = resized.astype(np.int32) & ~3
    color_id = q[:, :, 0] + q[:, :, 1] * 256 + q[:, :, 2] * 65536

    flat = color_id.ravel()
    unique, counts = np.unique(flat, return_counts=True)
    top_indices = np.argpartition(counts, max(-3, -len(counts)))[-3:]

    best_area = 0
    best_x = 0
    col_run = np.empty((h, w), dtype=np.int32)

    for idx in top_indices:
        c = unique[idx]
        mask = color_id == c
        col_run[0] = mask[0]
        for y in range(1, h):
            col_run[y] = (col_run[y - 1] + 1) * mask[y]

        for y in range(min_side, h):
            row = col_run[y]
            x = skip_left
            while x < w:
                if row[x] < min_side:
                    x += 1
                    continue
                s = x
                while x < w and row[x] >= min_side:
                    x += 1
                run_w = x - s
                run_h = int(row[s])
                if run_h > 0:
                    ratio = run_w / run_h
                    area = run_w * run_h
                    if 0.7 < ratio < 1.4 and area > best_area:
                        best_area = area
                        best_x = s
                        if best_area >= good_enough:
                            offset_x = best_x * 2
                            logger.debug("缺口定位: x=%s, 滑块=%sx%s", offset_x, sw, sh)
                            return True, offset_x

    if best_area == 0:
        return False, "未找到缺口"

    offset_x = best_x * 2
    logger.debug("缺口定位: x=%s, 滑块=%sx%s", offset_x, sw, sh)
    return True, offset_x
