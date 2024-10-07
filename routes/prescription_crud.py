from flask import Blueprint, request

from services import prescription_drug_edit_service
from services import prescription_drug_service
from decorators.api_endpoint_decorator import api_endpoint

app_pres_crud = Blueprint("app_pres_crud", __name__)


@app_pres_crud.route("/editPrescription/drug/<int:idPrescriptionDrug>", methods=["PUT"])
@api_endpoint()
def actionUpdatePrescriptionDrug(idPrescriptionDrug):
    data = request.get_json()

    prescription_drug_edit_service.updatePrescriptionDrug(idPrescriptionDrug, data)

    pd = prescription_drug_service.getPrescriptionDrug(idPrescriptionDrug)

    return prescription_drug_service.prescriptionDrugToDTO(pd)


@app_pres_crud.route("/editPrescription/drug", methods=["POST"])
@api_endpoint()
def actionCreatePrescriptionDrug():
    data = request.get_json()

    newId = prescription_drug_edit_service.createPrescriptionDrug(data)

    pd = prescription_drug_service.getPrescriptionDrug(newId)

    return prescription_drug_service.prescriptionDrugToDTO(pd)


@app_pres_crud.route(
    "/editPrescription/drug/<int:idPrescriptionDrug>/suspend/<int:suspend>",
    methods=["PUT"],
)
@api_endpoint()
def actionSuspendPrescriptionDrug(idPrescriptionDrug, suspend):
    pdUpdate = prescription_drug_edit_service.togglePrescriptionDrugSuspension(
        idPrescriptionDrug=idPrescriptionDrug, suspend=True if suspend == 1 else False
    )

    return {
        "idPrescription": str(pdUpdate.idPrescription),
        "idPrescriptionDrug": str(pdUpdate.id),
        "idDrug": pdUpdate.idDrug,
        "suspended": True if suspend == 1 else False,
    }


@app_pres_crud.route(
    "/editPrescription/<int:idPrescription>/missing-drugs", methods=["GET"]
)
@api_endpoint()
def get_prescription_missing_drugs(idPrescription):
    missing_drugs = prescription_drug_edit_service.get_missing_drugs(idPrescription)

    list = []
    for d in missing_drugs:
        list.append({"idDrug": d[0], "name": d[1]})

    return list


@app_pres_crud.route(
    "/editPrescription/<int:idPrescription>/missing-drugs/copy", methods=["POST"]
)
@api_endpoint()
def copy_prescription_missing_drugs(idPrescription):
    data = request.get_json()

    prescription_drug_edit_service.copy_missing_drugs(
        idPrescription=idPrescription, idDrugs=data.get("idDrugs", None)
    )

    return 1
