# Config drift

## Symptoms

- A service starts misbehaving with no deploy and no infrastructure
  change, often after a ConfigMap, Secret, or feature-flag update.
- Behavior differs between replicas, or between environments that
  should be identical.

## Diagnosis steps

1. Check `get_recent_deploys` to rule out a code deploy as the trigger.
2. Check `describe_pod` for recent ConfigMap/Secret mount changes or
   restart reasons tied to config reloads.
3. Compare configuration (env vars, mounted ConfigMaps, feature flags)
   across replicas or environments to find the one that drifted.

## Likely root cause

A configuration change (ConfigMap, Secret, feature flag, or manual
`kubectl edit`) was applied outside of the normal deploy pipeline and
is not what the running code expects.

## Proposed fix

Revert the configuration to the last known-good value and bring it
under the same review process as code deploys so future changes are
tracked and reversible.
