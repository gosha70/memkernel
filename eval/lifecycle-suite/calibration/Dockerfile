# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
#
# Disposable calibration environment (specs/memkernel-0-5 FR-015, task 18).
# Built by build.sh from `git archive` of one commit, so the image holds exactly
# that code. Python dependencies come from that commit's poetry.lock, with
# hashes. The one exception is torch: the locked version, but the CPU build
# from PyTorch's index, and the CUDA-only packages are left out. wiki-studio,
# in its own venv, is the locked version with its locked hashes. The embedding
# model is cached at a pinned revision and the build fails on any other. The resolved
# environment is written to /opt/environment.txt and copied into every run.
# Nothing from the host is mounted except the runs directory, and no credential
# is baked in: the API key arrives at `docker run` time only.
ARG PYTHON_IMAGE=python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce

FROM ${PYTHON_IMAGE} AS lock
ARG POETRY_VERSION=2.4.3
ARG POETRY_EXPORT_VERSION=1.10.1
COPY pyproject.toml poetry.lock /lock/
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}" "poetry-plugin-export==${POETRY_EXPORT_VERSION}" \
 && cd /lock && poetry export --only main --format requirements.txt --output requirements.txt \
 && python - <<'EOF'
# Drop torch, installed from the CPU index below, and its CUDA-only dependencies (nvidia-*, cuda-*, triton).
import re
from pathlib import Path
path = Path("/lock/requirements.txt")
entries = re.split(r"\n(?=\S)", path.read_text())
skip = re.compile(r"^(torch|triton|nvidia-[a-z0-9-]+|cuda-[a-z0-9-]+)==")
kept = [entry for entry in entries if entry.strip() and not skip.match(entry)]
path.write_text("\n".join(kept) + "\n")
torch = re.search(r'^name = "torch"\nversion = "([^"]+)"', Path("/lock/poetry.lock").read_text(), re.M)
Path("/lock/torch-version").write_text(torch.group(1))
# wiki-studio (no dependencies of its own) for its own venv, at the locked version with the locked hashes.
import tomllib
(ws,) = [p for p in tomllib.loads(Path("/lock/poetry.lock").read_text())["package"] if p["name"] == "wiki-studio"]
hashes = " ".join(f"--hash={f['hash']}" for f in ws["files"])
Path("/lock/wiki-studio.txt").write_text(f"wiki-studio=={ws['version']} {hashes}\n")
EOF

FROM ${PYTHON_IMAGE}
ARG CODE_SHA
ARG CLAUDE_CODE_VERSION=2.1.288
ARG WIKI_STUDIO_VERSION=0.4.1
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2
ARG EMBEDDING_MODEL_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41

RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force

COPY --from=lock /lock/requirements.txt /lock/torch-version /lock/wiki-studio.txt /opt/lock/
COPY . /opt/memkernel
RUN python -m venv /opt/mk-venv \
 && /opt/mk-venv/bin/pip install --no-cache-dir --no-deps --require-hashes -r /opt/lock/requirements.txt \
 && /opt/mk-venv/bin/pip install --no-cache-dir --no-deps --index-url https://download.pytorch.org/whl/cpu \
      "torch==$(cat /opt/lock/torch-version)" \
 && /opt/mk-venv/bin/pip install --no-cache-dir --no-deps /opt/memkernel \
 && /opt/mk-venv/bin/pip check \
 && python -m venv /opt/ws-venv \
 && /opt/ws-venv/bin/pip install --no-cache-dir --no-deps --require-hashes -r /opt/lock/wiki-studio.txt \
 && test "$(/opt/ws-venv/bin/wiki-studio --version)" = "${WIKI_STUDIO_VERSION}" \
 && ln -s /opt/ws-venv/bin/wiki-studio /usr/local/bin/wiki-studio \
 && HF_HOME=/opt/cache/huggingface /opt/mk-venv/bin/python -c \
      "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')" \
 && cached=$(cat "/opt/cache/huggingface/hub/models--sentence-transformers--${EMBEDDING_MODEL}/refs/main") \
 && { [ "$cached" = "${EMBEDDING_MODEL_REVISION}" ] \
      || { echo "the Hub served ${EMBEDDING_MODEL} revision $cached, not the pinned ${EMBEDDING_MODEL_REVISION}" >&2; exit 1; }; } \
 && HF_HOME=/opt/cache/huggingface HF_HUB_OFFLINE=1 /opt/mk-venv/bin/python -c \
      "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')" \
 && { echo "# code ${CODE_SHA}"; echo "# claude-code ${CLAUDE_CODE_VERSION}"; \
      echo "# wiki-studio ${WIKI_STUDIO_VERSION}"; \
      echo "# embedding model sentence-transformers/${EMBEDDING_MODEL} revision ${EMBEDDING_MODEL_REVISION}"; \
      echo "# run.sh sha256 $(sha256sum /opt/memkernel/eval/lifecycle-suite/calibration/run.sh | cut -d' ' -f1)"; \
      echo "# memkernel venv (pip freeze):"; \
      /opt/mk-venv/bin/pip freeze --all; \
      echo "# wiki-studio venv (pip freeze):"; \
      /opt/ws-venv/bin/pip freeze --all; } > /opt/environment.txt

RUN useradd --create-home --uid 1000 runner \
 && mkdir -p /runs && chown runner /runs \
 && chmod -R a+rX /opt/cache
ENV CODE_SHA=${CODE_SHA} \
    CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION} \
    WIKI_STUDIO_VERSION=${WIKI_STUDIO_VERSION} \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    EMBEDDING_MODEL_REVISION=${EMBEDDING_MODEL_REVISION}
USER runner
WORKDIR /home/runner
ENTRYPOINT ["/opt/memkernel/eval/lifecycle-suite/calibration/run.sh"]
CMD ["calibrate"]
