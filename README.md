# HashBurst Mining Accelerator

Canonical repository for HashBurst AI1 mining optimization.

## Status

Current integration target: **0.1.3**. Development / release-candidate preparation. Production APPLY remains disabled.

## Responsibility

AI1 performs the analytical pipeline:

`OBSERVE -> PREDICT -> DECIDE -> SIGNED PROPOSAL`

It evaluates empirical worker/profile history, telemetry health, thermal state and economic inputs. It does not own Node identity, signed controller authorization, TEP, Federation or permanent miner execution.

## Safety boundary

The Accelerator may recommend or propose. The HashBurst Node control plane authorizes actions. MiningControlProvider performs only locally bound provider operations.

The first RC must preserve:

- shadow mode
- `apply_supported=false`
- no arbitrary miner command execution
- no wallet/credential mutation
- no silent history or policy mutation

## Compatibility

HashBurst Node dev3/dev4 Stage A exercised the bridge with Accelerator 0.1.2. The current target is 0.1.3. Contract tests must prove schema/semantic compatibility before Node v0.1.0-rc1.

AI2 solo-mining search-space segmentation is a separate subsystem and is not silently folded into AI1.
