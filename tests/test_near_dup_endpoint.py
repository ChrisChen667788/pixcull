"""v2.6-P1 — live-server test for /api/v1/runs/<id>/near_dups.

Pre-writes a synthetic embeddings.npz into the run (so no CLIP model is
needed) and asserts the endpoint groups + heroes against it.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = ROOT / "tests" / "fixtures" / "smoke_run"


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close()
    return p


@pytest.fixture()
def server(tmp_path):
    if not (_FIXTURE / "output" / "scores.csv").is_file():
        pytest.skip("smoke fixture missing")
    root = tmp_path / "demo"
    shutil.copytree(_FIXTURE, root / "smoke_run")
    # Synthetic CLIP cache: shot_01/shot_02 near-identical, shot_03 close
    # to both; shot_04..06 mutually distinct. Hero should be the highest
    # score_final member of the {01,02,03} group.
    import csv as _csv
    rows = list(_csv.DictReader(open(root / "smoke_run" / "output" / "scores.csv")))
    fns = sorted(r["filename"] for r in rows)          # shot_01..shot_06
    base = np.zeros(8, np.float32); base[0] = 1.0
    near = base + np.array([0, .05, 0, 0, 0, 0, 0, 0], np.float32)
    near2 = base + np.array([0, 0, .07, 0, 0, 0, 0, 0], np.float32)
    others = [np.eye(8, dtype=np.float32)[i] for i in (3, 4, 5)]
    vecs = np.stack([base, near, near2] + others)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    with open(root / "smoke_run" / "output" / "embeddings.npz", "wb") as fh:
        np.savez(fh, filenames=np.array(fns), vectors=vecs,
                 model=np.array("clip-vit-base-patch32"))

    env = {**os.environ, "PIXCULL_DEMO_ROOT": str(root)}
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve_demo.py"),
         "--port", str(port), "--host", "127.0.0.1", "--no-open"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    base_url = f"http://127.0.0.1:{port}"
    up = False
    for _ in range(40):
        if proc.poll() is not None:
            break
        try:
            urllib.request.urlopen(f"{base_url}/results/smoke_run", timeout=1)
            up = True; break
        except Exception:
            time.sleep(0.4)
    if not up:
        proc.terminate(); pytest.skip("serve_demo did not come up")
    yield base_url, fns, rows
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()


def test_near_dups_groups_and_hero(server):
    base_url, fns, rows = server
    d = json.loads(urllib.request.urlopen(
        f"{base_url}/api/v1/runs/smoke_run/near_dups", timeout=20).read())
    assert d["schema"].startswith("pixcull.api.v1.near_dups")
    assert d["cached"] is True                       # used the pre-written npz
    assert d["n_photos"] == 6
    assert len(d["groups"]) == 1
    g = d["groups"][0]
    assert sorted(g["members"]) == fns[:3]           # shot_01..03 fold together
    # hero = highest score_final among the members
    scores = {r["filename"]: float(r["score_final"]) for r in rows
              if r["filename"] in g["members"]}
    assert g["hero"] == max(scores, key=scores.get)


def test_near_dups_threshold_param(server):
    base_url, fns, _ = server
    # ~0.999 threshold: even the planted near-pairs unlink → no groups
    d = json.loads(urllib.request.urlopen(
        f"{base_url}/api/v1/runs/smoke_run/near_dups?threshold=0.999",
        timeout=20).read())
    assert d["groups"] == []
    d2 = json.loads(urllib.request.urlopen(
        f"{base_url}/api/v1/runs/smoke_run/near_dups?threshold=junk",
        timeout=20).read())
    assert abs(d2["threshold"] - 0.92) < 1e-9        # bad param → default


def test_near_dups_unknown_run(server):
    base_url, _, _ = server
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(f"{base_url}/api/v1/runs/nope/near_dups",
                               timeout=10)
    assert ei.value.code == 404
