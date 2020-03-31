#!/bin/bash

TOKEN=$(curl -X POST -d '{"email":"demo", "password":"demo"}' -H "Content-Type: application/json" http://localhost:5000/authenticate | jq -r '.access_token')

for DRUG in 1 2 3
do
  LINK=(http://localhost:5000/segments/1/outliers/generate/drug/${DRUG})
  COMMAND=("curl -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' ${LINK}")
  printf "${LINK} "
  bash -c "${COMMAND}"
  printf "\n"
done