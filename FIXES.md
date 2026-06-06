# Local sensor robustness fixes

This clone contains improvements on top of upstream for reliable operation with Sunny Island 6048 (multicluster) WebBox setups.

## Changes
- Enhanced non-numeric / status channel handling in sensors (prevents ValueError on state_class=measurement with string values like "Off", "Prio_C", "Backup", "---", "Master" etc.)
- Added broad _STATUS_HINTS list for common operating/relay/grid status channels.
- Defensive native_value guards so even if a channel flips type the integration does not crash HA sensor updates.
- Builds on the upstream 53b18cc "Fix sensor non-numeric values" commit.

## For HACS
Use this repo (or your fork) as a custom repository in HACS instead of the original while the main repo history/commit references are unstable.

Install the integration, then the sensors for status channels (op_stt_*, rly*, prio, etc.) will no longer cause coordinator listener errors or "non-numeric value" exceptions.


