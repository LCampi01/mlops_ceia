#!/bin/bash

COMMAND="$1"

if [ "$COMMAND" == "--stop" ]; then
  docker compose stop
elif [ "$COMMAND" == "--destroy" ]; then
  docker compose down -v -t 0
else
  docker compose --profile all up
if
