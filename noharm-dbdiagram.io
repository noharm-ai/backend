// https://dbdiagram.io/d/5df2c8b4edf08a25543f089e

Table "Exame"  [headercolor: #16a085] {
  "fkHospital" integer [default: 1]
  "fkExame" bigint [pk, not null]
  "fkPessoa" bigint [not null]
  "nrAtendimento" bigint [not null]
  "dtExame" timestamp [not null]
  "tpExame" varchar(100) [not null]
  "valor" float [not null]
  "unidade" varchar(250) [default: NULL]
}

Table "Intervencao"  [headercolor: #16a085] {
  "fkHospital" integer [default: 1]
  "idIntervencao" integer [pk, not null]
  "idPresMed" bigint [not null, ref: > PresMed.idPresMed]
  "idUsuario" integer [not null]
  "idMotivoIntervencao" integer [not null, ref: > MotivoIntervencao.idMotivoIntervencao]
  "boolPropaga" char(1) [not null, default: "N"]
  "observacao" text
}

Table "Medicamento"  [headercolor: #3498db] {
  "fkHospital" integer [default: 1]
  "fkMedicamento" bigint [pk, not null]
  "fkUnidadeMedida" varchar(10) [default: NULL]
  "nome" varchar(250) [not null]
}

Table "MotivoIntervencao"  [headercolor: #3498db] {
  "fkHospital" integer [default: 1]
  "idMotivoIntervencao" integer [pk, not null]
  "nome" varchar(250) [not null]
  "tipo" varchar(50) [not null]
}

Table "Outlier"  [headercolor: #16a085] {
  "fkHospital" integer [default: 1]
  "fkMedicamento" integer [not null]
  "idOutlier" bigint [pk, not null]
  "idSegmento" integer [default: NULL]
  "contagem" integer [default: NULL]
  "dose" float [default: NULL]
  "frequenciaDia" integer [default: NULL]
  "escore" integer [default: NULL]
  "escoremanual" integer [default: NULL]
}

Table "Pessoa"  [headercolor: #16a085] {
  "fkHospital" integer [default: 1]
  "fkPessoa" bigint [pk, not null]
  "nrAtendimento" bigint [not null]
  "dtNascimento" date [not null]
  "dtInternacao" timestamp [not null]
  "cor" varchar(100) [default: NULL]
  "sexo" char(1) [default: NULL]
  "peso" float [default: NULL]
}

Table "Prescricao"  [headercolor: #16a085] {
  "fkHospital" integer [default: 1]
  "fkSetor" integer [not null]
  "fkPrescricao" bigint [pk, not null]
  "fkPessoa" bigint [not null]
  "idSegmento" integer [default: NULL]
  "dtPrescricao" timestamp [not null]
  "status" char(1) [default: "0"]
}

Table "PrescricaoAgg"  [headercolor: #16a085] {
  "fkHospital" integer [default: 1]
  "fkSetor" integer [not null]
  "fkMedicamento" bigint [not null]
  "fkUnidadeMedida" varchar(10) [default: NULL]
  "fkFrequencia" integer [default: NULL]
  "dose" float [default: NULL]
  "frequenciaDia" integer [default: NULL]
}

Table "PresMed"  [headercolor: #16a085] {
  "idPresMed" bigint [pk, not null]
  "fkPrescricao" bigint [not null]
  "fkMedicamento" integer [not null]
  "fkUnidadeMedida" varchar(10) [default: NULL]
  "fkFrequencia" integer [default: NULL]
  "idSegmento" integer [default: NULL]
  "idOutlier" bigint [default: NULL]
  "dose" float [default: NULL]
  "frequenciaDia" integer [default: NULL]
  "via" varchar(50) [default: NULL]
  "complemento" text
  "quantidade" integer [default: NULL]
}

Table "Frequencia"  [headercolor: #3498db] {
  "fkHospital" integer [default: 1]
  "fkFrequencia" integer [pk, not null]
  "nome" varchar(250) [not null]
  "frequenciaDia" integer [default: NULL]
  "frequenciaHora" integer [default: NULL]
}

Table "UnidadeMedida"  [headercolor: #3498db] {
  "fkHospital" integer [default: 1]
  "fkUnidadeMedida" varchar(10) [pk, not null]
  "nome" varchar(250) [not null]
}

Table "UnidadeConverte"  [headercolor: #3498db] {
  "fkHospital" integer [default: 1]
  "fkUnidadeMedidaDe" integer [not null]
  "fkUnidadeMedidaPara" integer [not null]
  "fator" float [not null]
}

Table "Segmento"  [headercolor: #3498db] {
  "idSegmento" integer [pk, not null]
  "nome" varchar(250) [not null]
  "idade_min" integer [default: NULL]
  "idade_max" integer [default: NULL]
  "peso_min" float [default: NULL]
  "peso_max" float [default: NULL]
}

Table "SegmentoSetor"  [headercolor: #3498db] {
  "idSegmento" integer [not null]
  "fkHospital" integer [not null]
  "fkSetor" integer [not null]
}

Table "Hospital"  [headercolor: #3498db] {
  "fkHospital" integer [pk, not null]
  "nome" varchar(255) [not null]
}

Table "Setor"  [headercolor: #3498db] {
  "fkHospital" integer [default: 1]
  "fkSetor" integer [pk, not null]
  "nome" varchar(255) [not null]
}

Table "User"  [headercolor: #3498db] {
  "idUser" integer [pk, not null]
  "email" varchar(255) [not null]
  "password" varchar(255) [not null]
  "schema" varchar(255) [not null]
}