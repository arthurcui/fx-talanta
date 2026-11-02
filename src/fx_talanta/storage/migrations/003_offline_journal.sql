-- Durable, independently committed gateway and simulator snapshots. Each simulator
-- run is a separate research ledger, never a real broker account or live activation.
CREATE TABLE fx.offline_journal (
    run_id uuid NOT NULL,
    stream text NOT NULL CHECK (stream IN ('gateway','broker')),
    revision bigint NOT NULL CHECK (revision > 0),
    recorded_at timestamptz NOT NULL,
    event text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (run_id, stream, revision)
);
CREATE TRIGGER offline_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON fx.offline_journal
    FOR EACH STATEMENT EXECUTE FUNCTION fx.no_mutation();

CREATE FUNCTION fx.validate_offline() RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, fx AS $$
DECLARE binding jsonb;
BEGIN
    SELECT identity INTO STRICT binding FROM fx.account_binding;
    IF binding->>'environment' <> 'PAPER' OR binding->>'venue' <> 'SIMULATOR' OR
       NEW.payload->'account' IS DISTINCT FROM binding THEN
        RAISE EXCEPTION 'offline journal requires the bound PAPER simulator' USING ERRCODE='23514';
    END IF;
    IF NEW.revision <> COALESCE((SELECT max(revision) FROM fx.offline_journal
        WHERE run_id=NEW.run_id AND stream=NEW.stream), 0) + 1 THEN
        RAISE EXCEPTION 'offline journal revision conflict' USING ERRCODE='23514';
    END IF;
    IF NEW.recorded_at < (SELECT max(recorded_at) FROM fx.offline_journal
        WHERE run_id=NEW.run_id) THEN
        RAISE EXCEPTION 'offline clock moved backwards' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER validate_offline BEFORE INSERT ON fx.offline_journal
    FOR EACH ROW EXECUTE FUNCTION fx.validate_offline();
REVOKE ALL ON FUNCTION fx.validate_offline() FROM PUBLIC;

-- Preserve existing M0A provenance while labeling actual offline execution separately.
DO $$
DECLARE constraint_name text;
BEGIN
    FOR constraint_name IN SELECT conname FROM pg_constraint
        WHERE conrelid='fx.records'::regclass AND contype='c'
          AND pg_get_constraintdef(oid) LIKE '%provenance%'
    LOOP
        EXECUTE format('ALTER TABLE fx.records DROP CONSTRAINT %I', constraint_name);
    END LOOP;
END
$$;
ALTER TABLE fx.records ADD CONSTRAINT record_provenance CHECK (
    payload->>'provenance' IS NOT NULL AND
    payload->>'provenance' IN ('SCRIPTED_FIXTURE', 'OFFLINE_SIMULATION')
);
