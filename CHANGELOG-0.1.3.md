# 0.1.3
- Separated volatile BTC/EUR observation from policy.
- Added `hashburst-market-observation-v1`.
- Added dual-source `market-collect` with CoinGecko/Coinbase adapters, freshness, response hashes and cross-source deviation gate.
- Added non-destructive `migrate-policy`.
- `status` and `recommend` now require `--market`.
- Kept 0.1.2 history schema unchanged and read-only compatibility.
- Production apply remains unsupported in Accelerator; execution is reserved for authenticated Node Stage B.