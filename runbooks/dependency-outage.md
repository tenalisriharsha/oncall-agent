# Dependency outage

## Symptoms

- No recent deploy, pods healthy (no OOM, low restarts).
- Elevated error rate or latency with no obvious internal cause.

## Diagnosis steps

1. Rule out a deploy regression and a pod health issue first.
2. Check `query_prometheus` for the request rate and error rate of
   outbound calls to each downstream dependency (database, cache,
   third-party API).
3. Check `get_pod_logs` for connection timeouts, `5xx` responses from a
   dependency, or circuit breaker trips.

## Likely root cause

A downstream dependency (database, cache, external API) is degraded or
unavailable, and the service is failing or slowing down while waiting
on it.

## Proposed fix

Confirm the dependency's own status page or alerts. If it is degraded,
escalate to the dependency's owning team and consider enabling a
fallback or circuit breaker on the calling service while it recovers.
