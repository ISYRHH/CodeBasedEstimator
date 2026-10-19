"""Optimize a fixed MAGE tree's target batch under independent target failures.

The integer objective is ``D*u + (A+B*u)/(1-(1-S)**u)``.  Its successive
differences change sign once, so binary search needs O(log(maximum)) scalar
comparisons and does not reevaluate the probability tree.  Comparisons use
positive terms in logarithmic form, with an adaptive Decimal fallback near a
tie.  See ``docs/model.md`` for the cost convention and the distinction
between model independence and actual shared-tree events.
"""

from __future__ import annotations

from decimal import Decimal, MAX_EMAX, MIN_EMIN, localcontext
from fractions import Fraction
from math import exp, expm1, inf, isfinite, log, log1p, log2, ulp


_LOG2_E = log2(exp(1.0))
_LOG_2 = log(2.0)
_LOG10_2 = log(2.0, 10.0)


def _logadd(left, right):
    top = max(left, right)
    if top in (-inf, inf):
        return top
    return top + log2(1.0 + 2.0 ** (min(left, right) - top))


def _hazard_logs(log_probability):
    """Return log2(lambda), log2(lambda-S), retaining the small second term."""
    if log_probability < -50:
        return log_probability, 2 * log_probability - 1.0
    probability = 2.0 ** log_probability
    if log_probability > -1e-16:
        # Avoid multiplying a subnormal log(S) by ln(2).  The omitted
        # correction is O(abs(log(S))) and below binary64 precision here.
        hazard = -log(-log_probability) - log(_LOG_2)
    elif log_probability > -1:
        # log(S) is supplied, so -expm1(log(S)) retains 1-S near S=1.
        hazard = -log(-expm1(log_probability * _LOG_2))
    else:
        hazard = -log1p(-probability)
    if probability < 0.25:
        # 2*(lambda-S)/S**2 = sum_{j>=0} 2*S**j/(j+2).
        power, total, index = 1.0, 1.0, 2
        while True:
            power *= probability
            index += 1
            updated = total + 2.0 * power / index
            if updated == total:
                break
            total = updated
        difference = 2 * log_probability - 1 + log2(total)
    else:
        difference = log2(hazard - probability)
    return log2(hazard), difference


def _log_expm1(log_argument):
    if log_argument < -50:
        return log_argument
    if log_argument > 1023:
        return inf
    argument = 2.0 ** log_argument
    if argument > 50:
        return argument * _LOG2_E
    return log2(expm1(argument))


def _log_expm1_minus_argument(log_argument):
    """Log2(exp(x)-1-x), including x that cannot be represented as a float."""
    if log_argument < -50:
        return 2 * log_argument - 1.0
    if log_argument > 1023:
        return inf
    argument = 2.0 ** log_argument
    if argument < 0.25:
        # 2*(exp(x)-1-x)/x**2 = 1 + x/3 + x**2/12 + ... .
        term, total, index = 1.0, 1.0, 2
        while True:
            index += 1
            term *= argument / index
            updated = total + term
            if updated == total:
                break
            total = updated
        return 2 * log_argument - 1 + log2(total)
    if argument > 50:
        return argument * _LOG2_E
    return log2(expm1(argument) - argument)


def _log_survival(log_hazard):
    if log_hazard < -50:
        return log_hazard
    if log_hazard > 10:
        return 0.0
    return log2(-expm1(-(2.0 ** log_hazard)))


def _decimal_expm1(argument):
    if abs(argument) > Decimal("0.25"):
        return argument.exp() - 1
    term = total = argument
    index = 1
    while True:
        index += 1
        term *= argument / index
        updated = total + term
        if updated == total:
            return total
        total = updated


def _decimal_expm1_minus_argument(argument):
    if argument > Decimal("0.25"):
        return argument.exp() - 1 - argument
    term = total = argument * argument / 2
    index = 2
    while True:
        index += 1
        term *= argument / index
        updated = total + term
        if updated == total:
            return total
        total = updated


class _DifferenceSign:
    """Sign of the consecutive cost difference, computed as sign(H(u)-A).

    With lambda=-ln(1-S), x=lambda*u and P(u)=1-exp(-x),
    H(u) = [D*expm1(x)*P(u+1) + B*(expm1(x)-u*S)]/S.
    Both terms increase strictly with u.  For stable evaluation, write
    expm1(x)-u*S = (expm1(x)-x) + u*(lambda-S), a sum of positive terms.
    Thus a binary search finds the first nonnegative integer difference.
    """

    def __init__(self, log_probability, shared_cost, per_target_cost, conversion):
        self.log_probability = log_probability
        self.shared = shared_cost
        self.per_target = per_target_cost
        self.conversion = conversion
        self.log_shared = log2(shared_cost)
        self.log_target = (log2(per_target_cost.numerator)
                           - log2(per_target_cost.denominator))
        self.log_conversion = log2(conversion)
        self.log_hazard, self.log_difference = _hazard_logs(log_probability)
        self.log_scale = max(1.0, abs(log_probability), abs(self.log_shared),
                             abs(self.log_conversion),
                             log2(per_target_cost.numerator),
                             log2(per_target_cost.denominator))
        self.decimal_parameters = {}

    def __call__(self, targets):
        log_targets = log2(targets)
        log_argument = self.log_hazard + log_targets
        conversion_term = (self.log_conversion + _log_expm1(log_argument)
                           + _log_survival(self.log_hazard + log2(targets + 1))
                           - self.log_probability)
        target_term = (self.log_target
                       + _logadd(_log_expm1_minus_argument(log_argument),
                                 log_targets + self.log_difference)
                       - self.log_probability)
        log_threshold = _logadd(conversion_term, target_term)
        # Cancellation of large logarithms can affect the final comparison;
        # the fallback threshold accounts for their scale, not just the result.
        tolerance = 128 * ulp(max(self.log_scale, abs(log_targets)))
        difference = log_threshold - self.log_shared
        if abs(difference) > tolerance:
            return 1 if difference > 0 else -1
        return self._decimal_sign(targets)

    def _parameters_at_precision(self, precision):
        if precision in self.decimal_parameters:
            return self.decimal_parameters[precision]
        logarithm = Decimal.from_float(self.log_probability) * Decimal(2).ln()
        probability = logarithm.exp()
        if probability < Decimal("0.25"):
            # Store lambda-S separately: lambda itself may round to S.
            power = probability * probability
            difference = power / 2
            index = 2
            while True:
                power *= probability
                index += 1
                updated = difference + power / index
                if updated == difference:
                    break
                difference = updated
            hazard = probability + difference
        else:
            failure = (-_decimal_expm1(logarithm)
                       if logarithm > Decimal("-0.25") else 1 - probability)
            hazard = -failure.ln()
            difference = hazard - probability
        target_cost = (Decimal(self.per_target.numerator)
                       / Decimal(self.per_target.denominator))
        result = probability, hazard, difference, target_cost
        self.decimal_parameters[precision] = result
        return result

    def _exact_binary_sign(self, targets):
        """Resolve cheap exact ties when the supplied probability is 2**(-m)."""
        if not self.log_probability.is_integer():
            return None
        exponent = -int(self.log_probability)
        if exponent * targets > 65536:
            return None
        probability = Fraction(1, 1 << exponent)
        failure = 1 - probability
        tree_failure = failure ** targets
        success = 1 - tree_failure
        next_success = 1 - failure * tree_failure
        numerator = (self.conversion * success * next_success
                     + self.per_target * (success - targets * probability * tree_failure)
                     - self.shared * probability * tree_failure)
        return (numerator > 0) - (numerator < 0)

    def _decimal_sign(self, targets):
        # Enough significant digits to distinguish neighboring integers even
        # when float(log2(u)) == float(log2(u+1)); add a generous guard margin.
        precision = max(80, int(targets.bit_length() * _LOG10_2) + 60)
        for attempt in range(4):
            with localcontext() as context:
                context.prec = precision
                context.Emax, context.Emin = MAX_EMAX, MIN_EMIN
                probability, hazard, difference, target_cost = (
                    self._parameters_at_precision(precision))
                count = Decimal(targets)
                argument = hazard * count
                next_argument = hazard * Decimal(targets + 1)
                threshold = (
                    Decimal(self.conversion) * _decimal_expm1(argument)
                    * (-_decimal_expm1(-next_argument))
                    + target_cost * (_decimal_expm1_minus_argument(argument)
                                     + count * difference)
                ) / probability
                residual = threshold - Decimal(self.shared)
                # This is a numerical guard, not a certified interval bound.
                tolerance = max(threshold, Decimal(self.shared)).scaleb(-precision + 20)
                if abs(residual) > tolerance:
                    return 1 if residual > 0 else -1
            if attempt == 0:
                exact = self._exact_binary_sign(targets)
                if exact is not None:
                    return exact
            precision *= 2
        # An unresolved tie is far below the reported binary64 cost precision.
        # Favor the smaller batch; do not claim interval-certified exactness.
        return 0


def optimal_target_batch(log_probability, shared_cost, per_target_cost,
                         conversion_per_target, maximum):
    """Return a numerically verified integer minimum for a fixed tree.

    ``log_probability`` is log2(S); A=``shared_cost`` and
    D=``conversion_per_target`` are positive integers; B=``per_target_cost``
    is a positive Fraction; ``maximum`` is the available, memory-feasible cap.
    The supplied floating log probability defines the probability model for
    this calculation.  Binary search is exact with exact signs; the practical
    implementation uses adaptive precision, resolving cheap rational ties
    exactly and treating exceptionally unresolved differences as ties.
    """
    if (type(shared_cost) is not int or shared_cost <= 0
            or type(conversion_per_target) is not int or conversion_per_target <= 0
            or type(maximum) is not int or maximum <= 0
            or not isinstance(per_target_cost, Fraction) or per_target_cost <= 0
            or not isinstance(log_probability, (float, int))
            or isinstance(log_probability, bool)
            or not isfinite(log_probability) or log_probability > 0):
        raise ValueError("invalid fixed-tree target-batch parameters")
    if maximum == 1 or log_probability == 0:
        return 1
    sign = _DifferenceSign(float(log_probability), shared_cost, per_target_cost,
                           conversion_per_target)
    lower, upper = 1, maximum
    while lower < upper:
        middle = (lower + upper) // 2
        if sign(middle) >= 0:
            upper = middle
        else:
            lower = middle + 1
    return lower
