# Disk pressure

## Symptoms

- Pods are evicted or fail to schedule with a `DiskPressure` node
  condition.
- `get_pod_status` shows pods stuck in `Pending` or repeatedly
  recreated on a different node, rather than a clean OOM kill.

## Diagnosis steps

1. Check `describe_pod` for `DiskPressure` conditions or eviction
   events.
2. Check `query_prometheus` for node filesystem usage against
   capacity, and for any single volume (logs, temp files, container
   image cache) growing unbounded.
3. Check `get_pod_logs` for the service writing excessive local logs
   or temp files.

## Likely root cause

A node's disk filled up, usually from unbounded local logging, a
temp-file leak, or accumulated container images, triggering kubelet
eviction.

## Proposed fix

Clear the offending disk usage (log rotation, temp cleanup, image GC)
as an immediate fix, and set resource/log limits so the same service
cannot repeat the fill-up. Escalate to infra if node-level disk sizing
itself needs to change.
