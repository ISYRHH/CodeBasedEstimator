"""Scheme adapter contract and deliberately synthetic demo instances."""

from typing import Protocol

from .models import AttackInstance, Problem


class SchemeAdapter(Protocol):
    """Return distinct justified routes; do not equate decoding and recovery.

    A real adapter must explain candidate verification, postprocessing and
    success assumptions. Missing structural attacks must stay explicit.
    """

    def instances(self, parameter_set: str, goal: str) -> list[AttackInstance]: ...


class DemoScheme:
    """Interface example only: these parameters describe no NGCC submission."""

    def instances(self, parameter_set: str, goal: str) -> list[AttackInstance]:
        if goal not in ("key_recovery", "msg_recovery"):
            raise ValueError("goal must be key_recovery or msg_recovery")
        if parameter_set == "hamming":
            problem = Problem("sd", {"n": 40, "k": 20, "w": 5 if goal == "key_recovery" else 4}, 0)
        elif parameter_set == "qary":
            problem = Problem("sd", {"n": 40, "k": 20, "w": 4, "q": 3}, 0)
        elif parameter_set == "rank":
            problem = Problem("rank_sd", {"q": 2, "m": 8, "n": 8, "k": 4, "r": 2})
        else:
            raise ValueError("demo parameter_set must be hamming, qary or rank")
        return [AttackInstance(
            name=f"toy-{parameter_set}/{goal}", scheme="synthetic-demo",
            parameter_set=parameter_set, goal=goal, problem=problem,
            route="synthetic decoding subproblem; no scheme recovery reduction claimed",
            assumptions=("Synthetic parameters; scheme-level recovery and validation are not modeled.",),
        )]
