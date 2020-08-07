#!/bin/bash
declare -i EXITSUM=0

HOST=("localhost:5000")
printf "Authenticating...\n"
TOKEN=$(curl -X POST -d '{"email":"demo", "password":"demo"}' -H "Content-Type: application/json" ${HOST}/authenticate | jq -r '.access_token')
EXITSUM+=$?

SEGMENT=1
DRUG=5
PRESCRIPTION=20
PRESCRIPTIONDRUG=20
ADMISSION=5

for LINK in reports patient-name/123 user/name-url outliers/${SEGMENT}/${DRUG} \
			intervention/reasons intervention drugs/${SEGMENT} substance \
			"prescriptions?idSegment=${SEGMENT}&date=2020-12-31" prescriptions/${PRESCRIPTION} \
			prescriptions/drug/${PRESCRIPTIONDRUG}/period \
			static/demo/prescription/${PRESCRIPTION} \
			exams/${ADMISSION} segments segments/${SEGMENT} departments departments/free \
			segments/exams/types \
			segments/${SEGMENT}/outliers/generate/drug/${DRUG} 
do
  COMMAND=("curl --fail -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' '${HOST}/${LINK}'")
  printf "${LINK} "
  bash -c "${COMMAND}"
  EXITSUM+=$?
  printf "\n"
done

LINK=("drugs/${DRUG}")
DATA=('{ "idSegment": 1, "mav": true }')
COMMAND=("curl --fail -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
EXITSUM+=$?
printf "\n"

LINK=("prescriptions/${PRESCRIPTION}")
DATA=('{ "status": "s"}')
COMMAND=("curl --fail -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
EXITSUM+=$?
printf "\n"

LINK=("patient/${ADMISSION}")
DATA=('{ "height": 15}')
COMMAND=("curl --fail -X POST -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
EXITSUM+=$?
printf "\n"

LINK=("prescriptions/drug/${PRESCRIPTIONDRUG}")
DATA=('{ "height": 15}')
COMMAND=("curl --fail -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
EXITSUM+=$?
printf "\n"

LINK=("prescriptions/drug/${PRESCRIPTIONDRUG}/1")
COMMAND=("curl --fail -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
EXITSUM+=$?
printf "\n"

LINK=("intervention/${PRESCRIPTIONDRUG}")
DATA=('{ "status": "s", "admissionNumber": 12832489}')
COMMAND=("curl --fail -X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "${COMMAND}"
EXITSUM+=$?
printf "\n"

echo "EXITSUM = ${EXITSUM}"
exit $EXITSUM