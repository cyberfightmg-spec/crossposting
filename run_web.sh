#!/bin/bash
cd /root/crossposting
source .venv/bin/activate
export MODE=web
exec python main.py