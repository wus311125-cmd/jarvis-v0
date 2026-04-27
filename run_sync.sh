#!/bin/bash
set -e
cd /Users/nhp/jarvis-v0
export $(grep -v '^\s*#' .env | grep -v '^\s*$' | xargs)
source .venv/bin/activate
python sync.py
