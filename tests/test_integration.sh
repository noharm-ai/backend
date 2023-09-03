#!/bin/bash
declare -i EXITSUM=0

HOST=("localhost:5000")
printf "Authenticating Admin...\n"
TOKEN=$(curl -X POST -d '{"email":"demo", "password":"demo"}' -H "Content-Type: application/json" ${HOST}/authenticate | jq -r '.access_token')
EXITSUM+=$?

SEGMENT=1
DRUG=5
PRESCRIPTION=20
PRESCRIPTIONDRUG=20
ADMISSION=5

for LINK in reports outliers/${SEGMENT}/${DRUG} \
			intervention/reasons drugs/${SEGMENT} substance \
			"prescriptions?idSegment=${SEGMENT}&date=2020-12-31" prescriptions/${PRESCRIPTION} \
			prescriptions/drug/${PRESCRIPTIONDRUG}/period \
			static/demo/prescription/${PRESCRIPTION} \
			exams/${ADMISSION} segments segments/${SEGMENT} departments \
			segments/exams/types notes/${ADMISSION} \
			segments/${SEGMENT}/outliers/generate/drug/${DRUG} 
do
  COMMAND=("-H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' '${HOST}/${LINK}'")
  printf "${LINK} "
  bash -c "curl ${COMMAND}"
  bash -c "curl --silent --fail ${COMMAND} > /dev/null"
  EXITSUM+=$?
  printf "\n"
done

LINK=("prescriptions/${PRESCRIPTION}")
DATA=('{ "status": "s"}')
COMMAND=("-X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
STATUSCODE=$(bash -c "curl --silent --output /dev/null --write-out '%{http_code}' ${COMMAND}")
if [[ ${STATUSCODE} -ne 401 ]]; then EXITSUM+=22; fi;
printf "\n"

LINK=("patient/${ADMISSION}")
DATA=('{ "height": 15}')
COMMAND=("-X POST -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
STATUSCODE=$(bash -c "curl --silent --output /dev/null --write-out '%{http_code}' ${COMMAND}")
if [[ ${STATUSCODE} -ne 401 ]]; then EXITSUM+=22; fi;
printf "\n"

LINK=("intervention/${PRESCRIPTIONDRUG}")
DATA=('{ "status": "s", "admissionNumber": 5}')
COMMAND=("-X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
STATUSCODE=$(bash -c "curl --silent --output /dev/null --write-out '%{http_code}' ${COMMAND}")
if [[ ${STATUSCODE} -ne 401 ]]; then EXITSUM+=22; fi;
printf "\n"

############################
#  Not Admin User Actions  #
############################

HOST=("localhost:5000")
printf "Authenticating Not Admin...\n"
TOKEN=$(curl -X POST -d '{"email":"noadmin", "password":"noadmin"}' -H "Content-Type: application/json" ${HOST}/authenticate | jq -r '.access_token')
EXITSUM+=$?

LINK=("prescriptions/404")
COMMAND=("-H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' '${HOST}/${LINK}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
STATUSCODE=$(bash -c "curl --silent --output /dev/null --write-out '%{http_code}' ${COMMAND}")
if [[ ${STATUSCODE} -ne 400 ]]; then EXITSUM+=22; fi;
printf "\n"

LINK=("drugs/${DRUG}")
DATA=('{ "idSegment": 1, "mav": true }')
COMMAND=("-X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
bash -c "curl --silent --fail ${COMMAND} > /dev/null"
EXITSUM+=$?
printf "\n"

LINK=("prescriptions/${PRESCRIPTION}")
DATA=('{ "status": "s"}')
COMMAND=("-X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
bash -c "curl --silent --fail ${COMMAND} > /dev/null"
EXITSUM+=$?
printf "\n"

LINK=("patient/${ADMISSION}")
DATA=('{ "height": 15}')
COMMAND=("-X POST -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
bash -c "curl --silent --fail ${COMMAND} > /dev/null"
EXITSUM+=$?
printf "\n"

LINK=("patient/404")
DATA=('{ "height": 15}')
COMMAND=("-X POST -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
STATUSCODE=$(bash -c "curl --silent --output /dev/null --write-out '%{http_code}' ${COMMAND}")
if [[ ${STATUSCODE} -ne 400 ]]; then EXITSUM+=22; fi;
printf "\n"

LINK=("prescriptions/drug/${PRESCRIPTIONDRUG}")
DATA=('{ "notes": "some notes", "admissionNumber": 5}')
COMMAND=("-X PUT -H 'Accept: application/json' -H 'Authorization: Bearer ${TOKEN}' -H 'Content-Type: application/json' ${HOST}/${LINK} -d '${DATA}'")
printf "${LINK} "
bash -c "curl ${COMMAND}"
bash -c "curl --silent --fail ${COMMAND} > /dev/null"
EXITSUM+=$?
printf "\n"

echo "EXITSUM = ${EXITSUM}"
exit $EXITSUM