# OOM crash loop

## Symptoms

- `get_pod_status` reports `oom_killed: true` and a high restart count.
- No recent deploy, or the deploy is old enough to rule out a
  regression.

## Diagnosis steps

1. Check `get_pod_status` for `oom_killed` and restart count.
2. Check `query_prometheus` for the container memory usage metric
   against the pod's memory limit, to confirm the pod is consistently
   hitting the ceiling rather than a one-off spike.
3. Check `get_pod_logs` for allocation patterns or a growing working
   set right before each kill.

## Likely root cause

The service's memory limit is too low for its current load, or the
service has a memory leak.

## Proposed fix

Increase the memory limit as an immediate mitigation, and scale up
replicas to spread load. File a follow-up to profile the service for a
leak if restarts continue after the limit increase.
