#!/usr/bin/env bash
# Render build script — installs system deps + Python package
set -e

# Install ffmpeg for video assembler
apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Install Python package
pip install --upgrade pip
pip install -e .
