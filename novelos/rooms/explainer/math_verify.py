"""Real mathematical verification for explainer scripts.

This is not a format check: it solves the system itself (Cramer's rule,
exact Fractions) and re-derives every step of every method from the
system's equations, so a wrong answer or a wrong intermediate step is
rejected even when the JSON shape is perfect.

Step semantics (see schema.MathStep):
- given / rearrange: equation must be a nonzero scalar multiple of the
  named system equation (sources[0] = 0 or 1).
- substitute: sources[0] names an earlier step; `relation` (var = coeff *
  other + const) is substituted into that step's equation, symbolically,
  and the result must equal this step's equation exactly.
- add / subtract: equation must equal the coefficient-wise sum/difference
  of the two named earlier steps.
- scale: equation must equal factor * the named earlier step's equation.
- read: equation must be a single-variable equation (var = value) that is
  factor * the named earlier step, and the value must be the solution.
- row_op: R_target <- R_target + factor * R_source on the method's
  augmented matrix (tracked step by step); the equation must equal the
  resulting row, and the starting matrix must be the system itself.

Every step equation must also be satisfied by the solution, and every
method's final result must equal the solved solution.
"""

from __future__ import annotations

from fractions import Fraction

from .schema import ExplainerScript, LinearSystem, LinEq


def system_equations(sys: LinearSystem) -> list[LinEq]:
    return [LinEq(x=sys.a, y=sys.b, const=sys.c), LinEq(x=sys.d, y=sys.e, const=sys.f)]


def solve_system(sys: LinearSystem) -> dict[str, Fraction]:
    """Exact solution of a 2x2 linear system; raises ValueError if singular."""
    det = Fraction(sys.a * sys.e - sys.b * sys.d)
    if det == 0:
        raise ValueError("system has no unique solution (determinant is 0)")
    x = Fraction(sys.c * sys.e - sys.b * sys.f, 1) / det
    y = Fraction(sys.a * sys.f - sys.c * sys.d, 1) / det
    return {"x": x, "y": y}


def _frac(eq: LinEq) -> tuple[Fraction, Fraction, Fraction]:
    return Fraction(eq.x), Fraction(eq.y), Fraction(eq.const)


def _proportional(a: LinEq, b: LinEq) -> bool:
    """True when a == k*b for some nonzero rational k (same line)."""
    ax, ay, ac = _frac(a)
    bx, by, bc = _frac(b)
    if bx == 0 and by == 0 and bc == 0:
        return ax == 0 and ay == 0 and ac == 0
    if bx != 0:
        k = ax / bx
    elif by != 0:
        k = ay / by
    else:
        k = ac / bc
    return k != 0 and (k * bx, k * by, k * bc) == (ax, ay, ac)


def _satisfies(eq: LinEq, sol: dict[str, Fraction]) -> bool:
    return Fraction(eq.x) * sol["x"] + Fraction(eq.y) * sol["y"] == Fraction(eq.const)


def _substitute(eq: LinEq, var: str, coeff: int, const: int) -> LinEq:
    """Replace `var` by (coeff * other + const) in eq; return standard form."""
    x, y, c = _frac(eq)
    if var == "x":
        # a*(coeff*y + const) + b*y = c  ->  (a*coeff + b)*y = c - a*const
        return _frac_eq(Fraction(0), x * coeff + y, c - x * const)
    # a*x + b*(coeff*x + const) = c  ->  (a + b*coeff)*x = c - b*const
    return _frac_eq(x + y * coeff, Fraction(0), c - y * const)


def _frac_eq(x: Fraction, y: Fraction, c: Fraction) -> LinEq:
    """Build a LinEq from Fractions; fails loudly if a value is not integral
    (scripts are integer problems — a fractional step equation is a bug)."""
    if x.denominator != 1 or y.denominator != 1 or c.denominator != 1:
        raise ValueError(f"non-integer step equation: {x}*x + {y}*y = {c}")
    return LinEq(x=int(x), y=int(y), const=int(c))


def _parse_factor(raw: str) -> Fraction:
    try:
        return Fraction(raw.strip())
    except (ValueError, ZeroDivisionError) as e:
        raise ValueError(f"bad factor {raw!r}") from e


def verify_method(sys: LinearSystem, method, solution: dict[str, Fraction]) -> list[str]:
    """Verify one method; returns a list of problems (empty = verified)."""
    issues: list[str] = []
    eqs = system_equations(sys)
    steps = method.steps
    derived: list[LinEq] = []  # equations established by earlier steps
    matrix: list[list[Fraction]] | None = None
    if method.matrix is not None:
        if [list(map(int, row)) for row in method.matrix] != [[sys.a, sys.b, sys.c], [sys.d, sys.e, sys.f]]:
            issues.append(f"method {method.kind}: matrix is not the system itself")
        matrix = [[Fraction(v) for v in row] for row in method.matrix]

    for i, st in enumerate(steps):
        tag = f"method {method.kind} step {i + 1} ({st.op})"
        try:
            if st.op in ("given", "rearrange"):
                if len(st.sources) != 1 or st.sources[0] not in (0, 1):
                    issues.append(f"{tag}: sources must name one system equation (0 or 1)")
                elif not _proportional(st.equation, eqs[st.sources[0]]):
                    issues.append(f"{tag}: equation is not the system equation {st.sources[0]}")
            elif st.op == "substitute":
                if st.relation is None or len(st.sources) != 1 or not 0 <= st.sources[0] < len(derived):
                    issues.append(f"{tag}: needs one earlier step + a relation")
                else:
                    rel = st.relation
                    sol_v, sol_w = solution[rel.var], solution["y" if rel.var == "x" else "x"]
                    if sol_v != rel.coeff * sol_w + rel.const:
                        issues.append(f"{tag}: relation {rel.var} = {rel.coeff}*other + {rel.const} "
                                      f"is false at the solution")
                    want = _substitute(derived[st.sources[0]], rel.var, rel.coeff, rel.const)
                    if _frac(st.equation) != _frac(want):
                        issues.append(f"{tag}: substituting into step {st.sources[0] + 1} gives "
                                      f"{want.x}*x + {want.y}*y = {want.const}, not "
                                      f"{st.equation.x}*x + {st.equation.y}*y = {st.equation.const}")
            elif st.op in ("add", "subtract"):
                if len(st.sources) != 2 or any(not 0 <= s < len(derived) for s in st.sources):
                    issues.append(f"{tag}: needs two earlier steps")
                else:
                    e1, e2 = (derived[st.sources[0]], derived[st.sources[1]])
                    sign = 1 if st.op == "add" else -1
                    want = LinEq(x=e1.x + sign * e2.x, y=e1.y + sign * e2.y,
                                 const=e1.const + sign * e2.const)
                    if _frac(st.equation) != _frac(want):
                        issues.append(f"{tag}: {st.op} of steps {st.sources[0] + 1},{st.sources[1] + 1} gives "
                                      f"{want.x}*x + {want.y}*y = {want.const}")
            elif st.op == "scale":
                if len(st.sources) != 1 or not 0 <= st.sources[0] < len(derived):
                    issues.append(f"{tag}: needs one earlier step")
                else:
                    k = _parse_factor(st.factor)
                    e = derived[st.sources[0]]
                    want = _frac_eq(k * e.x, k * e.y, k * e.const)
                    if _frac(st.equation) != _frac(want):
                        issues.append(f"{tag}: scaling step {st.sources[0] + 1} by {st.factor} does not give "
                                      f"this equation")
            elif st.op == "read":
                if len(st.sources) != 1 or not 0 <= st.sources[0] < len(derived):
                    issues.append(f"{tag}: needs one earlier step")
                else:
                    k = _parse_factor(st.factor)
                    e = derived[st.sources[0]]
                    want = _frac_eq(k * e.x, k * e.y, k * e.const)
                    if _frac(st.equation) != _frac(want):
                        issues.append(f"{tag}: reading step {st.sources[0] + 1} x {st.factor} gives "
                                      f"{want.x}*x + {want.y}*y = {want.const}")
                    elif not ((st.equation.x != 0) ^ (st.equation.y != 0)):
                        issues.append(f"{tag}: a read-off must isolate exactly one variable")
                    else:
                        var = "x" if st.equation.x != 0 else "y"
                        value = Fraction(st.equation.const, getattr(st.equation, var))
                        if value != solution[var]:
                            issues.append(f"{tag}: read {var} = {value}, but the solution is {solution[var]}")
            elif st.op == "row_op":
                if matrix is None or st.row_op is None:
                    issues.append(f"{tag}: row_op needs the matrix and a row_op")
                else:
                    ro = st.row_op
                    if not (0 <= ro.target < len(matrix) and 0 <= ro.source < len(matrix)):
                        issues.append(f"{tag}: row index out of range")
                    else:
                        matrix[ro.target] = [matrix[ro.target][j] + ro.factor * matrix[ro.source][j]
                                            for j in range(3)]
                        want = _frac_eq(*matrix[ro.target])
                        if _frac(st.equation) != _frac(want):
                            issues.append(f"{tag}: row operation gives "
                                          f"{want.x}*x + {want.y}*y = {want.const}")
            else:  # pragma: no cover - pydantic Literal already rejects this
                issues.append(f"{tag}: unknown op")
        except ValueError as e:
            issues.append(f"{tag}: {e}")
        derived.append(st.equation)
        if not _satisfies(st.equation, solution):
            issues.append(f"{tag}: equation {st.equation.x}*x + {st.equation.y}*y = "
                          f"{st.equation.const} is not satisfied by the solution")

    if {k: Fraction(v) for k, v in method.result.items()} != solution:
        issues.append(f"method {method.kind}: result {method.result} != solution "
                      f"{{'x': {solution['x']}, 'y': {solution['y']}}}")
    return issues


def verify_script(script: ExplainerScript) -> list[str]:
    """Verify a whole script; returns problems (empty = the maths is right)."""
    try:
        solution = solve_system(script.system)
    except ValueError as e:
        return [f"system: {e}"]
    issues: list[str] = []
    if {k: Fraction(v) for k, v in script.solution.items()} != solution:
        issues.append(f"script solution {script.solution} != solved solution "
                      f"{{'x': {solution['x']}, 'y': {solution['y']}}}")
    for method in script.methods:
        issues += verify_method(script.system, method, solution)
    return issues
