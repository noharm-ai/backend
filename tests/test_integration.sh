#!/bin/bash

HOST=("localhost:5000")
printf "Authenticating..."
TOKEN=$(curl -X POST -d '{"email":"demo", "password":"demo"}' -H "Content-Type: application/json" ${HOST}/authenticate | jq -r '.access_token')

SEGMENT=1
DRUG=5
PRESCRIPTION=20
PRESCRIPTIONDRUG=20
ADMISSION=5

for LINK in reports patient-name/123 user/name-url outliers/${SEGMENT}/${DRUG} \
			intervention/reasons intervention drugs/${SEGMENT} substance \
			prescriptions prescriptions/${PRESCRIPTION} \
			prescriptions/drug/${PRESCRIPTIONDRUG}/period \
			/static/demo/prescription/${PRESCRIPTION} \
			exams/${ADMISSION} segments segments/${SEGMENT} departments departments/free \
			segments/exams/types \
			/segments/${SEGMENT}/outliers/generate/drug/${DRUG} 
do
  COMMAND=("curl -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' ${HOST}/${LINK}")
  printf "${LINK} "
  bash -c "${COMMAND}"
  printf "\n"
done

LINK=("segments/${SEGMENT}")
DATA=('{ "status": 1}')
COMMAND=("curl -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
printf "\n"

LINK=("drugs/${DRUG}")
DATA=('{ "idSegment": 1, "mav": true }')
COMMAND=("curl -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
printf "\n"

LINK=("prescriptions/${PRESCRIPTION}")
DATA=('{ "status": "s"}')
COMMAND=("curl -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
printf "\n"

LINK=("patient/${ADMISSION}")
DATA=('{ "height": 15}')
COMMAND=("curl -X POST -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
printf "\n"

LINK=("prescriptions/drug/${PRESCRIPTIONDRUG}")
DATA=('{ "height": 15}')
COMMAND=("curl -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
printf "\n"

LINK=("prescriptions/drug/${PRESCRIPTIONDRUG}/1")
COMMAND=("curl -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
printf "\n"

LINK=("intervention/${PRESCRIPTIONDRUG}")
DATA=('{ "status": "s"}')
COMMAND=("curl -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
printf "\n"