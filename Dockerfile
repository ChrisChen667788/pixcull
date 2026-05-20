# PixCull · single-stage Docker image
#
# Quickest path for someone to try the project without installing
# Python / building a venv / pulling 1.5 GB of ML models locally.
#
# Build:
#   docker build -t pixcull .
#
# Run (drop a folder of JPGs in to be scored):
#   docker run --rm -p 8770:8770 \
#     -v "$(pwd)/photos:/data/photos" \
#     -v "$HOME/.cache/pixcull-models:/root/.cache" \
#     pixcull
#
#   then open http://localhost:8770
#
# The second mount caches the ML model weights (~500 MB on first
# run: CLIP + InsightFace + MediaPipe + LAION-aesthetic + rembg).
# Without it every container restart re-downloads.
#
# Photos: the upload page accepts drag-drop directly in the
# browser, but if you mount a folder at /data/photos the
# "扫描本地文件夹" tab can scan it in place (no copy).

FROM python:3.12-slim

# System deps:
#   libgl1 + libglib2.0   for opencv-python's image I/O
#   libxext6 + libsm6     for some rawpy decode paths
#   exiftool              soft-dep for IPTC embed (V29.1)
#   git                   pip install -e in dev mode reaches it
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libxext6 \
        libsm6 \
        exiftool \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pin CPU torch wheels — the GPU build is 2 GB heavier and
# unnecessary for the rescorer head we actually use.
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

# Copy minimal install metadata first so the heavy pip-install
# layer caches between rebuilds when only source code changes.
COPY pyproject.toml README.md LICENSE ./
COPY pixcull/ ./pixcull/

RUN pip install --upgrade pip && \
    pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        "torch==2.4.1" "torchvision==0.19.1" && \
    pip install --no-cache-dir -e .

# Copy the runtime scripts + iOS + plugin trees last so source
# edits don't bust the dependency layer.
COPY scripts/        ./scripts/
COPY tests/          ./tests/
COPY lr_plugin/      ./lr_plugin/
COPY mobile/         ./mobile/
COPY docs/           ./docs/
COPY training.csv training_axis.csv ./

# Default ports + data dir
ENV PIXCULL_DATA_DIR=/data
EXPOSE 8770

# Bind to 0.0.0.0 so the host can reach us via the published port.
# --no-open suppresses the auto-Chrome-launch that's pointless in
# a container.
CMD ["python", "scripts/serve_demo.py", "--port", "8770", "--no-open", "--host", "0.0.0.0"]
