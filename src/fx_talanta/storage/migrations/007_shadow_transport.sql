-- Separate no-order evidence; never an execution or reservation ledger.
CREATE TABLE fx.shadow_events (
    stream uuid NOT NULL,
    seq bigint NOT NULL CHECK (seq > 0),
    scope text NOT NULL CHECK (scope ~ '^[0-9a-f]{64}$'),
    body text NOT NULL CHECK (octet_length(body) <= 131072),
    prior text NOT NULL CHECK (prior ~ '^[0-9a-f]{64}$'),
    hash text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (stream, seq)
);
CREATE TRIGGER shadow_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON fx.shadow_events
    FOR EACH STATEMENT EXECUTE FUNCTION fx.no_mutation();
CREATE FUNCTION fx.validate_shadow() RETURNS trigger LANGUAGE plpgsql
    SET search_path=pg_catalog,fx AS $$
DECLARE identity jsonb; enabled boolean;
BEGIN
    SELECT b.identity,b.execution_enabled INTO STRICT identity,enabled FROM fx.account_binding b;
    IF identity->>'environment' <> 'PAPER' OR enabled OR
       (NEW.body::jsonb)->>'execution_enabled' IS DISTINCT FROM 'false' THEN
        RAISE EXCEPTION 'shadow requires disabled PAPER binding' USING ERRCODE='23514';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.stream::text,0));
    IF NEW.seq <> COALESCE((SELECT max(seq) FROM fx.shadow_events WHERE stream=NEW.stream),0)+1 OR
       (NEW.seq>1 AND NEW.scope IS DISTINCT FROM (SELECT scope FROM fx.shadow_events WHERE stream=NEW.stream AND seq=1)) THEN
        RAISE EXCEPTION 'shadow sequence/scope conflict' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER validate_shadow BEFORE INSERT ON fx.shadow_events
    FOR EACH ROW EXECUTE FUNCTION fx.validate_shadow();
CREATE TRIGGER restore_shadow_guard BEFORE INSERT ON fx.shadow_events
    FOR EACH ROW EXECUTE FUNCTION fx.guard_restored_writes();
REVOKE ALL ON FUNCTION fx.validate_shadow() FROM PUBLIC;
