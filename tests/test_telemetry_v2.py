#!/usr/bin/env python3
import pathlib
p=pathlib.Path(__file__).with_name("telemetry-v2.py").read_text()
c=pathlib.Path(__file__).with_name("compare-telemetry-v2.py").read_text()
assert "hashburst-mining-telemetry-v2" in p
assert "/sys/fs/cgroup" in p and "usage_usec" in p
assert "systemd-cgroup-v2-interval" in p
assert '"joules":None' in p and '"co2e_g":None' in p
assert "supported_node_classes" in p
assert "difference_in_differences_load" in c
assert "miner_pid_continuity" in c
assert "throughput_measured" in c and "share_acceptance_measured" in c
print("HASHBURST_MINING_TELEMETRY_V2_TESTS_OK")
