"""CE 2.1.1 BJMM disjoint-weight loops with block probability inside the min.

The constraint ranges and inner costs follow upstream BJMMdw/BJMMpdw. The
outer success exponent is replaced before choosing hidden l1/l2 constraints;
their memory is checked in the requested units before that minimum. This
local adapter leaves the ordinary CE backend unchanged.
"""

from math import ceil, inf, log2
from types import SimpleNamespace

from .unbalanced import optimize_outer


def install_disjoint_outer(algorithm, profile):
    from cryptographic_estimators.SDEstimator.sd_helper import (
        _gaussian_elimination_complexity, _list_merge_complexity,
        _mem_matrix, _mitm_nn_complexity,
        binom as comb,
    )

    partial = type(algorithm).__name__ == "BJMMpdw"
    n, k, w = algorithm.problem.get_parameters()
    algorithm._time_complexity_is_convex = False

    def evaluate(parameters, verbose_information=None, *, return_details=False):
        if partial and len(parameters) == 1:
            return None if return_details else (inf, inf)
        par = SimpleNamespace(**parameters)
        local_time, local_memory, selected = inf, inf, None
        radius = algorithm._adjust_radius
        radius1, radius2 = (max(1, radius//2) if partial else radius), max(1, radius//2)
        start1 = algorithm._choose_first_constraint_such_that_representations_cancel_out_exactly(parameters)
        if start1 == -1:
            return None if return_details else (inf, inf)
        low1 = max(0, start1-radius1) if partial else max(start1-radius1, par.w1, par.w11)
        for l1 in range(low1, start1+radius1):
            if 2*l1 >= n-k or n-k-2*l1 < w:
                continue
            half = (k+l1)//2 if partial else k//2
            if partial and (half-par.p < 0 or half-par.p < par.p1-par.p//2):
                continue
            reps = (comb(par.p, par.p//2)*comb(half-par.p, par.p1-par.p//2))**2
            if not partial:
                reps *= (comb(par.w1, par.w1//2)*comb(l1-par.w1, par.w11-par.w1//2))**2
                reps = max(reps, 1)
            first = comb(half, par.p1)
            if algorithm._is_early_abort_possible(log2(first)):
                # This lower bound excludes this l1, not an earlier feasible
                # hidden constraint already visited for the same tuple.
                continue
            second = (max(first**2//2**l1, 1) if partial else
                      max(first**2*comb(l1, par.w11)**2//2**(2*l1), 1))
            memory = log2(2*first+second+_mem_matrix(n, k, par.r))
            # CE's outer search compares bit memory with a strict bound. Do
            # that before minimizing hidden constraints, so an oversized
            # fastest l1 cannot mask a slower, feasible l1 for this tuple.
            bounded_memory = (algorithm.problem.to_bitcomplexity_memory(memory)
                              if algorithm.bit_complexities else memory)
            if bounded_memory >= algorithm.problem.memory_bound:
                continue
            start2 = algorithm._choose_second_constraint_such_that_list_size_remains_constant(parameters, second)
            if start2 == -1:
                continue
            information_weight = 2*par.p+2*par.w2+(0 if partial else 2*par.w1)
            constraint1 = l1 if partial else 2*l1
            max2 = (n-k-constraint1-(w-information_weight))//2
            upper2 = min(max2, start2+radius2)
            if not partial:
                upper2 = max(1, upper2)
            for l2 in range(max(par.w2, start2-radius2), upper2):
                tail = n-k-constraint1-2*l2
                uniform = (log2(comb(tail, w-information_weight))
                           + 2*log2(comb(half, par.p))
                           + 2*log2(comb(l2, par.w2))-log2(comb(n, w)))
                if not partial:
                    uniform += 2*log2(comb(l1, par.w1))
                before = max(0.0, -uniform-algorithm.problem.nsolutions)
                gaussian = _gaussian_elimination_complexity(n, k, par.r)
                tree = ((2*_list_merge_complexity(first, l1, algorithm._hmap)) if partial else
                        (2*_mitm_nn_complexity(first, 2*l1, 2*par.w11, algorithm._hmap)))
                tree += _mitm_nn_complexity(second, 2*l2, 2*par.w2, algorithm._hmap)
                repeats = int(ceil(2**max(constraint1-log2(reps), 0)))
                iteration = log2(gaussian+repeats*tree)
                uniform_total = (log2(comb(tail, w-information_weight))
                                 + log2(comb(n-tail, information_weight))-log2(comb(n, w)))
                lower = iteration+max(0.0, uniform_total-uniform-algorithm.problem.nsolutions)
                if lower >= local_time or algorithm._is_early_abort_possible(lower):
                    continue
                outer = optimize_outer(profile, tail, information_weight)
                after = max(0.0, -uniform-outer.gain-algorithm.problem.nsolutions)
                time = after+iteration
                if time < local_time:
                    local_time, local_memory = time, memory
                    selected = {
                        **outer.to_dict(), "applied": True, "strategy": "block_allocation",
                        "tail_size": tail, "information_weight": information_weight,
                        "log2_permutations_before": before, "log2_permutations_after": after,
                        "log2_repetition_gain": before-after,
                        "hidden_constraints": {"l1": l1, "l2": l2},
                        "inner_costs": "CE 2.1.1 disjoint-weight list and representation costs unchanged",
                        "search": "block probability evaluated inside CE finite l1/l2 constraint loops",
                    }
                    if verbose_information is not None:
                        verbose_information.update({
                            "constraints": [constraint1, 2*l2], "permutations": after,
                            "tree": log2(repeats*tree), "gauss": log2(gaussian),
                            "representations": reps,
                            "lists": [log2(first), log2(second),
                                      2*log2(second)+(0 if partial else log2(comb(2*l2, 2*par.w2))-2*l2)],
                        })
        return selected if return_details else (local_time, local_memory)

    algorithm._time_and_memory_complexity = evaluate
    return lambda parameters: evaluate(parameters, return_details=True)
