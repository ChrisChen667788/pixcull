"""v2.2-P1-2 — PixCull optional-model manager.

A tiny registry + fetcher for PixCull's *optional* learned models — the
audio-event tagger today; the VLM caption / LLM meta exports next.  The
core tool runs without any of them (each degrades to a tested DSP /
template fallback), so this just turns "download the right file and drop
it in the right place" into one command.

Cache dir: ``~/.pixcull/models/`` — exactly where the consumers already
look (e.g. ``scoring/audio_tagger.py`` searches it first), so a pulled
model is picked up with **no extra wiring**.

Public surface (used by the ``pixcull models`` CLI + tests):

    REGISTRY                      the catalogue (name → ModelSpec)
    models_dir(base=None)         (creates +) returns the cache dir
    get_spec(name)                ModelSpec or KeyError
    resolve_path(name)            cache path for a model (may not exist)
    is_installed(name)            file present AND checksum ok (if known)
    list_models()                 [ModelStatus] for the whole catalogue
    pull(name, force=False)       download + verify + install → Path

Downloads go through ``urllib.request`` which supports ``http(s)://``
*and* ``file://`` — so tests pull a fixture over ``file://`` with a real
checksum, exercising the whole path with no network.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

PIXCULL_HOME = Path.home() / ".pixcull"
_CHUNK = 1 << 20  # 1 MiB


# --------------------------------------------------------------------- #
# Catalogue types
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class Sidecar:
    """An auxiliary file fetched next to a model (e.g. its labels.json)."""
    filename: str
    url: str = ""
    sha256: str = ""


@dataclass(frozen=True)
class ModelSpec:
    name: str                  # CLI handle, e.g. "audio-tagger"
    filename: str              # cached filename, e.g. "audio_tagger.onnx"
    description: str
    used_by: str
    url: str = ""              # "" ⇒ not yet published
    sha256: str = ""           # expected hex digest ("" ⇒ cannot verify)
    size: int = 0              # bytes, for display only
    sidecars: tuple[Sidecar, ...] = ()

    @property
    def published(self) -> bool:
        return bool(self.url)


class ChecksumError(RuntimeError):
    """Downloaded bytes did not match the expected sha256."""


class NotPublishedError(RuntimeError):
    """The model is catalogued but has no download URL yet."""


# --------------------------------------------------------------------- #
# The catalogue.  Real exports fill in url + sha256 + size as the slices
# that produce them ship (audio-tagger → v2.2-P0-1, vlm-caption → P0-3).
# Until then a row is "unpublished": it shows up in `list`, and `pull`
# explains there's nothing to fetch yet rather than 404-ing.
# --------------------------------------------------------------------- #
REGISTRY: dict[str, "ModelSpec"] = {
    "audio-tagger": ModelSpec(
        name="audio-tagger",
        filename="audio_tagger.onnx",
        description="Learned laughter / applause / music tagger (ONNX).",
        used_by="pixcull video · scoring/audio_tagger.py (else DSP fallback)",
        url="",      # published by v2.2-P0-1
        sha256="",
        size=0,
        sidecars=(Sidecar("audio_tagger.onnx.labels.json"),),
    ),
    "vlm-caption": ModelSpec(
        name="vlm-caption",
        filename="vlm_caption.onnx",
        description="Small vision-language model for reel best-frame captions.",
        used_by="pixcull video reel caption (else signal/template fallback)",
        url="",      # published by v2.2-P0-3
    ),
}


# --------------------------------------------------------------------- #
# Paths + integrity
# --------------------------------------------------------------------- #
def models_dir(base: Optional[Path] = None) -> Path:
    """Return the model cache dir, creating it if needed."""
    d = (Path(base) if base is not None else PIXCULL_HOME) / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_spec(name: str, registry: Optional[dict] = None) -> ModelSpec:
    reg = REGISTRY if registry is None else registry
    try:
        return reg[name]
    except KeyError:
        known = ", ".join(sorted(reg)) or "(none)"
        raise KeyError(f"unknown model {name!r}; known: {known}")


def resolve_path(name: str, *, registry: Optional[dict] = None,
                 base: Optional[Path] = None) -> Path:
    """Where the model's file lives in the cache (it may not exist yet)."""
    return models_dir(base) / get_spec(name, registry).filename


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def is_installed(name: str, *, registry: Optional[dict] = None,
                 base: Optional[Path] = None) -> bool:
    """True if the cached file exists and (when known) matches its sha256."""
    spec = get_spec(name, registry)
    p = models_dir(base) / spec.filename
    if not p.exists():
        return False
    return sha256_file(p) == spec.sha256 if spec.sha256 else True


@dataclass
class ModelStatus:
    spec: ModelSpec
    installed: bool
    path: Path


def list_models(*, registry: Optional[dict] = None,
                base: Optional[Path] = None) -> list[ModelStatus]:
    reg = REGISTRY if registry is None else registry
    out: list[ModelStatus] = []
    for name in sorted(reg):
        out.append(ModelStatus(
            spec=reg[name],
            installed=is_installed(name, registry=reg, base=base),
            path=models_dir(base) / reg[name].filename,
        ))
    return out


# --------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------- #
def _download(url: str, dest: Path,
              progress: Optional[Callable[[int, int], None]] = None) -> None:
    """Stream ``url`` → ``dest``.  Supports http(s):// and file://."""
    with urllib.request.urlopen(url) as resp:  # noqa: S310 — URLs are ours
        total = int(resp.headers.get("Content-Length", 0) or 0)
        done = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)


def _fetch_verify_install(url: str, sha256: str, dest: Path,
                          progress=None) -> None:
    """Download to a temp file in dest's dir, verify, atomically move in."""
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        _download(url, tmp, progress=progress)
        if sha256:
            got = sha256_file(tmp)
            if got != sha256:
                raise ChecksumError(
                    f"{dest.name}: sha256 mismatch\n"
                    f"  expected {sha256}\n  got      {got}")
        shutil.move(str(tmp), str(dest))   # same-dir rename → atomic
    finally:
        if tmp.exists():
            tmp.unlink()


def pull(name: str, *, registry: Optional[dict] = None,
         base: Optional[Path] = None, force: bool = False,
         progress=None) -> Path:
    """Download + checksum-verify a model into the cache; return its path.

    Idempotent: an already-installed model (present + checksum-valid) is
    returned untouched unless ``force=True``.

    Raises:
        KeyError           — unknown model name.
        NotPublishedError  — catalogued but no download URL yet.
        ChecksumError      — bytes don't match the expected sha256.
        urllib.error.URLError / OSError — network / IO failure.
    """
    spec = get_spec(name, registry)
    if not spec.published:
        raise NotPublishedError(
            f"model {name!r} is catalogued but not yet published "
            f"(its export ships in a later v2.2 slice) — nothing to fetch.")
    dest = models_dir(base) / spec.filename
    if not force and is_installed(name, registry=registry, base=base):
        return dest

    _fetch_verify_install(spec.url, spec.sha256, dest, progress=progress)
    for sc in spec.sidecars:
        if sc.url:
            _fetch_verify_install(sc.url, sc.sha256, dest.parent / sc.filename)
    return dest
