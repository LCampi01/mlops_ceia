#!/bin/bash

COMMAND="$1"

if [ "$COMMAND" == "--stop" ]; then
  docker compose stop
elif [ "$COMMAND" == "--destroy" ]; then
  docker compose down -v
else
  docker compose up -d
fi
