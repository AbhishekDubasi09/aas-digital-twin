# Interview cheat sheet: aas-digital-twin

All numbers below come from files in this repo: `docs/run_output/` (CSV logs, `ab_summary.json`, `pytest_output.txt`) and the source code.

## The objective in one paragraph

A pick-and-place cell loses output when the arm overheats and stops. The twin shows the state of the cell in a standard form (AAS over OPC UA and MQTT), measures OEE from real uptime and cycle counts, and reacts to the temperature before the stop happens. That is the whole project. The Franka arm is the asset. The rest is the pipeline around it.

## 60-second pitch

I built a digital twin of a Franka Research 3 pick-and-place cell in Gazebo. The arm moves parts from a conveyor into a good bin and a reject bin. It heats up while it works, and above about 40 C it can trip into a stop of 20 to 40 seconds. A ROS 2 node runs the cell and publishes telemetry. An OPC UA server exposes it. A gateway reads it, fills four AAS submodels, computes OEE from measured uptime, downtime and cycle counts, and publishes to MQTT. When the temperature reaches 38 C the gateway writes a lower speed back over OPC UA. In my 300-seed model run that cut thermal stops from about two per run to zero and raised OEE from 0.63 to 0.69. In my single Gazebo pair the OEE was equal, because one run is noisy. There are 46 pytest tests and all pass. The asset is simulated, so none of this is factory data.

## 3-minute architecture walkthrough

Follow `docs/diagrams/architecture.png` from left to right.

1. **Asset layer.** `cycle_manager.py` is a ROS 2 node. It solves the FR3 pick and place path with `fr3_kinematics.py`, sends joint targets at 30 Hz, and moves the parts on the belt. It keeps a simple thermal model. Heating depends on speed squared, cooling pulls toward 25 C, and above 40 C each finished cycle can end in a 20 to 40 s thermal stop.
2. **Bridge and OPC UA.** `opcua_bridge_node.py` copies ROS 2 topics into `AssetOpcUaServer` (asyncua). It also reads the writable `SpeedScale` node and publishes it back to the cycle manager.
3. **Gateway.** `gateway/bridge.py` polls OPC UA every 0.5 s. It writes OperationalState, adds the time between polls to downtime when the state is DOWN, and calls `compute_oee`. If the temperature is 38 C or more, it writes `SpeedScale = 0.8` and publishes an alert.
4. **AAS layer.** Four submodels: Nameplate, TechnicalData, OperationalState, ConditionMonitoring. They are served by the BaSyx Python SDK REST API under `/api/v3.0`.
5. **MQTT and dashboard.** The gateway publishes JSON topics to Mosquitto. `live_dashboard.py` subscribes and plots OEE, A, P, Q, the seven joints, temperature, state and alarm.

## Why each technology

- **AAS (IEC 63278-1).** A standard shape for asset data. Any AAS tool can read the submodels without knowing my machine.
- **OPC UA.** The usual shop-floor protocol. It has a typed information model, browsing and writable nodes. I needed a writable node for the derating command.
- **MQTT.** Light publish-subscribe. Good for sending the same update to many consumers.
- **Eclipse BaSyx Python SDK.** A real implementation of the AAS metamodel and REST API, so I did not invent my own JSON.
- **asyncua.** A pure Python OPC UA server and client. Easy to test over TCP.
- **Mosquitto.** A small standard MQTT broker that runs locally.

## OEE formula and a worked example from the real run

- Availability A = run time / planned time, where run time = planned time minus downtime.
- Performance P = min(1, ideal cycle time x cycles / run time). Ideal cycle time is 4.0 s (`IDEAL_CYCLE_TIME_S` in `gateway/bridge.py`). The FR3 path takes 4.4 s.
- Quality Q = good cycles / total cycles.
- OEE = A x P x Q.

Last row of the derated 240 s run (`docs/run_output/mitigated/telemetry.csv`, t = 239.8 s):

- A = 0.906 (22.4 s of downtime in the window)
- P = 0.718 (39 cycles x 4.0 s / run time, with the arm running at speed 0.8)
- Q = 38 / 39 = 0.974
- OEE = 0.906 x 0.718 x 0.974 = 0.634

Last row of the baseline run: A = 0.781, P = 0.833, Q = 0.974, OEE = 0.634.

## OPC UA versus MQTT trade-offs

- OPC UA is client-server with a typed information model. A client can browse, read and write on demand. It costs more to set up.
- MQTT is publish-subscribe with no data model. Payloads are whatever JSON I choose. It is cheap and fans out well.
- I use OPC UA next to the asset and for the command back to it, and MQTT toward consumers.
- QoS: the gateway uses paho's default publish, which is QoS 0. That is fine for a 2 Hz stream where the next sample replaces a lost one. The alert topic should be QoS 1 so an alarm is not lost. I did not change that yet.
- Polling OPC UA is simple. OPC UA subscriptions would cut latency and traffic. I did not build that.

## Real problems met while building

| Problem | Fix |
|---|---|
| sudo password blocking non-interactive runs | Passwordless sudo, set once |
| Slow apt over WSL | Install only what is needed, in one call |
| Gazebo spawn timing | `spawn_entity` waits for the service, timeout raised to 180 s |
| `model://sun` made gzserver try to download from the internet and the spawn timed out | Defined the light inline in the world file |
| DDS discovery delay | Wait for the spawn and the topics before starting the bridge and cycle manager |
| Missing `frame_id` | `traj.header.frame_id = "base"` on every trajectory |
| CMake on the 9p file system | Build in the Linux home folder, not `/mnt/c` |
| Glitchy arm, cycle count 4 times too high | Old `cycle_manager` processes from earlier launches were still running and fighting. The run script now kills leftovers first |
| Dashboard recording crashed after 10 frames | Race between the MQTT thread and the plotting thread. Added a lock and a snapshot |
| Dashboard video ran too fast | Drawing was slower than the video frame rate. Rendered from the logged CSV instead, with exact timing |
| Screen capture of the Gazebo window was black | WSLg does not draw the root window. Captured the window id with ImageMagick `import`, three workers in parallel |

Which fix took longest: the duplicate `cycle_manager` processes. The symptom looked like a simulation bug, and the data looked wrong for a while before I thought of stale processes. For the first build I do not have a record, so pick the one you remember.

## Honest limits

- The asset is simulated. There is no physical hardware.
- The temperature model and the trip behavior are my assumptions. The result "derating helps" depends on a thermal stop taking 20 to 40 s. With short stops it would not pay off. I checked that in the model.
- OEE is computed on simulated uptime, not factory data.
- One Gazebo pair showed equal OEE. The gain only shows over many seeds in the model.
- Parts are moved by setting their pose. There is no grasp or contact physics.
- There is no image processing in this project.
- The project was built with an AI coding assistant. I must be able to explain every module myself.

## Twelve likely questions

1. **What is an AAS?** A standard digital representation of an asset, made of submodels, defined in IEC 63278-1.
2. **Why four submodels?** Identity (Nameplate), fixed specs (TechnicalData), live state (OperationalState), derived KPIs and alarms (ConditionMonitoring).
3. **Where is OEE computed and why there?** In the gateway, because it sees both the OPC UA values and the poll timing.
4. **How do you measure downtime?** The gateway adds the gap between polls whenever the state reads DOWN. Resolution is the 0.5 s poll interval.
5. **Is OEE hardcoded anywhere?** No. Only the ideal cycle time of 4.0 s is a constant.
6. **Why is the early OEE curve rough?** Before the first cycle finishes, P and Q are zero. In this cell that is about 12 s, because the first part travels along the belt. After that each cycle moves P by a large step.
7. **Why is Performance 0.72 in the derated run?** The arm ran at 0.8 speed, so each cycle takes 5.5 s instead of 4.4 s. That is the price of avoiding the stops.
8. **Does the twin really fix the problem?** It does not repair hardware. It senses, decides and sends a command. In the simulation that removed the thermal stops. On a real machine the same loop would need the machine's own limits and safety rules.
9. **Why OPC UA and MQTT both?** OPC UA for typed asset access and commands, MQTT for cheap fan-out to consumers.
10. **How did you test OPC UA and MQTT?** A real asyncua client talks to the real server over TCP. The MQTT tests use a live Mosquitto broker and skip if none is running.
11. **How many tests?** 46 collected, 46 passed with a Mosquitto broker running. Two of them skip when no broker is up. They include FK and IK checks, the thermal model, the gateway derating write-back and the OPC UA server.
12. **What would change for real hardware?** Replace the bridge node with the machine's real OPC UA endpoint and map its node names. The gateway and AAS code stay the same. Add authentication and subscriptions.
