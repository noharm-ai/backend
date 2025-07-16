from sqlalchemy.dialects import postgresql

from .main import db


class Department(db.Model):
    __tablename__ = "setor"

    id = db.Column("fksetor", db.BigInteger, primary_key=True)
    idHospital = db.Column("fkhospital", db.BigInteger, primary_key=True)
    name = db.Column("nome", db.String, nullable=False)


class SegmentDepartment(db.Model):
    __tablename__ = "segmentosetor"

    id = db.Column("idsegmento", db.BigInteger, primary_key=True)
    idHospital = db.Column("fkhospital", db.BigInteger, primary_key=True)
    idDepartment = db.Column("fksetor", db.BigInteger, primary_key=True)


class MeasureUnit(db.Model):
    __tablename__ = "unidademedida"

    id = db.Column("fkunidademedida", db.String, primary_key=True)
    idHospital = db.Column("fkhospital", db.BigInteger, nullable=False)
    description = db.Column("nome", db.String, nullable=False)
    measureunit_nh = db.Column("unidademedida_nh", db.String, nullable=True)


class MeasureUnitConvert(db.Model):
    __tablename__ = "unidadeconverte"

    idMeasureUnit = db.Column("fkunidademedida", db.String, primary_key=True)
    idDrug = db.Column("fkmedicamento", db.BigInteger, primary_key=True)
    idSegment = db.Column("idsegmento", db.BigInteger, primary_key=True)
    factor = db.Column("fator", db.Float, nullable=False)


class InterventionReason(db.Model):
    __tablename__ = "motivointervencao"

    id = db.Column("idmotivointervencao", db.BigInteger, primary_key=True)
    idHospital = db.Column("fkhospital", db.BigInteger, nullable=False)
    description = db.Column("nome", db.String, nullable=False)
    mamy = db.Column("idmotivomae", db.BigInteger, nullable=False)
    active = db.Column("ativo", db.Boolean, nullable=False)
    suspension = db.Column("suspensao", db.Boolean, nullable=False)
    substitution = db.Column("substituicao", db.Boolean, nullable=False)
    customEconomy = db.Column("economia_customizada", db.Boolean, nullable=False)
    blocking = db.Column("bloqueante", db.Boolean, nullable=False)
    ram = db.Column("ram", db.Boolean, nullable=False)
    relation_type = db.Column("tp_relacao", db.BigInteger, nullable=False)


class Frequency(db.Model):
    __tablename__ = "frequencia"

    id = db.Column("fkfrequencia", db.String, primary_key=True)
    idHospital = db.Column("fkhospital", db.BigInteger, nullable=False)
    description = db.Column("nome", db.String, nullable=False)
    dailyFrequency = db.Column("frequenciadia", db.Float, nullable=True)
    fasting = db.Column("jejum", db.Boolean, nullable=True)


class Notes(db.Model):
    __tablename__ = "observacao"

    idOutlier = db.Column("idoutlier", db.BigInteger, primary_key=True)
    idPrescriptionDrug = db.Column("fkpresmed", db.BigInteger, primary_key=True)
    admissionNumber = db.Column("nratendimento", db.BigInteger, nullable=False)
    idSegment = db.Column("idsegmento", db.BigInteger, nullable=False)
    idDrug = db.Column("fkmedicamento", db.BigInteger, nullable=False)
    dose = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    notes = db.Column("text", db.String, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.BigInteger, nullable=True)


class Memory(db.Model):
    __tablename__ = "memoria"

    key = db.Column("idmemoria", db.BigInteger, primary_key=True, autoincrement=True)
    kind = db.Column("tipo", db.String(100), nullable=False)
    value = db.Column("valor", postgresql.JSON, nullable=False)
    update = db.Column("update_at", db.DateTime, nullable=False)
    user = db.Column("update_by", db.BigInteger, nullable=False)


class GlobalMemory(db.Model):
    __tablename__ = "memoria"
    __table_args__ = {"schema": "public"}

    key = db.Column("idmemoria", db.BigInteger, primary_key=True, autoincrement=True)
    kind = db.Column("tipo", db.String(100), nullable=False)
    value = db.Column("valor", postgresql.JSON, nullable=False)
    update = db.Column("update_at", db.DateTime, nullable=False)
    user = db.Column("update_by", db.BigInteger, nullable=False)


class SchemaConfig(db.Model):
    __tablename__ = "schema_config"
    __table_args__ = {"schema": "public"}

    schemaName = db.Column("schema_name", db.String, primary_key=True)
    createdAt = db.Column("created_at", db.Date, nullable=False)
    updatedAt = db.Column("updated_at", db.Date, nullable=True)
    updatedBy = db.Column("updated_by", db.BigInteger, nullable=True)
    config = db.Column("configuracao", postgresql.JSONB, nullable=True)
    status = db.Column("status", db.Integer, nullable=False)
    nh_care = db.Column("tp_noharm_care", db.Integer, nullable=False)
    cpoe = db.Column("cpoe", db.Boolean, nullable=False)
    return_integration = db.Column("integracao_retorno", db.Boolean, nullable=False)

    fl1 = db.Column("fl1_atualiza_indicadores_cpoe", db.Boolean, nullable=False)
    fl2 = db.Column("fl2_atualiza_indicadores_prescricao", db.Boolean, nullable=False)
    fl3 = db.Column("fl3_atualiza_prescricaoagg", db.Boolean, nullable=False)
    fl3_segments = db.Column(
        "fl3_segmentos", postgresql.ARRAY(db.BigInteger), nullable=True
    )
    fl4 = db.Column("fl4_cria_conciliacao", db.Boolean, nullable=False)


class SchemaConfigAudit(db.Model):
    """table schema_config_audit: audit record for schema_config changes"""

    __tablename__ = "schema_config_audit"
    __table_args__ = {"schema": "public"}

    id = db.Column("idschema_config_audit", db.BigInteger, primary_key=True)
    schemaName = db.Column("schema_name", db.String, nullable=False)
    auditType = db.Column("tp_audit", db.Integer, nullable=False)
    extra = db.Column("extra", postgresql.JSON, nullable=True)
    createdAt = db.Column("created_at", db.DateTime, nullable=False)
    createdBy = db.Column("created_by", db.BigInteger, nullable=False)


class CultureHeader(db.Model):
    __tablename__ = "cultura_cabecalho"

    id = db.Column("idculturacab", db.Integer, primary_key=True)
    idPatient = db.Column("fkpessoa", db.Integer, nullable=False)
    idDepartment = db.Column("fksetor", db.Integer, nullable=True)
    admissionNumber = db.Column("nratendimento", db.Integer, nullable=True)
    idExam = db.Column("fkexame", db.Integer, nullable=True)
    idExamItem = db.Column("fkitemexame", db.Integer, nullable=True)
    examName = db.Column("nomeexame", db.String, nullable=True)
    examMaterialName = db.Column("nomematerial", db.String, nullable=True)
    examMaterialTypeName = db.Column("nomematerialtipo", db.String, nullable=True)
    previousResult = db.Column("resultprevio", db.String, nullable=True)
    colony = db.Column("dscolonia", db.String, nullable=True)
    extraInfo = db.Column("complemento", db.String, nullable=True)
    gram = db.Column("gram", db.String, nullable=True)

    requestDate = db.Column("dtpedido", db.Date, nullable=True)
    collectionDate = db.Column("dtcoleta", db.Date, nullable=True)
    releaseDate = db.Column("dtliberacao", db.Date, nullable=True)


class Culture(db.Model):
    __tablename__ = "cultura"

    id = db.Column("idcultura", db.Integer, primary_key=True)
    idExam = db.Column("fkexame", db.Integer, nullable=True)
    idExamItem = db.Column("fkitemexame", db.Integer, nullable=True)
    idMicroorganism = db.Column("fkmicroorganismo", db.Integer, nullable=True)
    microorganism = db.Column("nomemicroorganismo", db.String, nullable=True)
    drug = db.Column("nomemedicamento", db.String, nullable=True)
    result = db.Column("resultado", db.String, nullable=True)
    microorganismAmount = db.Column("qtmicroorganismo", db.String, nullable=True)
    predict_proba = db.Column("predict_proba", db.Float, nullable=True)
    drug_proba = db.Column("medicamento_proba", db.Float, nullable=True)
    prediction = db.Column("predict", db.String, nullable=True)


class NifiQueue(db.Model):
    """SQLALCHEMY model for nifi_queue table"""

    __tablename__ = "nifi_queue"

    id = db.Column("idqueue", db.Integer, primary_key=True)
    url = db.Column("url", db.String, nullable=False)
    method = db.Column("method", db.String, nullable=False)
    body = db.Column("body", postgresql.JSONB, nullable=True)
    extra = db.Column("extra", postgresql.JSONB, nullable=True)
    runStatus = db.Column("run_status", db.Boolean, nullable=False)
    responseCode = db.Column("response_code", db.Integer, nullable=True)
    response = db.Column("response", postgresql.JSONB, nullable=True)
    responseAt = db.Column("response_at", db.Date, nullable=True)
    createdAt = db.Column("create_at", db.Date, nullable=False)
    createdBy = db.Column("created_by", db.Integer, nullable=True)


class Tag(db.Model):
    """SQLALCHEMY model for marcador table"""

    __tablename__ = "marcador"

    name = db.Column("nome", db.String, primary_key=True)
    tag_type = db.Column("tp_marcador", db.Integer, primary_key=True)
    active = db.Column("ativo", db.Boolean, nullable=False)
    updated_at = db.Column("updated_at", db.DateTime, nullable=False)
    updated_by = db.Column("updated_by", db.BigInteger, nullable=False)
    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.BigInteger, nullable=False)


class Protocol(db.Model):
    """SQLALCHEMY model for protocolo table"""

    __tablename__ = "protocolo"
    __table_args__ = {"schema": "public"}

    id = db.Column("idprotocolo", db.Integer, primary_key=True)
    schema = db.Column("schema_name", db.String, nullable=True)
    name = db.Column("nome", db.String, nullable=False)
    protocol_type = db.Column("tp_protocolo", db.Integer, nullable=False)
    status_type = db.Column("tp_situacao", db.Integer, nullable=False)
    config = db.Column("configuracao", postgresql.JSON, nullable=False)
    updated_at = db.Column("updated_at", db.DateTime, nullable=True)
    updated_by = db.Column("updated_by", db.BigInteger, nullable=True)
    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.BigInteger, nullable=False)


class ICDTable(db.Model):
    """International Classification of Diseases table"""

    __tablename__ = "tb_cid10"
    __table_args__ = {"schema": "public"}

    id_int = db.Column("co_cid10", db.Integer, primary_key=True)
    id_str = db.Column("nu_cid10", db.String, nullable=False)
    name = db.Column("no_cid10", db.String, nullable=False)
    status = db.Column("st_ativo", db.Integer, nullable=False)
