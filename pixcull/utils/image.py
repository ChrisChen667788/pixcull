import cv2
import numpy as np
from PIL import Image


def to_gray(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)


def resize_keep_ratio(img: Image.Image, max_side: int) -> Image.Image:
    if max(img.size) <= max_side:
        return img
    img = img.copy()
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img
