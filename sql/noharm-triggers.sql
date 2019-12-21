-------------------------------------
-------- UPDATE SELF TABLES --------
-------------------------------------

CREATE FUNCTION demo.complete_presmed()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$BEGIN
    NEW.frequenciadia := (
        SELECT f.frequenciadia FROM demo.frequencia f
        WHERE f.fkfrequencia = NEW.fkfrequencia
    );
    NEW.idoutlier := (
        SELECT MAX(o.idoutlier) FROM demo.outlier o 
        WHERE o.fkmedicamento = NEW.fkmedicamento
        AND o.dose = NEW.dose
        AND o.frequenciadia = NEW.frequenciadia
        AND o.idsegmento = NEW.idsegmento
    );
    NEW.idsegmento = (
        SELECT p.idsegmento FROM demo.prescricao p
        WHERE p.fkprescricao = NEW.fkprescricao
    );
    RETURN NEW;
END;$BODY$;

ALTER FUNCTION demo.complete_presmed()
    OWNER TO postgres;

CREATE TRIGGER trg_complete_presmed
    BEFORE INSERT 
    ON demo.presmed
    FOR EACH ROW
    EXECUTE PROCEDURE demo.complete_presmed();

--------

CREATE FUNCTION demo.complete_prescricao()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$BEGIN
    IF NEW.status = 'S' THEN
        UPDATE demo.presmed pm
        SET pm.escorefinal = (SELECT COALESCE(escoremanual, escore) 
                                FROM demo.outlier o
                                WHERE o.idoutlier = pm.idoutlier);
    END IF;
    NEW.idsegmento = (
        SELECT s.idsegmento FROM demo.segmentosetor s
        WHERE s.fksetor = NEW.fksetor
        AND s.fkhospital = NEW.fkhospital
    );
    RETURN NEW;
END;$BODY$;

ALTER FUNCTION demo.complete_prescricao()
    OWNER TO postgres;

CREATE TRIGGER trg_complete_prescricao
    BEFORE INSERT 
    ON demo.prescricao
    FOR EACH ROW
    EXECUTE PROCEDURE demo.complete_prescricao();

--------

CREATE FUNCTION demo.complete_prescricaoagg()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$BEGIN
    NEW.frequenciadia := (
        SELECT f.frequenciadia FROM demo.frequencia f
        WHERE f.fkfrequencia = NEW.fkfrequencia
    );
    NEW.idsegmento = (
        SELECT s.idsegmento FROM demo.segmentosetor s
        WHERE s.fksetor = NEW.fksetor
        AND s.fkhospital = NEW.fkhospital
    );
    RETURN NEW;
END;$BODY$;

ALTER FUNCTION demo.complete_prescricaoagg()
    OWNER TO postgres;

CREATE TRIGGER trg_complete_prescricaoagg
    BEFORE INSERT 
    ON demo.prescricaoagg
    FOR EACH ROW
    EXECUTE PROCEDURE demo.complete_prescricaoagg();

--------

CREATE FUNCTION demo.complete_frequencia()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$BEGIN
    NEW.frequenciadia := 24 / NEW.frequenciahora;
    RETURN NEW;
END;$BODY$;

ALTER FUNCTION demo.complete_frequencia()
    OWNER TO postgres;

CREATE TRIGGER trg_complete_frequencia
    BEFORE INSERT 
    ON demo.frequencia
    FOR EACH ROW
    EXECUTE PROCEDURE demo.complete_frequencia();

-------------------------------------
-------- UPDATE CHILD TABLES --------
-------------------------------------

CREATE FUNCTION demo.popula_presmed_by_outlier()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$BEGIN
    UPDATE demo.presmed pm
        SET idoutlier = (
            SELECT MAX(o.idoutlier) FROM demo.outlier o 
            WHERE o.fkmedicamento = pm.fkmedicamento
            AND o.dose = pm.dose
            AND o.frequenciadia = pm.frequenciadia
            AND o.idsegmento = pm.idsegmento
        )
    WHERE escorefinal IS NULL;
    RETURN NULL;
END;$BODY$;

ALTER FUNCTION demo.popula_presmed_by_outlier()
    OWNER TO postgres;

CREATE TRIGGER trg_popula_presmed_by_outlier
    AFTER INSERT 
    ON demo.outlier
    FOR EACH ROW
    EXECUTE PROCEDURE demo.popula_presmed_by_outlier();

--------

CREATE FUNCTION demo.popula_presmed_by_frequencia()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$BEGIN
    UPDATE demo.presmed pm
        SET pm.frequenciadia = (
            SELECT f.frequenciadia FROM demo.frequencia f 
            WHERE o.fkfrequencia = pm.fkfrequencia
        )
    WHERE pm.escorefinal IS NULL;
    RETURN NULL;
END;$BODY$;

ALTER FUNCTION demo.popula_presmed_by_frequencia()
    OWNER TO postgres;

CREATE TRIGGER trg_popula_presmed_by_frequencia
    AFTER INSERT 
    ON demo.frequencia
    FOR EACH ROW
    EXECUTE PROCEDURE demo.popula_presmed_by_frequencia();

--------

CREATE FUNCTION demo.popula_prescricaoagg_by_segmento()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$BEGIN
    UPDATE demo.presmed pm
        SET pm.idsegmento = (
            SELECT s.idsegmento FROM demo.segmentosetor s
            WHERE s.fksetor = pm.fksetor
            AND s.fkhospital = pm.fkhospital
        )
    WHERE pm.escorefinal IS NULL;
    UPDATE demo.prescricao p
        SET p.idsegmento = (
            SELECT s.idsegmento FROM demo.segmentosetor s
            WHERE s.fksetor = p.fksetor
            AND s.fkhospital = p.fkhospital
        )
    WHERE p.status IS NULL;
    UPDATE demo.prescricaoagg pa
        SET pa.idsegmento = (
            SELECT s.idsegmento FROM demo.segmentosetor s
            WHERE s.fksetor = pa.fksetor
            AND s.fkhospital = pa.fkhospital
        );
    RETURN NULL;
END;$BODY$;

ALTER FUNCTION demo.popula_prescricaoagg_by_segmento()
    OWNER TO postgres;

CREATE TRIGGER trg_popula_prescricaoagg_by_segmento
    AFTER INSERT OR UPDATE 
    ON demo.segmentosetor
    FOR EACH ROW
    EXECUTE PROCEDURE demo.popula_prescricaoagg_by_segmento();