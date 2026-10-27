"""Shared wording for model conditions with the same meaning across backends."""

CLASSICAL_COST = "Random-code cost model with constant-cost memory access."
BLOCK_OUTER = (
    "Block weights affect only the outer success probability; "
    "inner costs and rank probabilities use the generic model."
)
BLOCK_SOLUTIONS = "All counted solutions match the supplied block weights, with uniform supports within each block."
SINGLE_SYNDROME = "Only one syndrome is modeled; no DOOM speedup is applied."
