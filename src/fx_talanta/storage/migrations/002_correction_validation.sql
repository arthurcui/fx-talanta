CREATE OR REPLACE FUNCTION fx.validate_record() RETURNS trigger LANGUAGE plpgsql
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
            ((previous.payload->'body') - 'status' - 'outcome') THEN
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
