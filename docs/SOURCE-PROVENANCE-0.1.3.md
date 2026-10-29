# Source provenance: Mining Accelerator 0.1.3

Verified on 2026-10-29.

- artifact: `HashBurst-Mining-Accelerator-0.1.3.zip`
- ZIP SHA-256: `d796b6d3519a073bca93fd2591a7642f3baf86f4c17aa04e13cb1151b27c15c3`
- `accelerator.py` SHA-256: `5bcff576a5ebb0b63d6d21eacfe07fba0d19a6040d2ebacc234fa59ff933549b`
- internal `SHA256SUMS`: fully verified

The source archive contains accelerator.py, policy examples, README/CHANGELOG and test_market_v013.py. Python bytecode/cache entries in the ZIP are build/runtime by-products and are intentionally excluded from canonical source import.

Operational evidence previously exercised 11 unit tests successfully and reported version 0.1.3, shadow mode and apply_supported=false.

The source preserves the 0.1.3 boundary: volatile BTC/fiat market telemetry is separated from policy; production apply is not implemented here and belongs behind authenticated Node authorization.
