RAW_EXTS: set[str] = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng", ".orf", ".rw2"}
IMG_EXTS: set[str] = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}
ALL_EXTS: set[str] = RAW_EXTS | IMG_EXTS


def is_raw(path_or_ext: str) -> bool:
    ext = path_or_ext if path_or_ext.startswith(".") else "." + path_or_ext.rsplit(".", 1)[-1]
    return ext.lower() in RAW_EXTS
