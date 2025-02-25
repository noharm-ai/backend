import redis
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, asc
from datetime import date
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import deferred
from flask_mail import Mail
from flask_jwt_extended import get_jwt

from config import Config

db = SQLAlchemy()
mail = Mail()
redis_client = redis.StrictRedis(
    host=Config.REDIS_HOST,
    port=Config.REDIS_PORT,
    db=0,
    decode_responses=True,
    ssl=True,
    socket_timeout=2,
    socket_connect_timeout=2,
)


class dbSession:
    def setSchema(schema):
        db.session.connection(
            execution_options={"schema_translate_map": {None: schema}}
        )


class User(db.Model):
    __tablename__ = "usuario"
    __table_args__ = {"schema": "public"}

    id = db.Column("idusuario", db.BigInteger, primary_key=True)
    name = db.Column("nome", db.String(250), nullable=False)
    email = db.Column("email", db.String(254), unique=True, nullable=False)
    password = db.Column("senha", db.String(128), nullable=False)
    schema = db.Column("schema", db.String, nullable=False)
    config = db.Column("config", postgresql.JSON, nullable=False)
    reports_config = db.Column("relatorios", postgresql.JSON, nullable=True)
    external = db.Column("fkusuario", db.String, nullable=False)
    active = db.Column("ativo", db.Boolean, nullable=True)

    def find(id):
        user = User()
        user.id = id
        claims = get_jwt()
        user.schema = claims["schema"]
        user.config = claims["config"]
        return user


class UserAudit(db.Model):
    __tablename__ = "usuario_audit"
    __table_args__ = {"schema": "public"}

    id = db.Column("idusuario_audit", db.BigInteger, primary_key=True)
    idUser = db.Column("idusuario", db.BigInteger, nullable=False)
    auditType = db.Column("tp_audit", db.Integer, nullable=False)
    pwToken = db.Column("pw_token", db.String, nullable=True)
    extra = db.Column("extra", postgresql.JSON, nullable=True)
    auditIp = db.Column("audit_ip", db.String, nullable=True)
    createdAt = db.Column("created_at", db.DateTime, nullable=False)
    createdBy = db.Column("created_by", db.BigInteger, nullable=False)


class UserAuthorization(db.Model):
    __tablename__ = "usuario_autorizacao"
    __table_args__ = {"schema": "public"}

    id = db.Column("idusuario_autorizacao", db.BigInteger, primary_key=True)
    idUser = db.Column("idusuario", db.BigInteger, nullable=False)
    idSegment = db.Column("idsegmento", db.BigInteger, nullable=True)
    schemaName = db.Column("schema_name", db.String, nullable=True)
    createdAt = db.Column("created_at", db.DateTime, nullable=False)
    createdBy = db.Column("created_by", db.BigInteger, nullable=False)


class UserExtra(db.Model):
    __tablename__ = "usuario_extra"
    __table_args__ = {"schema": "public"}

    idUser = db.Column("idusuario", db.BigInteger, primary_key=True)
    config = db.Column("config", postgresql.JSON, nullable=False)
    createdAt = db.Column("created_at", db.DateTime, nullable=False)
    createdBy = db.Column("created_by", db.BigInteger, nullable=False)


class Substance(db.Model):
    __tablename__ = "substancia"
    __table_args__ = {"schema": "public"}

    id = db.Column("sctid", db.BigInteger, primary_key=True)
    name = db.Column("nome", db.String(255), nullable=False)
    link = db.Column("link", db.String(255), nullable=False)
    idclass = db.Column("idclasse", db.String(255), nullable=False)
    active = db.Column("ativo", db.Boolean, nullable=False)
    maxdose_adult = db.Column("dosemax_adulto", db.Float, nullable=True)
    maxdose_pediatric = db.Column("dosemax_pediatrico", db.Float, nullable=True)
    maxdose_adult_weight = db.Column("dosemax_peso_adulto", db.Float, nullable=True)
    maxdose_pediatric_weight = db.Column(
        "dosemax_peso_pediatrico", db.Float, nullable=True
    )
    default_measureunit = db.Column("unidadepadrao", db.String, nullable=True)
    handling = deferred(
        db.Column("manejo", postgresql.JSONB(none_as_null=True), nullable=True)
    )
    admin_text = deferred(db.Column("curadoria", db.String, nullable=True))
    updatedAt = db.Column("update_at", db.DateTime, nullable=True)
    updatedBy = db.Column("update_by", db.BigInteger, nullable=True)
    tags = db.Column("tags", postgresql.ARRAY(db.String(100)), nullable=True)
    kidney_adult = db.Column("renal_adulto", db.Integer, nullable=True)
    kidney_pediatric = db.Column("renal_pediatrico", db.Integer, nullable=True)
    liver_adult = db.Column("hepatico_adulto", db.Integer, nullable=True)
    liver_pediatric = db.Column("hepatico_pediatrico", db.Integer, nullable=True)
    fall_risk = db.Column("risco_queda", db.Integer, nullable=True)
    pregnant = db.Column("gestante", db.String, nullable=True)
    lactating = db.Column("lactante", db.String, nullable=True)
    platelets = db.Column("plaquetas", db.Integer, nullable=True)
    division_range = db.Column("divisor_faixa", db.Float, nullable=True)


class SubstanceClass(db.Model):
    __tablename__ = "classe"
    __table_args__ = {"schema": "public"}

    id = db.Column("idclasse", db.String(10), primary_key=True)
    idParent = db.Column("idclassemae", db.String(10), nullable=False)
    name = db.Column("nome", db.String(255), nullable=False)


class Relation(db.Model):
    __tablename__ = "relacao"
    __table_args__ = {"schema": "public"}

    sctida = db.Column("sctida", db.BigInteger, primary_key=True)
    sctidb = db.Column("sctidb", db.BigInteger, primary_key=True)
    kind = db.Column("tprelacao", db.String(2), primary_key=True)
    text = db.Column("texto", db.String, nullable=True)
    level = db.Column("nivel", db.String, nullable=True)
    active = db.Column("ativo", db.Boolean, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.BigInteger, nullable=True)
    creator = db.Column("create_by", db.BigInteger, nullable=True)


class Notify(db.Model):
    __tablename__ = "notifica"
    __table_args__ = {"schema": "public"}

    id = db.Column("idnotifica", db.BigInteger, primary_key=True, autoincrement=True)
    title = db.Column("titulo", db.String(100), nullable=False)
    tooltip = db.Column("tooltip", db.String(255), nullable=False)
    link = db.Column("link", db.String(100), nullable=False)
    icon = db.Column("icon", db.String(25), nullable=False)
    classname = db.Column("classname", db.String(50), nullable=False)
    startDate = db.Column("inicio", db.Date, nullable=False)
    endDate = db.Column("validade", db.Date, nullable=False)
    schema = db.Column("schema", db.String, nullable=False)

    def getNotification(schema):
        n = (
            Notify.query.filter(Notify.startDate <= date.today())
            .filter(Notify.endDate >= date.today())
            .filter(or_(Notify.schema == schema, Notify.schema == None))
            .order_by(asc(Notify.id))
            .first()
        )
        return (
            {
                "id": n.id,
                "title": n.title,
                "tooltip": n.tooltip,
                "link": n.link,
                "icon": n.icon,
                "classname": n.classname,
            }
            if n
            else None
        )


class Drug(db.Model):
    __tablename__ = "medicamento"

    id = db.Column("fkmedicamento", db.BigInteger, primary_key=True)
    idHospital = db.Column("fkhospital", db.BigInteger, nullable=False)
    name = db.Column("nome", db.String, nullable=False)
    sctid = db.Column("sctid", db.BigInteger, nullable=True)
    ai_accuracy = db.Column("ia_acuracia", db.Float, nullable=True)
    source = db.Column("origem", db.String, nullable=True)
    created_by = db.Column("created_by", db.BigInteger, nullable=True)
    updated_by = db.Column("updated_by", db.BigInteger, nullable=True)
    created_at = db.Column("created_at", db.DateTime, nullable=False)
    updated_at = db.Column("updated_at", db.DateTime, nullable=True)


class DrugAttributesBase:
    idDrug = db.Column("fkmedicamento", db.BigInteger, primary_key=True)
    idSegment = db.Column("idsegmento", db.BigInteger, primary_key=True)
    antimicro = db.Column("antimicro", db.Boolean, nullable=True)
    mav = db.Column("mav", db.Boolean, nullable=True)
    controlled = db.Column("controlados", db.Boolean, nullable=True)
    notdefault = db.Column("naopadronizado", db.Boolean, nullable=True)
    maxDose = db.Column("dosemaxima", db.Float, nullable=True)
    kidney = db.Column("renal", db.Integer, nullable=True)
    liver = db.Column("hepatico", db.Integer, nullable=True)
    platelets = db.Column("plaquetas", db.Integer, nullable=True)
    elderly = db.Column("idoso", db.Boolean, nullable=True)
    tube = db.Column("sonda", db.Boolean, nullable=True)
    division = db.Column("divisor", db.Float, nullable=True)
    useWeight = db.Column("usapeso", db.Boolean, nullable=True)
    idMeasureUnit = db.Column("fkunidademedida", db.String, nullable=True)
    idMeasureUnitPrice = db.Column("fkunidademedidacusto", db.String, nullable=True)
    amount = db.Column("concentracao", db.Float, nullable=True)
    amountUnit = db.Column("concentracaounidade", db.String(3), nullable=True)
    whiteList = db.Column("linhabranca", db.Boolean, nullable=True)
    chemo = db.Column("quimio", db.Boolean, nullable=True)
    price = db.Column("custo", db.Float, nullable=True)
    maxTime = db.Column("tempotratamento", db.Integer, nullable=True)
    fallRisk = db.Column("risco_queda", db.Integer, nullable=True)
    dialyzable = db.Column("dialisavel", db.Boolean, nullable=True)
    pregnant = db.Column("gestante", db.String, nullable=True)
    lactating = db.Column("lactante", db.String, nullable=True)
    fasting = db.Column("jejum", db.Boolean, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.BigInteger, nullable=True)
    ref_maxdose = db.Column("ref_dosemaxima", db.Float, nullable=True)
    ref_maxdose_weight = db.Column("ref_dosemaxima_peso", db.Float, nullable=True)


class DrugAttributes(db.Model, DrugAttributesBase):
    __tablename__ = "medatributos"


class DrugAttributesAudit(db.Model):
    __tablename__ = "medatributos_audit"

    id = db.Column(
        "idmedatributos_audit", db.BigInteger, nullable=False, primary_key=True
    )
    auditType = db.Column("tp_audit", db.Integer, nullable=False)
    idDrug = db.Column("fkmedicamento", db.BigInteger, nullable=False)
    idSegment = db.Column("idsegmento", db.BigInteger, nullable=True)
    extra = db.Column("extra", postgresql.JSON, nullable=True)
    createdAt = db.Column("created_at", db.DateTime, nullable=False)
    createdBy = db.Column("created_by", db.BigInteger, nullable=False)


class Allergy(db.Model):
    __tablename__ = "alergia"

    idDrug = db.Column("fkmedicamento", db.BigInteger, primary_key=True)
    idPatient = db.Column("fkpessoa", db.BigInteger, primary_key=True)
    drugName = db.Column("nome_medicamento", db.String, nullable=True)
    active = db.Column("ativo", db.Boolean, nullable=False)
    createdAt = db.Column("created_at", db.DateTime, nullable=True)


class Outlier(db.Model):
    __tablename__ = "outlier"

    id = db.Column("idoutlier", db.BigInteger, primary_key=True)
    idDrug = db.Column("fkmedicamento", db.BigInteger, nullable=False)
    idSegment = db.Column("idsegmento", db.BigInteger, nullable=False)
    countNum = db.Column("contagem", db.Integer, nullable=True)
    dose = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    score = db.Column("escore", db.Integer, nullable=True)
    manualScore = db.Column("escoremanual", db.Integer, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.BigInteger, nullable=True)


class PrescriptionAgg(db.Model):
    __tablename__ = "prescricaoagg"

    idHospital = db.Column("fkhospital", db.BigInteger, nullable=False)
    idDepartment = db.Column("fksetor", db.BigInteger, primary_key=True)
    idSegment = db.Column("idsegmento", db.BigInteger, nullable=False)
    idDrug = db.Column("fkmedicamento", db.BigInteger, primary_key=True)
    idMeasureUnit = db.Column("fkunidademedida", db.String, nullable=False)
    idFrequency = db.Column("fkfrequencia", db.String, primary_key=True)
    dose = db.Column("dose", db.Float, primary_key=True)
    doseconv = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    countNum = db.Column("contagem", db.Integer, nullable=True)
