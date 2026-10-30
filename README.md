# HashBurst Mining Accelerator

Canonical repository for HashBurst AI1 mining optimization.

## Status

The current integration target is **0.1.3**. Production application remains disabled while the release-candidate line is under validation.

## Responsibility

AI1 analyzes mining telemetry and operating history to produce signed optimization proposals.

The processing sequence is:

`OBSERVE -> PREDICT -> DECIDE -> SIGNED PROPOSAL`

It evaluates worker and profile history, telemetry quality, thermal conditions and economic inputs. Node identity, controller authorization, TEP, Federation and permanent miner execution remain outside the Accelerator.

## Safety boundary

The Accelerator produces recommendations and signed proposals. The HashBurst Node control plane decides whether an authorized action may proceed. MiningControlProvider is limited to operations exposed by the locally configured provider.

The release-candidate safety requirements include:

- shadow mode
- `apply_supported=false`
- no arbitrary miner command execution
- no wallet or credential changes
- no unrecorded changes to history or policy

## Compatibility

The current integration target is Mining Accelerator 0.1.3. Compatibility with the HashBurst Node control contract is verified through contract tests covering the exchanged schemas and their required behavior.

AI2 handles solo-mining search-space segmentation as a separate subsystem. Its responsibilities and execution path remain independent from AI1.
