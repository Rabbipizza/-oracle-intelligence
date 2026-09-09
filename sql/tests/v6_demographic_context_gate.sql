\set ON_ERROR_STOP on
DO $$
DECLARE
  m jsonb;
BEGIN
  SELECT metrics->'demographic_context' INTO m
  FROM public.oracle_v6_experiments
  WHERE model_family='COUNT_NULL_MODEL'
    AND model_version='FORMAL_COUNT_NULL_V1'
    AND invalidated_at IS NULL
  ORDER BY created_at DESC,id DESC LIMIT 1;

  IF m IS NULL THEN
    RAISE EXCEPTION 'V6 DEMOGRAPHY FAIL: demographic_context metric missing';
  END IF;
  IF coalesce((m->>'historical_pit_backtest_allowed')::boolean,true) THEN
    RAISE EXCEPTION 'V6 DEMOGRAPHY FAIL: revised WDI series must not be admitted to historical PIT backtests';
  END IF;
  IF (m->>'state') NOT IN ('DEMOGRAPHIC_CONTEXT_AVAILABLE','NO_DEMOGRAPHIC_CONTEXT') THEN
    RAISE EXCEPTION 'V6 DEMOGRAPHY FAIL: unexpected state %',m->>'state';
  END IF;
END $$;
