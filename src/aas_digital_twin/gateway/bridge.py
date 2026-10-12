"""Edge gateway: OPC UA -> AAS submodels -> MQTT.

Polls the OPC UA asset server, writes live values into the AAS
OperationalState submodel, tracks real uptime/downtime from the observed
cycle state to recompute OEE into the ConditionMonitoring submodel, and
publishes a JSON snapshot of both submodels to MQTT.
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from asyncua import Client
from asyncua.common.node import Node
from basyx.aas import model

from aas_digital_twin.aas.oee import compute_oee
from aas_digital_twin.asset import thermal_model

IDEAL_CYCLE_TIME_S = thermal_model.IDEAL_CYCLE_TIME_S
"""Ideal seconds per cycle. The FR3 path takes 4.4 s, so Performance is about 0.91."""

MQTT_TOPIC_OPERATIONAL_STATE = "aas-digital-twin/operational_state"
MQTT_TOPIC_CONDITION_MONITORING = "aas-digital-twin/condition_monitoring"
MQTT_TOPIC_ALERTS = "aas-digital-twin/alerts"


class MqttPublisher(Protocol):
    """Minimal publish interface so tests can inject a stub instead of a broker."""

    def __call__(self, topic: str, payload: str) -> None: ...


class Gateway:
    """Bridges one OPC UA asset server into AAS submodels and MQTT."""

    def __init__(
        self,
        opcua_endpoint: str,
        object_store: model.DictObjectStore,
        publish: MqttPublisher,
        mitigation: bool = True,
    ) -> None:
        """Create a gateway wired to a specific OPC UA endpoint and object store.

        Args:
            opcua_endpoint: OPC UA server URL to poll.
            object_store: AAS object store containing OperationalState and
                ConditionMonitoring submodels to update in place.
            publish: callable(topic, payload) used to send MQTT messages.
            mitigation: if True, derate the cell when the temperature is high.
        """
        self._opcua_endpoint = opcua_endpoint
        self._operational_state = next(
            sm for sm in object_store if sm.id_short == "OperationalState"
        )
        self._condition_monitoring = next(
            sm for sm in object_store if sm.id_short == "ConditionMonitoring"
        )
        self._publish = publish
        self._mitigation = mitigation
        self._speed_scale = 1.0

        self._run_start_time = time.monotonic()
        self._downtime_accum_s = 0.0
        self._last_poll_time = self._run_start_time

    async def poll_once(self, opcua_client: Client) -> None:
        """Read the OPC UA asset cell once and propagate values downstream."""
        now = time.monotonic()
        elapsed_since_last_poll = now - self._last_poll_time
        self._last_poll_time = now

        asset_cell = await self._get_asset_cell_node(opcua_client)
        children = await asset_cell.get_children()
        values: dict[str, Any] = {}
        for child in children:
            name = (await child.read_browse_name()).Name
            values[name] = await child.read_value()

        cycle_state = str(values.get("CycleState", "IDLE"))
        if cycle_state == "DOWN":
            self._downtime_accum_s += elapsed_since_last_poll

        if self._mitigation:
            await self._apply_derating(children, float(values.get("Temperature", 0.0)))
        self._write_operational_state(values)
        oee_snapshot = self._recompute_condition_monitoring(values)

        self._publish(
            MQTT_TOPIC_OPERATIONAL_STATE,
            json.dumps(self._submodel_values(self._operational_state)),
        )
        self._publish(MQTT_TOPIC_CONDITION_MONITORING, json.dumps(oee_snapshot))

    async def run(self, poll_interval_s: float = 1.0, max_iterations: int | None = None) -> None:
        """Poll the OPC UA server on an interval, forever or a bounded count.

        Args:
            poll_interval_s: seconds to sleep between polls.
            max_iterations: if given, stop after this many polls (used in tests).
        """
        import asyncio

        async with Client(url=self._opcua_endpoint) as client:
            i = 0
            while max_iterations is None or i < max_iterations:
                await self.poll_once(client)
                i += 1
                if max_iterations is None or i < max_iterations:
                    await asyncio.sleep(poll_interval_s)

    async def _apply_derating(self, children: list[Node], temperature_c: float) -> None:
        """Slow the cell down before the thermal trip zone, and restore speed later."""
        new_scale = thermal_model.next_speed_scale(temperature_c, self._speed_scale)
        if new_scale == self._speed_scale:
            return
        for child in children:
            if (await child.read_browse_name()).Name == "SpeedScale":
                await child.write_value(float(new_scale))
        self._publish(
            MQTT_TOPIC_ALERTS,
            json.dumps(
                {
                    "alarm": "THERMAL_DERATING" if new_scale < 1.0 else "NONE",
                    "temperature_c": round(temperature_c, 2),
                    "speed_scale": new_scale,
                    "action": "derate" if new_scale < 1.0 else "restore full speed",
                }
            ),
        )
        self._speed_scale = new_scale

    async def _get_asset_cell_node(self, opcua_client: Client) -> Node:
        objects = opcua_client.nodes.objects
        for child in await objects.get_children():
            if (await child.read_browse_name()).Name == "AssetCell":
                return child
        raise RuntimeError("AssetCell object not found on OPC UA server")

    def _write_operational_state(self, values: dict[str, Any]) -> None:
        mapping = {
            "Joint1Position": "Joint1PositionRad",
            "Joint2Position": "Joint2PositionRad",
            "Joint3Position": "Joint3PositionRad",
            "Joint4Position": "Joint4PositionRad",
            "Joint5Position": "Joint5PositionRad",
            "Joint6Position": "Joint6PositionRad",
            "Joint7Position": "Joint7PositionRad",
            "ConveyorSpeed": "ConveyorSpeedMPerS",
            "Temperature": "TemperatureCelsius",
            "CycleState": "CycleState",
        }
        for opcua_name, aas_id_short in mapping.items():
            if opcua_name in values:
                element = self._operational_state.get_referable(aas_id_short)
                element.value = values[opcua_name]

    def _recompute_condition_monitoring(self, values: dict[str, Any]) -> dict[str, Any]:
        planned_time_s = max(time.monotonic() - self._run_start_time, 1e-6)
        total_count = int(values.get("CycleCount", 0))
        good_count = int(values.get("GoodCount", 0))

        result = compute_oee(
            planned_production_time_s=planned_time_s,
            downtime_s=min(self._downtime_accum_s, planned_time_s),
            ideal_cycle_time_s=IDEAL_CYCLE_TIME_S,
            total_cycle_count=total_count,
            good_cycle_count=good_count,
        )

        self._condition_monitoring.get_referable("Availability").value = result.availability
        self._condition_monitoring.get_referable("Performance").value = result.performance
        self._condition_monitoring.get_referable("Quality").value = result.quality
        self._condition_monitoring.get_referable("OEE").value = result.oee
        self._condition_monitoring.get_referable("TotalCycleCount").value = total_count
        self._condition_monitoring.get_referable("GoodCycleCount").value = good_count
        alarm = "THERMAL_DERATING" if self._speed_scale < 1.0 else "NONE"
        self._condition_monitoring.get_referable("SpeedScale").value = self._speed_scale
        self._condition_monitoring.get_referable("ActiveAlarm").value = alarm

        return {
            "availability": result.availability,
            "performance": result.performance,
            "quality": result.quality,
            "oee": result.oee,
            "total_cycle_count": total_count,
            "good_cycle_count": good_count,
            "speed_scale": self._speed_scale,
            "alarm": alarm,
        }

    @staticmethod
    def _submodel_values(submodel: model.Submodel) -> dict[str, Any]:
        return {
            e.id_short: e.value for e in submodel.submodel_element if isinstance(e, model.Property)
        }


def make_paho_publisher(host: str = "localhost", port: int = 1883) -> MqttPublisher:
    """Build a real MQTT publish callable backed by paho-mqtt (Eclipse Mosquitto)."""
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(host, port)
    client.loop_start()

    def _publish(topic: str, payload: str) -> None:
        client.publish(topic, payload)

    return _publish
