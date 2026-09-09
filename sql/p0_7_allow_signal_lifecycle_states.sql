-- P0-7: lifecycle states are first-class states in trend_probabilities.
alter table public.oracle_v6_trend_probabilities drop constraint if exists oracle_v6_trend_probabilities_state_check;
alter table public.oracle_v6_trend_probabilities add constraint oracle_v6_trend_probabilities_state_check
check (state = any(array['NOISE','SIGNAL','EMERGING','ACCELERATING','CONFIRMED','MATURE','DECLINING','EPHEMERAL_SIGNAL','REPLICATED_SIGNAL','CANDIDATE_FOR_SEMANTIC_BRIDGE']::text[]));