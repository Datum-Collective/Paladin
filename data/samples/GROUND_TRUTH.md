# Ground Truth: stalk-branch

**Scenario:** Synthetic small branch office (SYNTHETIC DATA). Three weak signals from different log sources
(web scan, ssh login as a service account, IDS alert on RDP to the file server) join into one path
from the public portal to the claims share. Shared names match data/inventory.yaml.


**Generated:** 2024-05-14 12:00:00 UTC


## Attack Summary

This scenario simulates the following attack sequence:

1. **www-data** on **WEB-BO-01**: External vulnerability scanner probes the public claims portal
2. **www-data** on **WEB-BO-01**: Attacker obtains an interactive session as the web service account
3. **nina.kapoor** on **FILE-BO-01**: Attacker uses compromised admin credentials to RDP from the DMZ web server to the file server


## Timeline

| Timestamp | Actor | System | Event Type | Details |
|-----------|-------|--------|------------|---------|
| 2024-05-14 12:30:01 UTC | www-data | WEB-BO-01 | Web_Scan | Web scan (nikto) against 45.83.220.5:80 (59 requests) |
| 2024-05-14 12:45:25 UTC | www-data | WEB-BO-01 | Ssh_Session | SSH session to 10.44.30.10:22 (UID: (filtered by sensor placement)) |
| 2024-05-14 12:45:25 UTC | www-data | WEB-BO-01 | Process | Process: /usr/bin/id (PID: 744380) - `id` |
| 2024-05-14 13:05:03 UTC | nina.kapoor | FILE-BO-01 | Rdp_Session | RDP session to 10.44.20.20:3389 (UID: (filtered by sensor placement)) |


## Source Evidence Status

Canonical ground truth remains authoritative. Source rows may be `visible`, `delayed`, `dropped`, `filtered`, or `out_of_window` depending on the selected observation profile and sensor placement.

| Storyline ID | Source | Status Counts |
|--------------|--------|---------------|
| evt-001 | ids | filtered: 59 |
| evt-002 | syslog | visible: 4 |
| evt-003 | ids | filtered: 1 |
| red_herring:rh-001 | ids | filtered: 1 |


## Indicators of Compromise (IOCs)

### Network IOCs

- 10.44.20.20:3389 (Lateral Movement)
- 10.44.30.10:22 (Lateral Movement)
- 45.83.220.5:80 (Web Scan Target)

### Process IOCs

- /usr/bin/id
- `id`

### User IOCs

- nina.kapoor (compromised account)
- www-data (compromised account)


## Red Herrings

The following events appear suspicious but are benign. They are included to make the dataset more realistic.

| Timestamp | Actor | System | Activity | Why It's Benign |
|-----------|-------|--------|----------|-----------------|
| 2024-05-14 13:40:06 UTC | maya.patel | WS-MPATEL-01 | User mistypes a password during a VPN reconnect | Benign user error |
