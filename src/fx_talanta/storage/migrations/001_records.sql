CREATE SCHEMA fx;
REVOKE ALL ON SCHEMA fx FROM PUBLIC;

CREATE TABLE fx.schema_migrations (
    version integer PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE fx.account_binding (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    identity jsonb NOT NULL,
    execution_enabled boolean NOT NULL DEFAULT false CHECK (NOT execution_enabled),
    CHECK (identity->>'environment' IN ('PAPER', 'LIVE')),
    CHECK ((identity->>'environment' = 'LIVE') = (identity->>'venue' = 'BROKER_LIVE'))
);

CREATE TABLE fx.records (
    sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    record_id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('decision','risk','execution','experience','lesson',
                                      'artifact','promotion','news','health','message','command')),
    recorded_at timestamptz NOT NULL,
    supersedes uuid REFERENCES fx.records(record_id),
    payload jsonb NOT NULL,
    CHECK (jsonb_typeof(payload) = 'object'),
    CHECK ((payload->>'record_id')::uuid IS NOT DISTINCT FROM record_id),
    CHECK (payload#>>'{body,kind}' IS NOT DISTINCT FROM kind),
    CHECK ((payload->>'recorded_at')::timestamptz IS NOT DISTINCT FROM recorded_at),
    CHECK ((payload->>'supersedes')::uuid IS NOT DISTINCT FROM supersedes),
    CHECK (payload->>'provenance' IS NOT DISTINCT FROM 'SCRIPTED_FIXTURE'),
    CHECK (jsonb_typeof(payload->'references') IS NOT DISTINCT FROM 'array'),
    CHECK (supersedes IS DISTINCT FROM record_id)
);

CREATE TABLE fx.record_links (
    source_id uuid NOT NULL REFERENCES fx.records(record_id),
    target_id uuid NOT NULL REFERENCES fx.records(record_id),
    relation text NOT NULL CHECK (relation IN
        ('NEWS','HEALTH','DECISION','EXECUTION','MESSAGE','ARTIFACT','CASE')),
    PRIMARY KEY (source_id, target_id, relation),
    CHECK (source_id <> target_id)
);

CREATE UNIQUE INDEX news_version_identity ON fx.records
    ((payload#>>'{body,source}'), (payload#>>'{body,item_id}'), (payload#>>'{body,revision}'))
    WHERE kind = 'news';
CREATE UNIQUE INDEX message_identity ON fx.records ((payload#>>'{body,message_id}'))
    WHERE kind = 'message';
CREATE UNIQUE INDEX command_request_identity ON fx.records ((payload#>>'{body,request_id}'))
    WHERE kind = 'command' AND supersedes IS NULL;
CREATE UNIQUE INDEX command_message_identity ON fx.records ((payload#>>'{body,message_id}'))
    WHERE kind = 'command' AND supersedes IS NULL;
CREATE UNIQUE INDEX single_correction_successor ON fx.records (supersedes)
    WHERE supersedes IS NOT NULL;
CREATE INDEX record_correlation ON fx.records ((payload->>'correlation_id'), sequence);

CREATE FUNCTION fx.no_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only history: append a superseding record' USING ERRCODE = '23514';
END
$$;
CREATE TRIGGER records_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON fx.records
    FOR EACH STATEMENT EXECUTE FUNCTION fx.no_mutation();
CREATE TRIGGER links_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON fx.record_links
    FOR EACH STATEMENT EXECUTE FUNCTION fx.no_mutation();
CREATE TRIGGER binding_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON fx.account_binding
    FOR EACH STATEMENT EXECUTE FUNCTION fx.no_mutation();

CREATE FUNCTION fx.validate_record() RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, fx AS $$
DECLARE
    binding jsonb;
    previous fx.records;
    b jsonb := NEW.payload->'body';
BEGIN
    SELECT identity INTO STRICT binding FROM fx.account_binding WHERE singleton;
    IF NEW.payload->'account' IS DISTINCT FROM binding THEN
        RAISE EXCEPTION 'account binding mismatch' USING ERRCODE = '23514';
    END IF;
    IF NEW.supersedes IS NOT NULL THEN
        SELECT * INTO STRICT previous FROM fx.records WHERE record_id = NEW.supersedes;
        IF previous.kind <> NEW.kind OR previous.recorded_at > NEW.recorded_at THEN
            RAISE EXCEPTION 'invalid correction kind or time' USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'command' AND
            (b - 'status' - 'outcome') IS DISTINCT FROM
            (previous.payload->'body' - 'status' - 'outcome') THEN
            RAISE EXCEPTION 'command identity is immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'news' AND (
            b->>'source' IS DISTINCT FROM previous.payload#>>'{body,source}' OR
            b->>'item_id' IS DISTINCT FROM previous.payload#>>'{body,item_id}' OR
            (b->>'revision')::integer <= (previous.payload#>>'{body,revision}')::integer) THEN
            RAISE EXCEPTION 'invalid news revision chain' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.kind = 'news' AND NOT (
        (b->>'published_at')::timestamptz <= (b->>'first_observed_at')::timestamptz AND
        (b->>'first_observed_at')::timestamptz <= (b->>'ingested_at')::timestamptz AND
        (b->>'ingested_at')::timestamptz <= (b->>'available_at')::timestamptz AND
        (b->>'available_at')::timestamptz <= NEW.recorded_at) THEN
        RAISE EXCEPTION 'invalid news availability' USING ERRCODE = '23514';
    END IF;
    IF NEW.kind = 'decision' AND b->>'result' IN ('VALID', 'HOLD') AND (
        b#>'{decision,account}' IS DISTINCT FROM binding OR
        (b#>>'{decision,expires_at}')::timestamptz <= NEW.recorded_at) THEN
        RAISE EXCEPTION 'invalid decision account or expiry' USING ERRCODE = '23514';
    END IF;
    IF NEW.kind = 'promotion' AND b->'activation_enabled' IS DISTINCT FROM 'false'::jsonb THEN
        RAISE EXCEPTION 'M0A cannot activate execution' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER validate_record BEFORE INSERT ON fx.records
    FOR EACH ROW EXECUTE FUNCTION fx.validate_record();

-- Runtime roles cannot write links directly. This fixed-path trigger validates and
-- creates them in the same transaction as the source record.
CREATE FUNCTION fx.link_record() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, fx AS $$
DECLARE
    ref jsonb;
    target fx.records;
    b jsonb := NEW.payload->'body';
    cutoff timestamptz := COALESCE((b->>'cutoff')::timestamptz, NEW.recorded_at);
    expected_kind text;
    messages integer := 0;
BEGIN
    FOR ref IN SELECT value FROM jsonb_array_elements(NEW.payload->'references') LOOP
        SELECT * INTO STRICT target FROM fx.records WHERE record_id = (ref->>'record_id')::uuid;
        expected_kind := CASE ref->>'relation'
            WHEN 'NEWS' THEN 'news' WHEN 'HEALTH' THEN 'health' WHEN 'DECISION' THEN 'decision'
            WHEN 'EXECUTION' THEN 'execution' WHEN 'MESSAGE' THEN 'message'
            WHEN 'ARTIFACT' THEN 'artifact' WHEN 'CASE' THEN 'experience' END;
        IF expected_kind IS NULL OR target.kind <> expected_kind OR
            target.recorded_at > NEW.recorded_at THEN
            RAISE EXCEPTION 'wrong evidence type or future record' USING ERRCODE = '23514';
        END IF;
        IF ref->>'relation' IN ('NEWS', 'HEALTH') AND (
            target.recorded_at > cutoff OR
            (target.kind = 'news' AND
             (target.payload#>>'{body,available_at}')::timestamptz > cutoff)) THEN
            RAISE EXCEPTION 'evidence unavailable at decision cutoff' USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'command' AND ref->>'relation' = 'MESSAGE' THEN
            messages := messages + 1;
            IF target.payload#>>'{body,interpretation}' IS DISTINCT FROM 'EXPLICIT_COMMAND' OR
                target.payload#>>'{body,role}' IS DISTINCT FROM 'USER' OR
                target.payload#>'{body,authenticated}' IS DISTINCT FROM 'true'::jsonb OR
                b->'authenticated' IS DISTINCT FROM 'true'::jsonb OR
                b->>'actor_id' IS DISTINCT FROM target.payload#>>'{body,actor_id}' OR
                b->>'message_id' IS DISTINCT FROM target.payload#>>'{body,message_id}' OR
                b->>'conversation_id' IS DISTINCT FROM target.payload#>>'{body,conversation_id}' OR
                b->>'action' IS DISTINCT FROM target.payload#>>'{body,interpreted_action}' THEN
                RAISE EXCEPTION 'message does not authorize command' USING ERRCODE = '23514';
            END IF;
        END IF;
        INSERT INTO fx.record_links VALUES (NEW.record_id, target.record_id, ref->>'relation');
    END LOOP;
    IF NEW.kind = 'command' AND (messages <> 1 OR
        (b->>'status' IN ('INTERPRETED','ACCEPTED') AND
         (b->>'expires_at')::timestamptz <= NEW.recorded_at)) THEN
        RAISE EXCEPTION 'command needs one authorized message and a valid expiry'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER link_record AFTER INSERT ON fx.records
    FOR EACH ROW EXECUTE FUNCTION fx.link_record();
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA fx FROM PUBLIC;
