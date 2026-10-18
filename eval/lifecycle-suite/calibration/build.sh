#!/usr/bin/env bash
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
#
# Build the calibration image from HEAD of a clean checkout:
#   eval/lifecycle-suite/calibration/build.sh
# The image is tagged memkernel-calibration:<short sha>.
set -euo pipefail

repo=$(git rev-parse --show-toplevel)
cd "$repo"
if [ -n "$(git status --porcelain)" ]; then
  echo "build.sh: the working tree is not clean; commit or stash first, so the image is exactly one commit" >&2
  exit 1
fi
sha=$(git rev-parse HEAD)
context=$(mktemp -d)
trap 'rm -rf "$context"' EXIT
git archive --format=tar HEAD | tar -x -C "$context"
docker build \
  --file "$context/eval/lifecycle-suite/calibration/Dockerfile" \
  --build-arg "CODE_SHA=$sha" \
  --tag "memkernel-calibration:${sha:0:12}" \
  "$context"
echo "built memkernel-calibration:${sha:0:12} from $sha"
