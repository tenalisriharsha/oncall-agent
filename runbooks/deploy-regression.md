# Deploy regression

## Symptoms

- Error rate or latency jumps shortly after a deploy.
- The jump lines up with `get_recent_deploys` reporting a deploy within
  the last 30 minutes.

## Diagnosis steps

1. Check `get_recent_deploys` for the affected service. A deploy inside
   the alert's lookback window is the strongest signal.
2. Check `get_pod_status` for restart counts. Restarts right after a
   deploy usually mean the new version is crashing on startup or
   failing readiness probes.
3. Check `query_prometheus` for the error-rate or latency metric named
   in the alert, and confirm the inflection point lines up with the
   deploy timestamp, not something earlier.

## Likely root cause

A code or config regression shipped in the most recent deploy.

## Proposed fix

Roll back the service to the previous version. Only re-attempt the new
version after the regression is fixed and verified in staging.
