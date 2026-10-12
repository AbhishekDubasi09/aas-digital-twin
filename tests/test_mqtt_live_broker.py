"""MQTT path against a real Mosquitto broker on localhost:1883.

Skipped when no broker is listening, so the suite still runs on a machine
without one. CI installs and starts mosquitto, so these tests run there.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import paho.mqtt.client as mqtt
import pytest

from aas_digital_twin.aas.api import build_object_store
from aas_digital_twin.gateway.bridge import (
    MQTT_TOPIC_CONDITION_MONITORING,
    Gateway,
    make_paho_publisher,
)
from aas_digital_twin.opcua.server import AssetOpcUaServer

ENDPOINT = "opc.tcp://127.0.0.1:48403/aas-twin-mqtt-test/"


def _broker_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 1883), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _broker_up(), reason="no Mosquitto broker on localhost:1883")


def _subscriber(topic: str) -> tuple[mqtt.Client, list[dict[str, Any]], threading.Event]:
    received: list[dict[str, Any]] = []
    got = threading.Event()

    def on_message(_c: Any, _u: Any, msg: Any) -> None:
        received.append(json.loads(msg.payload.decode()))
        got.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"test-{uuid.uuid4()}")
    client.on_message = on_message
    client.connect("127.0.0.1", 1883)
    client.subscribe(topic)
    client.loop_start()
    time.sleep(0.3)
    return client, received, got


def test_paho_publisher_delivers_json_through_the_broker() -> None:
    topic = f"aas-digital-twin/test/{uuid.uuid4()}"
    client, received, got = _subscriber(topic)
    try:
        publish = make_paho_publisher()
        publish(topic, json.dumps({"hello": "broker"}))
        assert got.wait(3.0)
        assert received[0] == {"hello": "broker"}
    finally:
        client.loop_stop()
        client.disconnect()


@pytest.fixture
async def asset_server() -> AsyncIterator[AssetOpcUaServer]:
    server = AssetOpcUaServer(endpoint=ENDPOINT)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


async def test_gateway_publishes_oee_to_a_live_broker(asset_server: AssetOpcUaServer) -> None:
    client, received, got = _subscriber(MQTT_TOPIC_CONDITION_MONITORING)
    try:
        await asset_server.update_cycle_state("RUNNING")
        await asset_server.update_counts(cycle_count=10, good_count=9)
        gateway = Gateway(
            opcua_endpoint=ENDPOINT,
            object_store=build_object_store(),
            publish=make_paho_publisher(),
        )
        await gateway.run(poll_interval_s=0.0, max_iterations=1)
        assert got.wait(3.0)
        payload = received[-1]
        assert payload["total_cycle_count"] == 10
        assert payload["good_cycle_count"] == 9
        assert payload["quality"] == pytest.approx(0.9)
    finally:
        client.loop_stop()
        client.disconnect()
