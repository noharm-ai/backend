import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services import memory_service
from exception.validation_error import ValidationError

app_rpt_general = Blueprint("app_rpt_general", __name__)


@app_rpt_general.route("/reports/general/prescription", methods=["GET"])
@jwt_required()
def general_prescription():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    cache = memory_service.get_memory("rpt_general")

    if cache is not None:
        return {
            "status": "success",
            "data": cache.value,
        }, status.HTTP_200_OK

    sql = f"""
        	select 
                distinct on (p.fkprescricao)
                p.fksetor,
                p.fkprescricao,
                p.convenio,
                p.nratendimento,
                s.nome as setorNome,
                p.dtprescricao::date as data,
                case 
                    when p.status = 's' then 1
                    when pa.fkprescricao is not null then 1
                    else 0
                end as checada,
                case 
                    when pa.fkprescricao is null then coalesce(array_length(p.aggmedicamento,1), 1)
                    else pa.total_itens
                end total_itens,
                case 
                    when p.status <> 's' and pa.fkprescricao is null then 0
                    when pa.fkprescricao is not null then pa.total_itens 
                    else coalesce(array_length(p.aggmedicamento,1), 1)
                end total_itens_checados,
                case
                    when p.status <> 's' and pa.fkprescricao is null then 'Não Checado'
                    when pa.fkprescricao is not null then user_pa.nome
                    else user_p.nome
                end as userNome
            from 
                {user.schema}.prescricao p 
                inner join {user.schema}.setor s on s.fksetor = p.fksetor
                left join (
                    select * from {user.schema}.prescricao_audit pa where pa.tp_audit = 1
                ) pa on pa.fkprescricao = p.fkprescricao
                left join public.usuario user_p on (p.update_by = user_p.idusuario)
                left join public.usuario user_pa on pa.created_by = user_pa.idusuario
            where 
                p.agregada = true 
                and p.concilia IS null 
                and s.fksetor in (select s2.fksetor from {user.schema}.segmentosetor s2 where s2.idsegmento is not null)
                and p.dtprescricao > now() - interval '2 months'
            order by p.fkprescricao, pa.created_at desc
    """

    db_session = db.create_scoped_session(
        options={"bind": db.get_engine(db.get_app(), "report")}
    )

    results = db_session.execute(sql).fetchall()
    itens = []
    for i in results:
        itens.append(
            {
                "idDepartment": i[0],
                "idPrescription": i[1],
                "insurance": i[2],
                "admissionNumber": i[3],
                "department": i[4],
                "date": i[5].isoformat(),
                "checked": i[6],
                "itens": i[7],
                "checkedItens": i[8],
                "responsible": i[9],
            }
        )

    memory_service.save_unique_memory("rpt_general", itens, user)

    return tryCommit(
        db,
        {
            "status": "success",
            "data": itens,
        },
    )
