// source at: https://dbdiagram.io/d/5df2c8b4edf08a25543f089e

// ######## prescription's Tables ######## //

Table "exame"  [headercolor: #16a085] {
  "fkexame" bigint [not null]
  "fkpessoa" bigint [not null]
  "nratendimento" bigint [not null]
  "dtexame" timestamp [not null]
  "tpexame" varchar(100) [not null]
  "valor" float [not null]
  "unidade" varchar(250) [default: NULL]
  
  indexes {
    (fkpessoa, nratendimento)
  }
  
}

Table "intervencao"  [headercolor: #16a085] {
  "idintervencao" integer [pk, not null, increment]
  "idpresmed" bigint [not null, ref: > presmed.idpresmed]
  "idusuario" smallint [not null]
  "idmotivointervencao" smallint [not null, ref: > motivointervencao.idmotivointervencao]
  "dtintervencao" timestamp [not null, default: 'now()']
  "boolpropaga" char(1) [not null, default: "n"]
  "observacao" text
}

Table "outlier"  [headercolor: #16a085] {
  "fkmedicamento" integer [not null]
  "idoutlier" integer [pk, not null, increment]
  "idsegmento" smallint [default: NULL]
  "contagem" integer [default: NULL]
  "dose" float [default: NULL]
  "frequenciadia" smallint [default: NULL]
  "escore" smallint [default: NULL]
  "escoremanual" smallint [default: NULL]
  "idusuario" smallint [default: NULL]
  
  indexes {
    (fkmedicamento, idsegmento, dose, frequenciadia) [unique]
  }
  
}

Table "pessoa"  [headercolor: #16a085] {
  "fkhospital" smallint [default: 1]
  "fkpessoa" bigint [pk, not null]
  "nratendimento" bigint [not null, unique]
  "dtnascimento" date [not null]
  "dtinternacao" timestamp [not null]
  "cor" varchar(100) [default: NULL]
  "sexo" char(1) [default: NULL]
  "peso" float [default: NULL]
}


// dummy Table to simulate person name
Table "nome"  [headercolor: #16a085] {
  "fkpessoa" bigint [pk, not null]
  "nome" varchar(255) [not null]
}


Table "prescricao"  [headercolor: #16a085] {
  "fkhospital" smallint [default: 1]
  "fksetor" smallint [not null]
  "fkprescricao" bigint [pk, not null]
  "fkpessoa" bigint [not null]
  "idsegmento" smallint [default: NULL]
  "dtprescricao" timestamp [not null]
  "status" char(1) [default: "0"]
  
  indexes {
    (fksetor, fkprescricao) [unique]
  }
}

Table "prescricaoagg"  [headercolor: #16a085] {
  "fkhospital" smallint [default: 1]
  "fksetor" smallint [not null]
  "fkmedicamento" bigint [not null]
  "fkunidademedida" varchar(10) [default: NULL]
  "fkfrequencia" integer [default: NULL]
  "dose" float [default: NULL]
  "frequenciadia" smallint [default: NULL]
  "contagem" integer [default: NULL]
  
  indexes {
    (fksetor, fkmedicamento, dose, fkfrequencia) [unique]
  }
  
}

Table "presmed"  [headercolor: #16a085] {
  "idpresmed" bigint [pk, not null, increment]
  "fkprescricao" bigint [not null]
  "fkmedicamento" integer [not null]
  "fkunidademedida" varchar(10) [default: NULL]
  "fkfrequencia" integer [default: NULL]
  "idsegmento" smallint [default: NULL]
  "idoutlier" integer [default: NULL]
  "dose" float [default: NULL]
  "frequenciadia" smallint [default: NULL]
  "via" varchar(50) [default: NULL]
  "complemento" text
  "quantidade" integer [default: NULL]
  "escorefinal" smallint [default: NULL]
  
  indexes {
    (fkprescricao, fkmedicamento, dose, fkfrequencia) [unique]
  }
}

// ######## support's Tables ######## //

Table "medicamento"  [headercolor: #3498db] {
  "fkhospital" smallint [default: 1]
  "fkmedicamento" bigint [pk, not null]
  "fkunidademedida" varchar(10) [default: NULL]
  "nome" varchar(250) [not null]
  
  indexes {
    (fkhospital, fkmedicamento) [unique]
  }
  
}

Table "motivointervencao"  [headercolor: #3498db] {
  "fkhospital" smallint [default: 1]
  "idmotivointervencao" smallint [pk, not null, increment]
  "nome" varchar(250) [not null]
  "tipo" varchar(50) [not null]
}

Table "frequencia"  [headercolor: #3498db] {
  "fkhospital" smallint [default: 1]
  "fkfrequencia" integer [pk, not null]
  "nome" varchar(250) [not null]
  "frequenciadia" smallint [default: NULL]
  "frequenciahora" smallint [default: NULL]
  
  indexes {
    (fkhospital, fkfrequencia) [unique]
  }
  
}

Table "unidademedida"  [headercolor: #3498db] {
  "fkhospital" smallint [default: 1]
  "fkunidademedida" varchar(10) [pk, not null]
  "nome" varchar(250) [not null]
  
  indexes {
    (fkhospital, fkunidademedida) [unique]
  }
  
}

Table "unidadeconverte"  [headercolor: #3498db] {
  "fkhospital" smallint [default: 1]
  "fkunidademedidade" varchar(10) [not null]
  "fkunidademedidapara" varchar(10) [not null]
  "fator" float [not null]
}

Table "segmento"  [headercolor: #3498db] {
  "idsegmento" smallint [pk, not null, increment]
  "nome" varchar(250) [not null]
  "idade_min" smallint [default: NULL]
  "idade_max" smallint [default: NULL]
  "peso_min" smallint [default: NULL]
  "peso_max" smallint [default: NULL]
  "status" smallint [default: NULL]
}

Table "segmentosetor"  [headercolor: #3498db] {
  "idsegmento" smallint [not null]
  "fkhospital" smallint [not null]
  "fksetor" smallint [not null]
}

Table "hospital"  [headercolor: #3498db] {
  "fkhospital" smallint [pk, not null, unique]
  "nome" varchar(255) [not null]
}

Table "setor"  [headercolor: #3498db] {
  "fkhospital" smallint [default: 1]
  "fksetor" smallint [pk, not null]
  "nome" varchar(255) [not null]
  
  indexes {
    (fkhospital, fksetor) [unique]
  }
  
}

Table "usuario"  [headercolor: #3498db] {
  "idusuario" smallint [pk, not null, increment]
  "nome" varchar(255) [not null, unique]
  "email" varchar(255) [not null, unique]
  "senha" varchar(255) [not null]
  "schema" varchar(10) [not null]
  "getnameurl" varchar(255) [default: NULL]
  "logourl" varchar(255) [default: NULL]
}

