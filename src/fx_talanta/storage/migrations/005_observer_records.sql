-- Foundation observations are synthetic. Real broker-demo provisioning and
-- provenance require a separate, explicitly qualified increment.
ALTER TABLE fx.records DROP CONSTRAINT records_kind_check;
ALTER TABLE fx.records ADD CONSTRAINT records_kind_check CHECK (
    kind IN ('decision','risk','execution','experience','lesson','artifact',
             'promotion','news','health','message','command','observation')
);
ALTER TABLE fx.records ADD CONSTRAINT observation_scope CHECK (
    kind <> 'observation' OR (
        payload->>'provenance' IS NOT DISTINCT FROM 'SCRIPTED_FIXTURE' AND
        payload#>>'{account,environment}' IS NOT DISTINCT FROM 'PAPER' AND
        payload#>>'{account,venue}' IS NOT DISTINCT FROM 'SIMULATOR' AND
        (payload#>'{body,snapshot}' = 'null'::jsonb OR (
            payload#>'{body,snapshot,account_before}' IS NOT DISTINCT FROM payload->'account' AND
            payload#>'{body,snapshot,account_after}' IS NOT DISTINCT FROM payload->'account' AND
            (payload#>>'{body,snapshot,observed_at}')::timestamptz <= recorded_at
        )) IS TRUE
    )
);
