"""One report per attack instance, with independent classical/quantum selections."""

from __future__ import annotations

from typing import Optional

from .models import AttackInstance, AttackModel, Options, Report


def estimate(
    instance: AttackInstance, *, options: Optional[Options] = None,
    classical_model: Optional[AttackModel] = None,
    quantum_model: Optional[AttackModel] = None,
) -> Report:
    """Pass the same tagged instance to each backend before its optimization.

    Backends use separate algorithm lists. There is no postprocessing discount
    for DOOM: its interpretation belongs to the selected attack algorithm.
    """
    options = options or Options()
    if options.classical_algorithms == () and not options.quantum_algorithms:
        raise ValueError("select at least one classical or quantum algorithm")
    backends = {}
    results = []
    if options.classical_algorithms != ():
        if classical_model is None:
            from .backend import ClassicalModel, backend_info

            classical_model = ClassicalModel()
            backends["classical"] = backend_info()
        else:
            backends["classical"] = {"name": classical_model.name}
        results.extend(classical_model.estimate(instance, options))
    if options.quantum_algorithms:
        if quantum_model is None:
            from .quantum import QuantumModel

            quantum_model = QuantumModel()
            backends["quantum"] = {"name": quantum_model.name, "implementation": "pending"}
        else:
            backends["quantum"] = {"name": quantum_model.name}
        results.extend(quantum_model.estimate(instance, options))
    return Report(instance, options, backends, results)
