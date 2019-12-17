CREATE FUNCTION demo.complete_presmed()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$BEGIN
    -- NEW.frequenciadia := por fkfrequencia
    NEW.idoutlier := (
        SELECT o.idoutlier FROM demo.outlier o WHERE 
        o.fkmedicamento = NEW.fkmedicamento AND
        o.dose = NEW.dose AND
        o.frequenciadia = NEW.frequenciadia
    );
    -- NEW.idsegmento := por fksetor + fkhospital
    RETURN NEW;
END;$BODY$;

ALTER FUNCTION demo.complete_presmed()
    OWNER TO postgres;


CREATE TRIGGER complete_presmed
    BEFORE INSERT OR UPDATE 
    ON demo.presmed
    FOR EACH ROW
    EXECUTE PROCEDURE demo.complete_presmed();

/*
CREATE TRIGGER popula_prescricaoagg_by_segmento
    AFTER INSERT OR UPDATE 
    ON demo.segmentosetor
    FOR EACH ROW
    EXECUTE PROCEDURE demo.popula_prescricaoagg_by_segmento();

CREATE TRIGGER complete_prescricao -- presmed.escorefinal, idsegmento
    BEFORE INSERT OR UPDATE 
    ON demo.prescricao
    FOR EACH ROW
    EXECUTE PROCEDURE demo.complete_prescricao();

CREATE TRIGGER complete_prescricaoagg -- idsegmento, frequenciadia
    BEFORE INSERT OR UPDATE 
    ON demo.prescricaoagg
    FOR EACH ROW
    EXECUTE PROCEDURE demo.complete_prescricaoagg();

CREATE TRIGGER popula_presmed_by_outlier
    AFTER INSERT OR UPDATE 
    ON demo.outlier
    FOR EACH ROW
    EXECUTE PROCEDURE demo.popula_predmed_by_outlier();

CREATE TRIGGER popula_presmed_by_frequencia
    AFTER INSERT OR UPDATE 
    ON demo.frequencia
    FOR EACH ROW
    EXECUTE PROCEDURE demo.popula_presmed_by_frequencia();

CREATE TRIGGER complete_frequencia -- frequenciadia
    BEFORE INSERT OR UPDATE 
    ON demo.frequencia
    FOR EACH ROW
    EXECUTE PROCEDURE demo.complete_frequencia();
*/