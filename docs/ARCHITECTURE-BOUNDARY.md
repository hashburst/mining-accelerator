# HashBurst Mining Accelerator architecture boundary

This repository owns mining-specific optimization and telemetry.

## Responsibilities

- miner telemetry: hashrate, accepted/rejected/stale shares, pool/algorithm and worker state;
- CPU/GPU mining efficiency and resource-budget proposals;
- AI1 mining optimization and pool/algorithm selection;
- cluster-miner optimization across VPS, Raspberry/ARM, Windows/macOS desktops, rigs and HPC;
- energy-efficiency observations, while never representing CPU-time proxies as measured Joules or verified carbon credits.

The generic HashBurst node runtime in `hashburst/node` coordinates capabilities and protected workloads. Specialist AI models may be supplied by `hashburst/AI`; segmentation policy may be supplied by `hashburst/mining_segmentation`.

The HVM consensus protocol, APoW validity/difficulty/reward rules, HBT native coin and HBT smart-contract execution remain in `hashburst/blockchain`. Mining AI MUST NOT change consensus targets, rewards or validity rules.

The full-node installer composes released components; this repository does not absorb HVM, TEP or installer responsibilities.
