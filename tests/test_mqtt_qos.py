"""QoS choice per MQTT topic. No broker needed."""

from aas_digital_twin.gateway.bridge import (
    ALERT_QOS,
    MQTT_TOPIC_ALERTS,
    MQTT_TOPIC_CONDITION_MONITORING,
    MQTT_TOPIC_OPERATIONAL_STATE,
    TELEMETRY_QOS,
    qos_for_topic,
)


def test_alerts_are_confirmed_by_the_broker() -> None:
    assert qos_for_topic(MQTT_TOPIC_ALERTS) == ALERT_QOS == 1


def test_telemetry_is_fire_and_forget() -> None:
    for topic in (MQTT_TOPIC_OPERATIONAL_STATE, MQTT_TOPIC_CONDITION_MONITORING):
        assert qos_for_topic(topic) == TELEMETRY_QOS == 0


def test_unknown_topics_default_to_telemetry_qos() -> None:
    assert qos_for_topic("aas-digital-twin/anything-else") == TELEMETRY_QOS
