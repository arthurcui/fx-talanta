-- A restored account is unusable until its complete archive has been verified and
-- an administrator explicitly attests that the source writer has been retired.
CREATE TABLE fx.restore_history (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    archive_id uuid NOT NULL,
    manifest_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('STAGED', 'RESTORED', 'RELEASED')),
    source_history jsonb NOT NULL DEFAULT '[]',
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER restore_history_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON fx.restore_history
    FOR EACH STATEMENT EXECUTE FUNCTION fx.no_mutation();

CREATE FUNCTION fx.guard_restored_writes() RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, fx AS $$
DECLARE latest text;
BEGIN
    SELECT status INTO latest FROM fx.restore_history ORDER BY sequence DESC LIMIT 1;
    -- Schema owner performs the verified import; runtime identities may not.
    IF latest IS NOT NULL AND latest <> 'RELEASED' AND current_user <>
       (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='fx') THEN
        RAISE EXCEPTION 'restored account awaits archive verification and writer handoff'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER restore_records_guard BEFORE INSERT ON fx.records
    FOR EACH ROW EXECUTE FUNCTION fx.guard_restored_writes();
CREATE TRIGGER restore_offline_guard BEFORE INSERT ON fx.offline_journal
    FOR EACH ROW EXECUTE FUNCTION fx.guard_restored_writes();
REVOKE ALL ON FUNCTION fx.guard_restored_writes() FROM PUBLIC;
