#!/bin/bash
# Cron wrapper for stock-mcp funnel
cd /home/admin/projects/stock-mcp-server
source .venv/bin/activate
export PYTHONUNBUFFERED=1
python scripts/run_funnel.py >> /home/admin/projects/stock-mcp-server/data/funnel_cron.log 2>&1
