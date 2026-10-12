"""The four AAS submodels for the arm+conveyor asset cell (IEC 63278-1).

Nameplate and TechnicalData are static; OperationalState and
ConditionMonitoring carry live values that the gateway updates as new
telemetry arrives.
"""

from __future__ import annotations

from typing import Any

from basyx.aas import model

NAMESPACE = "https://aas-digital-twin.example/ids"


def _prop(id_short: str, value: Any, value_type: model.DataTypeDefXsd) -> model.Property:
    return model.Property(id_short=id_short, value_type=value_type, value=value)


def build_nameplate_submodel() -> model.Submodel:
    """Static identification data: manufacturer, product, serial number."""
    return model.Submodel(
        id_=f"{NAMESPACE}/submodels/Nameplate",
        id_short="Nameplate",
        submodel_element={
            _prop("ManufacturerName", "aas-digital-twin project", model.datatypes.String),
            _prop("ManufacturerProductDesignation", "Franka Research 3 (simulated)", model.datatypes.String),
            _prop("SerialNumber", "SIM-0001", model.datatypes.String),
            _prop("YearOfConstruction", "2026", model.datatypes.String),
            _prop("CountryOfOrigin", "Simulated", model.datatypes.String),
        },
    )


def build_technical_data_submodel() -> model.Submodel:
    """Static specs: degrees of freedom, payload, reach."""
    return model.Submodel(
        id_=f"{NAMESPACE}/submodels/TechnicalData",
        id_short="TechnicalData",
        submodel_element={
            _prop("DegreesOfFreedom", 7, model.datatypes.Int),
            _prop("MaxPayloadKg", 3.0, model.datatypes.Double),
            _prop("ReachMeters", 0.855, model.datatypes.Double),
            _prop("MaxJointVelocityRadPerS", 2.62, model.datatypes.Double),
            _prop("ConveyorLengthMeters", 1.7, model.datatypes.Double),
        },
    )


def build_operational_state_submodel() -> model.Submodel:
    """Live operational values: joint positions, conveyor speed, cycle state.

    Values start at zero/defaults; the gateway writes real values into this
    submodel's properties as OPC UA telemetry arrives.
    """
    return model.Submodel(
        id_=f"{NAMESPACE}/submodels/OperationalState",
        id_short="OperationalState",
        submodel_element={
            _prop("Joint1PositionRad", 0.0, model.datatypes.Double),
            _prop("Joint2PositionRad", 0.0, model.datatypes.Double),
            _prop("Joint3PositionRad", 0.0, model.datatypes.Double),
            _prop("Joint4PositionRad", 0.0, model.datatypes.Double),
            _prop("Joint5PositionRad", 0.0, model.datatypes.Double),
            _prop("Joint6PositionRad", 0.0, model.datatypes.Double),
            _prop("Joint7PositionRad", 0.0, model.datatypes.Double),
            _prop("ConveyorSpeedMPerS", 0.0, model.datatypes.Double),
            _prop("TemperatureCelsius", 0.0, model.datatypes.Double),
            _prop("CycleState", "IDLE", model.datatypes.String),
        },
    )


def build_condition_monitoring_submodel() -> model.Submodel:
    """Computed OEE KPI: availability, performance, quality, and the product.

    All four values start at zero and are recomputed by the gateway from
    real measured uptime/downtime and cycle counts, never hardcoded.
    """
    return model.Submodel(
        id_=f"{NAMESPACE}/submodels/ConditionMonitoring",
        id_short="ConditionMonitoring",
        submodel_element={
            _prop("Availability", 0.0, model.datatypes.Double),
            _prop("Performance", 0.0, model.datatypes.Double),
            _prop("Quality", 0.0, model.datatypes.Double),
            _prop("OEE", 0.0, model.datatypes.Double),
            _prop("TotalCycleCount", 0, model.datatypes.Int),
            _prop("GoodCycleCount", 0, model.datatypes.Int),
        },
    )


def build_asset_shell(submodels: list[model.Submodel]) -> model.AssetAdministrationShell:
    """Build the AAS shell referencing all four submodels."""
    asset_information = model.AssetInformation(
        asset_kind=model.AssetKind.INSTANCE,
        global_asset_id=f"{NAMESPACE}/assets/FR3-SIM-0001",
    )
    return model.AssetAdministrationShell(
        id_=f"{NAMESPACE}/shells/FR3-SIM-0001",
        id_short="Fr3CellShell",
        asset_information=asset_information,
        submodel={model.ModelReference.from_referable(sm) for sm in submodels},
    )
