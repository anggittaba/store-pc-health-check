Scored over 30 simulated days (2026-09-12 to 2026-10-11). Unit: one issue type on one PC on one day (store-level for missing pulls).

| Issue type | Found & real | False alarms | Missed | of which hidden by a missing pull | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| No data from store | 27 | 0 | 0 | 0 | 100.0% | 100.0% |
| Card terminal offline | 70 | 17 | 0 | 0 | 80.5% | 100.0% |
| LAN degraded | 46 | 28 | 2 | 0 | 62.2% | 95.8% |
| Overheating | 39 | 1 | 13 | 1 | 97.5% | 75.0% |
| Disk health warning | 55 | 0 | 0 | 0 | 100.0% | 100.0% |
| Disk almost full | 43 | 0 | 9 | 0 | 100.0% | 82.7% |
| UPS problem | 43 | 16 | 8 | 0 | 72.9% | 84.3% |
| RAM below spec | 43 | 0 | 0 | 0 | 100.0% | 100.0% |
| No restart | 107 | 0 | 0 | 0 | 100.0% | 100.0% |
| Windows not activated | 39 | 0 | 6 | 6 | 100.0% | 86.7% |
| **All types** | **512** | **62** | **38** | **7** | **89.2%** | **93.1%** |

Wait-and-confirm variant (only issues seen 2+ checks in a row):

| Issue type | Precision | Recall |
|---|---:|---:|
| No data from store | 100.0% | 48.1% |
| Card terminal offline | 97.8% | 64.3% |
| LAN degraded | 100.0% | 58.3% |
| Overheating | 100.0% | 55.8% |
| Disk health warning | 100.0% | 89.1% |
| Disk almost full | 100.0% | 65.4% |
| UPS problem | 100.0% | 70.6% |
| RAM below spec | 100.0% | 86.0% |
| No restart | 100.0% | 90.7% |
| Windows not activated | 100.0% | 80.0% |

40 independent simulated fleets (seeds 1–40), 30 days each. Mean, with min–max in brackets.

| Issue type | Precision | Recall |
|---|---:|---:|
| No data from store | 100.0% (100–100) | 100.0% (100–100) |
| Card terminal offline | 67.1% (53–81) | 98.6% (94–100) |
| LAN degraded | 62.5% (40–78) | 84.8% (44–100) |
| Overheating | 93.5% (85–99) | 82.4% (75–89) |
| Disk health warning | 100.0% (100–100) | 99.0% (92–100) |
| Disk almost full | 100.0% (100–100) | 74.8% (60–83) |
| UPS problem | 78.0% (61–89) | 77.0% (57–91) |
| RAM below spec | 100.0% (100–100) | 98.3% (82–100) |
| No restart | 100.0% (100–100) | 98.9% (89–100) |
| Windows not activated | 100.0% (100–100) | 98.4% (87–100) |
| **All types** | **88.7% (85–93)** | **90.1% (83–94)** |
