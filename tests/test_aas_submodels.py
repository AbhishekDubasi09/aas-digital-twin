"""Tests for AAS submodel construction, serialization, and the REST API."""

from __future__ import annotations

import json

import pytest
from basyx.aas.adapter.json import json_serialization
from werkzeug.test import Client

from aas_digital_twin.aas.api import build_object_store, build_wsgi_app
from aas_digital_twin.aas.submodels import (
    build_asset_shell,
    build_condition_monitoring_submodel,
    build_nameplate_submodel,
    build_operational_state_submodel,
    build_technical_data_submodel,
)

EXPECTED_SUBMODEL_ID_SHORTS = {
    "Nameplate",
    "TechnicalData",
    "OperationalState",
    "ConditionMonitoring",
}


def _all_submodels():
    return [
        build_nameplate_submodel(),
        build_technical_data_submodel(),
        build_operational_state_submodel(),
        build_condition_monitoring_submodel(),
    ]


def test_all_four_submodels_are_built_with_expected_id_shorts() -> None:
    id_shorts = {sm.id_short for sm in _all_submodels()}
    assert id_shorts == EXPECTED_SUBMODEL_ID_SHORTS


def test_shell_references_all_four_submodels() -> None:
    submodels = _all_submodels()
    shell = build_asset_shell(submodels)
    referenced_ids = {ref.key[0].value for ref in shell.submodel}
    assert referenced_ids == {sm.id for sm in submodels}


@pytest.mark.parametrize("submodel_factory", _all_submodels())
def test_submodel_round_trips_through_json_serialization(submodel_factory) -> None:
    """Serialize each submodel to AAS JSON and back, verifying it is well-formed."""
    serialized = json.dumps(submodel_factory, cls=json_serialization.AASToJsonEncoder)
    data = json.loads(serialized)
    assert data["modelType"] == "Submodel"
    assert data["id"] == submodel_factory.id
    assert len(data["submodelElements"]) == len(submodel_factory.submodel_element)
    for element in data["submodelElements"]:
        assert element["modelType"] == "Property"
        assert "valueType" in element
        assert "value" in element


def test_operational_state_values_are_mutable_in_place() -> None:
    sm = build_operational_state_submodel()
    joint1 = sm.get_referable("Joint1PositionRad")
    joint1.value = 0.75
    assert sm.get_referable("Joint1PositionRad").value == pytest.approx(0.75)


def test_condition_monitoring_values_are_mutable_in_place() -> None:
    sm = build_condition_monitoring_submodel()
    sm.get_referable("OEE").value = 0.42
    sm.get_referable("TotalCycleCount").value = 100
    assert sm.get_referable("OEE").value == pytest.approx(0.42)
    assert sm.get_referable("TotalCycleCount").value == 100


def test_rest_api_lists_shell_and_submodels() -> None:
    store = build_object_store()
    app = build_wsgi_app(store)
    client = Client(app)

    shells_resp = client.get("/api/v3.0/shells")
    assert shells_resp.status_code == 200
    shells = shells_resp.get_json()["result"]
    assert len(shells) == 1
    assert shells[0]["idShort"] == "SimArm3DofShell"

    submodels_resp = client.get("/api/v3.0/submodels")
    assert submodels_resp.status_code == 200
    submodels = submodels_resp.get_json()["result"]
    assert {sm["idShort"] for sm in submodels} == EXPECTED_SUBMODEL_ID_SHORTS


def test_rest_api_returns_condition_monitoring_submodel_by_id() -> None:
    from base64 import urlsafe_b64encode

    store = build_object_store()
    app = build_wsgi_app(store)
    client = Client(app)

    cm = next(sm for sm in store if sm.id_short == "ConditionMonitoring")
    encoded_id = urlsafe_b64encode(cm.id.encode()).decode()

    resp = client.get(f"/api/v3.0/submodels/{encoded_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["idShort"] == "ConditionMonitoring"
    element_names = {e["idShort"] for e in body["submodelElements"]}
    assert element_names == {
        "Availability",
        "Performance",
        "Quality",
        "OEE",
        "TotalCycleCount",
        "GoodCycleCount",
    }
