# Network partition

## Symptoms

- Requests between two services time out or are refused, but both
  services individually report healthy pods and normal CPU/memory.
- The failure is one-directional or confined to specific pods/nodes
  rather than affecting every instance of a service.

## Diagnosis steps

1. Check `get_pod_status` on both sides of the call to confirm pods are
   up and not restarting.
2. Check `query_prometheus` for connection error or timeout metrics
   between the two services, and compare across nodes/availability
   zones to spot a localized partition.
3. Check `describe_pod` for network-related events (CNI errors, node
   NotReady conditions) on the affected pods' nodes.

## Likely root cause

A network partition between nodes, zones, or a misconfigured network
policy is blocking traffic that would otherwise succeed.

## Proposed fix

If isolated to specific nodes, cordon and drain them so traffic routes
around the partition. If caused by a network policy change, roll that
change back. Escalate to infrastructure/networking if the partition is
at the cluster or cloud-provider level.
