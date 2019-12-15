DROP SCHEMA demo CASCADE;
DROP TABLE IF EXISTS public.usuario;
CREATE SCHEMA demo;
GRANT ALL ON SCHEMA demo TO postgres;
GRANT ALL ON SCHEMA demo TO demo;


CREATE TABLE demo."exame" (
  "fkexame" bigint NOT NULL,
  "fkpessoa" bigint NOT NULL,
  "nratendimento" bigint NOT NULL,
  "dtexame" timestamp NOT NULL,
  "tpexame" varchar(100) NOT NULL,
  "valor" float NOT NULL,
  "unidade" varchar(250) DEFAULT NULL
);

CREATE TABLE demo."intervencao" (
  "idintervencao" SERIAL PRIMARY KEY NOT NULL,
  "idpresmed" bigint NOT NULL,
  "idusuario" smallint NOT NULL,
  "idmotivointervencao" smallint NOT NULL,
  "dtintervencao" timestamp NOT NULL DEFAULT 'now()',
  "boolpropaga" char(1) NOT NULL DEFAULT 'n',
  "observacao" text
);

CREATE TABLE demo."outlier" (
  "fkmedicamento" integer NOT NULL,
  "idoutlier" SERIAL PRIMARY KEY NOT NULL,
  "idsegmento" smallint DEFAULT NULL,
  "contagem" integer DEFAULT NULL,
  "dose" float DEFAULT NULL,
  "frequenciadia" smallint DEFAULT NULL,
  "escore" smallint DEFAULT NULL,
  "escoremanual" smallint DEFAULT NULL,
  "idusuario" smallint DEFAULT NULL
);

CREATE TABLE demo."pessoa" (
  "fkhospital" smallint DEFAULT 1,
  "fkpessoa" bigint PRIMARY KEY NOT NULL,
  "nratendimento" bigint UNIQUE NOT NULL,
  "dtnascimento" date NOT NULL,
  "dtinternacao" timestamp NOT NULL,
  "cor" varchar(100) DEFAULT NULL,
  "sexo" char(1) DEFAULT NULL,
  "peso" float DEFAULT NULL
);

CREATE TABLE demo."nome" (
  "fkpessoa" bigint PRIMARY KEY NOT NULL,
  "nome" varchar(255) NOT NULL
);

CREATE TABLE demo."prescricao" (
  "fkhospital" smallint DEFAULT 1,
  "fksetor" smallint NOT NULL,
  "fkprescricao" bigint PRIMARY KEY NOT NULL,
  "fkpessoa" bigint NOT NULL,
  "idsegmento" smallint DEFAULT NULL,
  "dtprescricao" timestamp NOT NULL,
  "status" char(1) DEFAULT '0'
);

CREATE TABLE demo."prescricaoagg" (
  "fkhospital" smallint DEFAULT 1,
  "fksetor" smallint NOT NULL,
  "idsegmento" smallint NOT NULL,
  "fkmedicamento" bigint NOT NULL,
  "fkunidademedida" varchar(10) DEFAULT NULL,
  "fkfrequencia" integer DEFAULT NULL,
  "dose" float DEFAULT NULL,
  "frequenciadia" smallint DEFAULT NULL,
  "contagem" integer DEFAULT NULL
);

CREATE TABLE demo."presmed" (
  "idpresmed" SERIAL PRIMARY KEY NOT NULL,
  "fkprescricao" bigint NOT NULL,
  "fkmedicamento" integer NOT NULL,
  "fkunidademedida" varchar(10) DEFAULT NULL,
  "fkfrequencia" integer DEFAULT NULL,
  "idsegmento" smallint DEFAULT NULL,
  "idoutlier" integer DEFAULT NULL,
  "dose" float DEFAULT NULL,
  "frequenciadia" smallint DEFAULT NULL,
  "via" varchar(50) DEFAULT NULL,
  "complemento" text,
  "quantidade" integer DEFAULT NULL,
  "escorefinal" smallint DEFAULT NULL
);

CREATE TABLE demo."medicamento" (
  "fkhospital" smallint DEFAULT 1,
  "fkmedicamento" bigint PRIMARY KEY NOT NULL,
  "fkunidademedida" varchar(10) DEFAULT NULL,
  "nome" varchar(250) NOT NULL
);

CREATE TABLE demo."motivointervencao" (
  "fkhospital" smallint DEFAULT 1,
  "idmotivointervencao" SERIAL PRIMARY KEY NOT NULL,
  "nome" varchar(250) NOT NULL,
  "tipo" varchar(50) NOT NULL
);

CREATE TABLE demo."frequencia" (
  "fkhospital" smallint DEFAULT 1,
  "fkfrequencia" integer PRIMARY KEY NOT NULL,
  "nome" varchar(250) NOT NULL,
  "frequenciadia" smallint DEFAULT NULL,
  "frequenciahora" smallint DEFAULT NULL
);

CREATE TABLE demo."unidademedida" (
  "fkhospital" smallint DEFAULT 1,
  "fkunidademedida" varchar(10) PRIMARY KEY NOT NULL,
  "nome" varchar(250) NOT NULL
);

CREATE TABLE demo."unidadeconverte" (
  "fkhospital" smallint DEFAULT 1,
  "fkunidademedidade" varchar(10) NOT NULL,
  "fkunidademedidapara" varchar(10) NOT NULL,
  "fator" float NOT NULL
);

CREATE TABLE demo."segmento" (
  "idsegmento" SERIAL PRIMARY KEY NOT NULL,
  "nome" varchar(250) NOT NULL,
  "idade_min" smallint DEFAULT NULL,
  "idade_max" smallint DEFAULT NULL,
  "peso_min" smallint DEFAULT NULL,
  "peso_max" smallint DEFAULT NULL,
  "status" smallint DEFAULT NULL
);

CREATE TABLE demo."segmentosetor" (
  "idsegmento" smallint NOT NULL,
  "fkhospital" smallint NOT NULL,
  "fksetor" smallint NOT NULL
);

CREATE TABLE demo."hospital" (
  "fkhospital" smallint UNIQUE PRIMARY KEY NOT NULL,
  "nome" varchar(255) NOT NULL
);

CREATE TABLE demo."setor" (
  "fkhospital" smallint DEFAULT 1,
  "fksetor" smallint PRIMARY KEY NOT NULL,
  "nome" varchar(255) NOT NULL
);

CREATE TABLE public."usuario" (
  "idusuario" SERIAL PRIMARY KEY NOT NULL,
  "nome" varchar(255) NOT NULL,
  "email" varchar(255) UNIQUE NOT NULL,
  "senha" varchar(255) NOT NULL,
  "schema" varchar(10) NOT NULL,
  "getnameurl" varchar(255) DEFAULT NULL,
  "logourl" varchar(255) DEFAULT NULL
);

ALTER TABLE demo."intervencao" ADD FOREIGN KEY ("idpresmed") REFERENCES demo."presmed" ("idpresmed");

ALTER TABLE demo."intervencao" ADD FOREIGN KEY ("idmotivointervencao") REFERENCES demo."motivointervencao" ("idmotivointervencao");

CREATE INDEX ON demo."exame" ("fkpessoa", "nratendimento");

CREATE UNIQUE INDEX ON demo."outlier" ("fkmedicamento", "idsegmento", "dose", "frequenciadia");

CREATE UNIQUE INDEX ON demo."prescricao" ("fksetor", "fkprescricao");

CREATE UNIQUE INDEX ON demo."prescricaoagg" ("fksetor", "fkmedicamento", "dose", "fkfrequencia");

CREATE UNIQUE INDEX ON demo."presmed" ("fkprescricao", "fkmedicamento", "dose", "fkfrequencia");

CREATE UNIQUE INDEX ON demo."medicamento" ("fkhospital", "fkmedicamento");

CREATE UNIQUE INDEX ON demo."frequencia" ("fkhospital", "fkfrequencia");

CREATE UNIQUE INDEX ON demo."unidademedida" ("fkhospital", "fkunidademedida");

CREATE UNIQUE INDEX ON demo."setor" ("fkhospital", "fksetor");