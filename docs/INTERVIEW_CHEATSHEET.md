# Interview cheat sheet: aas-digital-twin

All numbers below come from files in this repo: `docs/run_output/telemetry.jsonl`, the pytest run, and the source code.

## 60-second pitch

I built a digital twin of a simulated robot arm and conveyor cell. It follows the Industrie 4.0 idea of an Asset Administration Shell, or AAS. The asset is a 3-DOF arm and a conveyor in Gazebo, driven by a ROS 2 node that runs a duty cycle with random faults. An OPC UA server exposes the telemetry. A gateway reads it, fills four AAS submodels, computes OEE from measured uptime and downtime, and publishes to MQTT. A Matplotlib dashboard subscribes to MQTT. There are 32 pytest tests and all pass. The asset is simulated, so the OEE numbers show the pipeline works. They are not factory data.

## 3-minute architecture walkthrough

Follow `docs/diagrams/architecture.png` from left to right.

1. **Asset layer.** `cycle_manager` is a ROS 2 node. It sends joint trajectories to the arm and a belt angle to the conveyor. Every cycle it rolls a fault with 8 percent probability. A fault puts it in DOWN for 3 to 10 seconds. It also tracks cycle count, good count and a temperature signal.
2. **Bridge and OPC UA.** `opcua_bridge_node` copies the ROS 2 topics into an `AssetOpcUaServer` built on asyncua. This is the shop-floor protocol layer.
3. **Gateway.** `gateway/bridge.py` polls the OPC UA server once per second. It writes values into the OperationalState submodel. It adds the time between polls to a downtime counter whenever the state is DOWN. Then it calls `compute_oee`.
4. **AAS layer.** Four submodels: Nameplate, TechnicalData, OperationalState, ConditionMonitoring. They are served by the BaSyx Python SDK REST API under `/api/v3.0`.
5. **MQTT and dashboard.** The gateway publishes two JSON topics to Mosquitto. `live_dashboard.py` subscribes and plots state, temperature, A, P, Q and OEE.

## Why each technology

- **AAS (IEC 63278-1).** A standard shape for asset data. Any AAS tool can read the submodels without knowing my machine.
- **OPC UA.** The usual shop-floor protocol. It has a typed information model and browsing.
- **MQTT.** Light publish-subscribe. Good for sending the same update to many consumers.
- **Eclipse BaSyx Python SDK.** A real implementation of the AAS metamodel and REST API, so I did not invent my own JSON.
- **asyncua.** A pure Python OPC UA server and client. Easy to test over TCP.
- **Mosquitto.** A small, standard MQTT broker that runs locally.

## OEE formula and a real worked example

- Availability A = run time / planned time, where run time = planned time minus downtime.
- Performance P = min(1, ideal cycle time x cycles / run time). Ideal cycle time is 4.0 s (`IDEAL_CYCLE_TIME_S` in `gateway/bridge.py`).
- Quality Q = good cycles / total cycles.
- OEE = A x P x Q.

Last message of the committed 45 s run (about 44.9 s in):

- A = 0.614, so downtime was about 17.3 s of 44.9 s.
- P = 1.0 (capped)
- Q = 29 / 30 = 0.967
- OEE = 0.614 x 1.0 x 0.967 = 0.593

Note on P: the demo runs its simulated cycles faster than the 4 s ideal time to fit 45 s. So P is capped at 1.0 for the whole run. P carries no information in this run.

## OPC UA versus MQTT trade-offs

- OPC UA is client-server with a typed information model. A client can browse and read on demand. It costs more to set up.
- MQTT is publish-subscribe with no data model. Payloads are whatever JSON I choose. It is cheap and fans out well.
- I use OPC UA close to the asset and MQTT toward consumers.
- QoS: the gateway uses paho's default publish, which is QoS 0. That is fine for a 1 Hz telemetry stream where the next sample replaces a lost one. I would use QoS 1 for counters that must not be lost.
- Polling OPC UA at 1 Hz is simple. OPC UA subscriptions would cut latency and traffic. I did not build that.

## Real problems met while building

These are the problems I listed from the first build. The fix details below are what I remember, so check them against your own notes before the interview.

| Problem | Fix |
|---|---|
| sudo password blocking non-interactive runs | Set passwordless sudo once |
| Slow apt over WSL | Wait it out or use a closer mirror |
| Gazebo spawn timing | Wait for the spawn service before commanding the arm |
| DDS discovery delay | Wait for discovery before the first publish |
| Missing `frame_id` | Set `traj.header.frame_id = "base_link"` in `cycle_manager` |
| CMake on the 9p file system | Build in the Linux home folder, not `/mnt/c` |

I did not log which fix took longest in this repo. Pick the one you really remember.

## Honest limits

- The asset is simulated. There is no physical hardware.
- OEE is computed on simulated uptime, not factory data.
- There is no image processing in this project.
- The saved demo run uses an in-process simulator, not Gazebo. The Gazebo path was checked by hand, not by pytest.
- The pytest suite does not talk to a live Mosquitto broker. The gateway test uses a fake publisher.
- Start-up time counts as downtime in the first seconds of a run. See the plot caption.
- The project was built with an AI coding assistant. I must be able to explain every module myself.

## Twelve likely questions

1. **What is an AAS?** A standard digital representation of an asset, made of submodels, defined in IEC 63278-1.
2. **Why four submodels?** Identity (Nameplate), fixed specs (TechnicalData), live state (OperationalState), and derived KPIs (ConditionMonitoring).
3. **Where is OEE computed and why there?** In the gateway, because it sees both the OPC UA values and the poll timing.
4. **How do you measure downtime?** The gateway adds the gap between polls whenever the state reads DOWN. Resolution is the 1 s poll interval.
5. **Is OEE hardcoded anywhere?** No. Only the ideal cycle time of 4 s is a constant.
6. **Why is the early OEE curve jagged?** The first fault hit right after the first cycle. About 6 s of downtime landed in a window of 1 to 7 s, so A fell near 0. P flips between 0 and 1 because run time is tiny.
7. **Why is P always 1?** The demo speeds up cycles, so cycles per run time exceed the ideal rate and P is capped.
8. **Why OPC UA and MQTT both?** OPC UA for typed asset access, MQTT for cheap fan-out to consumers.
9. **How did you test OPC UA?** A real asyncua client connects to the real server over TCP in `test_opcua_server.py`.
10. **How many tests?** 32 collected, 32 passed. 28 test functions, some parametrized.
11. **What would change for real hardware?** Replace the bridge node with the machine's real OPC UA endpoint. The gateway and AAS code stay the same.
12. **What is missing?** Live-broker tests, OPC UA subscriptions, authentication, and real production data.
