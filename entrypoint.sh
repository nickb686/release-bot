#!/usr/bin/bash

while true; do
    uv run alembic upgrade head
    if [[ "$?" == "0" ]]; then
        break
    fi
    echo Deploy command failed, retrying in 5 secs...
    sleep 5
done
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
