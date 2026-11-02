ALTER TABLE fx.records DROP CONSTRAINT record_provenance;
ALTER TABLE fx.records ADD CONSTRAINT record_provenance CHECK (
    payload->>'provenance' IS NOT NULL AND payload->>'provenance'
    IN ('SCRIPTED_FIXTURE','OFFLINE_SIMULATION','BROKER_OBSERVATION')
);
ALTER TABLE fx.records DROP CONSTRAINT observation_scope;
ALTER TABLE fx.records ADD CONSTRAINT observation_scope CHECK (
    (kind <> 'observation' OR (
        payload#>>'{account,environment}' = 'PAPER' AND
        ((payload#>>'{account,venue}' = 'SIMULATOR' AND
          payload->>'provenance' = 'SCRIPTED_FIXTURE') OR
         (payload#>>'{account,venue}' = 'BROKER_DEMO' AND
          payload->>'provenance' = 'BROKER_OBSERVATION')) AND
        (payload#>'{body,snapshot}' = 'null'::jsonb OR (
            payload#>'{body,snapshot,account_before}' = payload->'account' AND
            payload#>'{body,snapshot,account_after}' = payload->'account' AND
            (payload#>>'{body,snapshot,observed_at}')::timestamptz <= recorded_at
        ))
    )) IS TRUE
);
ALTER TABLE fx.records ADD CONSTRAINT demo_evidence_scope CHECK (
    ((payload#>>'{account,venue}' <> 'BROKER_DEMO' AND
      payload->>'provenance' <> 'BROKER_OBSERVATION') OR
     (payload#>>'{account,venue}' = 'BROKER_DEMO' AND kind = 'observation' AND
      payload->>'provenance' = 'BROKER_OBSERVATION')) IS TRUE
);
