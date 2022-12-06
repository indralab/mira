#!/bin/bash
neo4j start
sleep 100
neo4j status
if [ "${ROOT_PATH}" ]; then
  uvicorn --host 0.0.0.0 --port 8771 mira.dkg.wsgi:app --root-path "${ROOT_PATH}"
else
  uvicorn --host 0.0.0.0 --port 8771 mira.dkg.wsgi:app
fi
