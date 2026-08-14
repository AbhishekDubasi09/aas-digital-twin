"""AAS REST API v3.0 server, backed by basyx-python-sdk's official WSGI app.

Builds the object store containing the shell and its four submodels, and
exposes them through the standards-compliant AAS REST API rather than a
hand-rolled one.
"""

from __future__ import annotations

from basyx.aas import model
from basyx.aas.adapter.aasx import DictSupplementaryFileContainer
from basyx.aas.adapter.http import WSGIApp

from aas_digital_twin.aas.submodels import (
    build_asset_shell,
    build_condition_monitoring_submodel,
    build_nameplate_submodel,
    build_operational_state_submodel,
    build_technical_data_submodel,
)


def build_object_store() -> model.DictObjectStore:
    """Create the object store holding the shell and all four submodels."""
    nameplate = build_nameplate_submodel()
    technical_data = build_technical_data_submodel()
    operational_state = build_operational_state_submodel()
    condition_monitoring = build_condition_monitoring_submodel()
    shell = build_asset_shell([nameplate, technical_data, operational_state, condition_monitoring])

    store: model.DictObjectStore = model.DictObjectStore()
    store.add(shell)
    store.add(nameplate)
    store.add(technical_data)
    store.add(operational_state)
    store.add(condition_monitoring)
    return store


def build_wsgi_app(store: model.DictObjectStore) -> WSGIApp:
    """Wrap the object store in the AAS REST API v3.0 WSGI application."""
    file_store = DictSupplementaryFileContainer()
    return WSGIApp(object_store=store, file_store=file_store)


def run_dev_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Run the AAS REST API with werkzeug's development server."""
    from werkzeug.serving import run_simple

    store = build_object_store()
    app = build_wsgi_app(store)
    run_simple(host, port, app)


if __name__ == "__main__":
    run_dev_server()
