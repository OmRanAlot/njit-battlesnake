#!/bin/bash
set -e

echo "Starting BattleSnake board on port 3000..."
cd /opt/board
npm run dev &

if [ $# -gt 0 ]; then
  exec "$@"
else
  wait
fi
