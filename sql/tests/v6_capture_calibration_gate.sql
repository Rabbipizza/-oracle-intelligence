\set ON_ERROR_STOP on
DO $$
DECLARE
  m jsonb;
BEGIN
  SELECT metrics->'economic_capture_calibration' INTO m
  FROM public.oracle_v6_experiments
  WHERE model_family='COUNT_NULL_MODEL'
    AND model_version='FORMAL_COUNT_NULL_V1'
    AND invalidated_at IS NULL
  ORDER BY created_at DESC,id DESC LIMIT 1;

  IF m IS NULL THEN
    RAISE EXCEPTION 'V6 CAPTURE CALIBRATION FAIL: metric missing';
  END IF;
  IF coalesce((m->>'capture_probability_allowed')::boolean,false) THEN
    RAISE EXCEPTION 'V6 CAPTURE CALIBRATION FAIL: probability must remain blocked until an explicit validated model stage';
  END IF;
  IF (m->>'state') NOT IN ('NO_CAPTURE_PROBABILITY_INSUFFICIENT_HISTORICAL_OUTCOMES','CAPTURE_MODEL_CALIBRATION_SAMPLE_READY') THEN
    RAISE EXCEPTION 'V6 CAPTURE CALIBRATION FAIL: unexpected state %',m->>'state';
  END IF;
END $$;
