"""Flip's calculator: exact math with SymPy.

What the brain sends is parsed by a small safe parser (never eval): only numbers, variables, + - * / ^,
and a fixed list of math functions get through.
"""

import ast
import logging
import re
import threading

log = logging.getLogger("flip")

TOOL = {
    "name": "math",
    "description": (
        "Exact calculator. Use it for ANY arithmetic, percentages, fractions, powers, roots, algebra, equations, "
        "trig, logs, statistics, probability and calculus instead of working numbers out in your head. "
        "op: evaluate (default) | solve | simplify | factor | expand | derivative | integral | limit. "
        "Write math like code: 2*x^2 + 3*x - 5, sqrt(2), 15% of 80 as 0.15*80, sin(30 deg), log(8, 2), "
        "binomial(10, 3), mean(1, 2, 3). Equations use =, several are separated by ; (e.g. 'x+y=5; x-y=1')."
    ),
    "schema": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "The math, e.g. 59382*912 or 2*x+3=11"},
            "op": {"type": "string", "enum": ["evaluate", "solve", "simplify", "factor", "expand", "derivative",
                                              "integral", "limit"]},
            "variable": {"type": "string", "description": "For solve/derivative/integral/limit, e.g. x"},
            "lower": {"type": "string", "description": "Integral lower bound (optional)"},
            "upper": {"type": "string", "description": "Integral upper bound (optional)"},
            "to": {"type": "string", "description": "Limit: the value the variable goes to, e.g. 0 or oo"},
        },
        "required": ["expression"],
    },
}

MAX_LEN = 600
TIME_LIMIT = 8.0


class MathError(Exception):
    pass


def _sympy():
    import sympy as sp

    return sp


def _funcs(sp):
    def perm(n, k):
        return sp.factorial(n) / sp.factorial(n - k)

    def log(x, base=None):
        return sp.log(x) if base is None else sp.log(x, base)

    def stat(fn):
        def run(*xs):
            if len(xs) == 1 and isinstance(xs[0], (list, tuple)):
                xs = xs[0]
            return fn([sp.nsimplify(x) for x in xs])
        return run

    def mean(xs):
        return sum(xs) / len(xs)

    def median(xs):
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

    def variance(xs):  # sample variance
        m = mean(xs)
        return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)

    def pvariance(xs):
        m = mean(xs)
        return sum((x - m) ** 2 for x in xs) / len(xs)

    return {
        "sqrt": sp.sqrt, "cbrt": sp.cbrt, "root": sp.root, "exp": sp.exp, "ln": sp.log, "log": log,
        "log10": lambda x: sp.log(x, 10), "log2": lambda x: sp.log(x, 2),
        "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "sec": sp.sec, "csc": sp.csc, "cot": sp.cot,
        "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan,
        "atan2": sp.atan2, "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
        "abs": sp.Abs, "floor": sp.floor, "ceil": sp.ceiling, "ceiling": sp.ceiling, "round": lambda x, n=0: sp.Float(round(float(x), int(n))) if n else sp.Integer(round(float(x))),
        "factorial": sp.factorial, "binomial": sp.binomial, "comb": sp.binomial, "ncr": sp.binomial,
        "perm": perm, "npr": perm, "gcd": sp.gcd, "lcm": sp.lcm, "mod": sp.Mod, "isprime": lambda n: sp.Integer(1) if sp.isprime(int(n)) else sp.Integer(0),
        "factorint": None, "min": sp.Min, "max": sp.Max,
        "mean": stat(mean), "average": stat(mean), "median": stat(median),
        "variance": stat(variance), "pvariance": stat(pvariance),
        "stdev": stat(lambda xs: sp.sqrt(variance(xs))), "pstdev": stat(lambda xs: sp.sqrt(pvariance(xs))),
        "deg": lambda x: x * sp.pi / 180,
    }


def _prepare(text):
    """Everyday math notation → what the parser understands."""
    t = str(text).strip()
    if len(t) > MAX_LEN:
        raise MathError("that's too long for the calculator")
    t = (t.replace("×", "*").replace("·", "*").replace("÷", "/").replace("−", "-").replace("–", "-")
          .replace("^", "**").replace("√", "sqrt").replace("π", "pi").replace("∞", "oo").replace("²", "**2")
          .replace("³", "**3"))
    t = re.sub(r"(\d)\s*°", r"\1*pi/180", t)
    t = re.sub(r"(\d(?:[\d.]*))\s*(?:deg|degrees)\b", r"(\1*pi/180)", t)
    t = re.sub(r"(\d(?:[\d.]*))\s*%\s*of\b", r"(\1/100)*", t)          # 15% of 80
    t = re.sub(r"(\d(?:[\d.]*))\s*%(?!\s*[\d(a-zA-Z])", r"(\1/100)", t)  # 20% (not 10 % 3)
    t = re.sub(r"(\d),(\d{3})\b", r"\1\2", t)                              # 1,000 → 1000
    t = re.sub(r"(\d)\s*([a-zA-Z(])", r"\1*\2", t)                        # 2x, 3(4) → 2*x, 3*(4)
    t = re.sub(r"\)\s*([\w(])", r")*\1", t)                                # (a)(b), (a)x
    return t


class _Parser:
    def __init__(self, sp):
        self.sp = sp
        self.funcs = {k: v for k, v in _funcs(sp).items() if v is not None}
        self.consts = {"pi": sp.pi, "e": sp.E, "E": sp.E, "i": sp.I, "I": sp.I, "oo": sp.oo, "inf": sp.oo,
                       "infinity": sp.oo}
        self.symbols = {}

    def parse(self, text):
        try:
            tree = ast.parse(text.strip(), mode="eval")
        except SyntaxError:
            raise MathError(f"couldn't read {text!r}")
        return self._node(tree.body)

    def _symbol(self, name):
        if not re.fullmatch(r"[A-Za-z]\w{0,11}", name):
            raise MathError(f"unknown name {name!r}")
        return self.symbols.setdefault(name, self.sp.Symbol(name))

    def _node(self, n):
        sp = self.sp
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return sp.Integer(n.value) if isinstance(n.value, int) else sp.Rational(repr(n.value))
        if isinstance(n, ast.Name):
            if n.id in self.consts:
                return self.consts[n.id]
            if n.id.lower() in self.funcs:
                raise MathError(f"{n.id} needs brackets, like {n.id}(x)")
            return self._symbol(n.id)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = self._node(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = self._node(n.left), self._node(n.right)
            op = type(n.op)
            if op is ast.Add:
                return a + b
            if op is ast.Sub:
                return a - b
            if op is ast.Mult:
                return a * b
            if op is ast.Div:
                return a / b
            if op is ast.Pow:
                if b.is_number and abs(b) > 100000 or (a.is_number and b.is_number and abs(a) > 1 and abs(b) > 5000):
                    raise MathError("that power is too huge to work out exactly")
                return a ** b
            if op is ast.Mod:
                return sp.Mod(a, b)
            if op is ast.FloorDiv:
                return sp.floor(a / b)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords:
            name = n.func.id.lower()
            if name not in self.funcs:
                raise MathError(f"unknown function {n.func.id!r}")
            if len(n.args) > 500:
                raise MathError("too many numbers")
            args = [self._node(a) for a in n.args]
            if name == "factorial" and args and args[0].is_number and abs(args[0]) > 5000:
                raise MathError("that factorial is too huge")
            return self.funcs[name](*args)
        if isinstance(n, (ast.List, ast.Tuple)):
            return [self._node(e) for e in n.elts]
        raise MathError("the calculator only does math (numbers, letters, + - * / ^ and math functions)")


def _fmt(sp, value):
    """Exact answer, plus a decimal when that helps."""
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt(sp, v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k} = {_fmt(sp, v)}" for k, v in value.items())
    try:
        value = sp.nsimplify(value) if isinstance(value, sp.Float) and value == int(value) else value
    except (TypeError, ValueError):
        pass
    if value in (sp.zoo, sp.nan):
        return "undefined (like dividing by zero)"
    exact = str(value).replace("**", "^")
    try:
        if value.is_number and value.is_real and not value.is_Integer:
            dec = sp.N(value, 12)
            dec_s = str(dec).rstrip("0").rstrip(".") if "." in str(dec) and "e" not in str(dec) else str(dec)
            if dec_s != exact:
                return f"{exact} ≈ {dec_s}"
    except (AttributeError, TypeError):
        pass
    return exact


def _split_eq(sp, parser, text):
    if "<=" in text or ">=" in text or "<" in text or ">" in text:
        m = re.split(r"(<=|>=|<|>)", text, maxsplit=1)
        lhs, op, rhs = parser.parse(m[0]), m[1], parser.parse(m[2])
        return {"<": sp.Lt, ">": sp.Gt, "<=": sp.Le, ">=": sp.Ge}[op](lhs, rhs)
    if "==" in text:
        text = text.replace("==", "=")
    if "=" in text:
        lhs, rhs = text.split("=", 1)
        return sp.Eq(parser.parse(lhs), parser.parse(rhs))
    return sp.Eq(parser.parse(text), 0)


def _run(args):
    sp = _sympy()
    parser = _Parser(sp)
    op = (args.get("op") or "evaluate").lower().strip()
    raw = str(args.get("expression") or "").strip()
    if not raw:
        raise MathError("nothing to calculate")
    var = parser._symbol(args["variable"].strip()) if args.get("variable") else None

    if op == "solve" or (op == "evaluate" and re.search(r"[a-zA-Z]", raw) and re.search(r"(?<![<>=!])=(?!=)|[<>]", raw)):
        parts = [p for p in re.split(r";|\band\b", raw) if p.strip()]
        eqs = [_split_eq(sp, parser, _prepare(p)) for p in parts]
        symbols = sorted(set().union(*[e.free_symbols for e in eqs]), key=str)
        if not symbols:
            return "true" if all(bool(e) for e in eqs) else "false"
        if any(isinstance(e, sp.core.relational.Relational) and not isinstance(e, sp.Eq) for e in eqs):
            target = var or symbols[0]
            text = str(sp.reduce_inequalities(eqs, [target])).replace("**", "^")
            text = re.sub(r" & \((\w+) < oo\)| & \(-oo < (\w+)\)", "", text)
            text = re.sub(r"\(-oo < (\w+)\) & ", "", text).replace(" | ", " or ")
            text = re.sub(r"^\((\S+) < (\w+)\)$", r"\2 > \1", text)
            text = re.sub(r"^\((\S+) < (\w+)\) & \((\w+) < (\S+)\)$", r"\1 < \2 < \4", text)
            return text[1:-1] if text.startswith("(") and text.endswith(")") and text.count("(") == 1 else text
        targets = [var] if var and len(eqs) == 1 else symbols
        sol = sp.solve(eqs, targets, dict=True)
        if not sol:
            return "no solution"
        return " or ".join(_fmt(sp, s) for s in sol)

    expr = parser.parse(_prepare(raw))
    if isinstance(expr, list):
        return _fmt(sp, expr)
    free = sorted(expr.free_symbols, key=str)
    var = var or (free[0] if free else None)
    if op == "simplify":
        return _fmt(sp, sp.simplify(expr))
    if op == "factor":
        if expr.is_Integer:
            return " · ".join(f"{p}^{k}" if k > 1 else str(p) for p, k in sp.factorint(int(expr)).items())
        return _fmt(sp, sp.factor(expr))
    if op == "expand":
        return _fmt(sp, sp.expand(expr))
    if op == "derivative":
        return _fmt(sp, sp.diff(expr, var))
    if op == "integral":
        if args.get("lower") not in (None, "") and args.get("upper") not in (None, ""):
            a, b = parser.parse(_prepare(args["lower"])), parser.parse(_prepare(args["upper"]))
            return _fmt(sp, sp.integrate(expr, (var, a, b)))
        return _fmt(sp, sp.integrate(expr, var)) + " + C"
    if op == "limit":
        return _fmt(sp, sp.limit(expr, var, parser.parse(_prepare(args.get("to") or "0"))))
    # evaluate
    value = sp.simplify(expr) if free else expr
    if not free:
        value = sp.nsimplify(value) if value.is_Float else value
    return _fmt(sp, value)


def run(args):
    """The math tool: returns the answer as text (or what went wrong). Gives up after a few seconds."""
    out = {}

    def work():
        try:
            out["text"] = _run(args)
        except MathError as e:
            out["text"] = f"ERROR: {e}"
        except Exception as e:  # sympy can raise all sorts on weird input
            out["text"] = f"ERROR: couldn't work that out ({type(e).__name__}: {e})"[:300]

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(TIME_LIMIT)
    if "text" not in out:
        return "ERROR: that took too long to work out"
    return out["text"]


# Plain calculations in a message ("what's 59382 × 912?", "15% of 80", "solve 2x+3=11") are worked out
# before the brain even starts, so he never has to do them in his head or remember to use the tool.
_NUM = r"\(?-?\d[\d,]*(?:\.\d+)?\)?"
_CALC = re.compile(rf"{_NUM}(?:\s*(?:[-+*/×x÷^]|\*\*)\s*{_NUM})+|\d[\d.]*\s*%\s*of\s*\$?\d[\d,.]*|"
                   rf"(?:sqrt|√)\s*\(?\s*\d[\d.]*\s*\)?")


_SIDE = re.compile(r"^[\s\d.+\-*/^()a-z]+$")


def equations(text):
    """Clean equations in the message, like "2x + 3 = 11" or "x + y = 10 and x - y = 4" (only numbers,
    + - * / ^ and single-letter variables; anything wordier is left to the brain)."""
    out = []
    for piece in re.split(r"\band\b|;|,|\n|:|\?|\.(?!\d)", text.lower()):
        if piece.count("=") != 1:
            continue
        left, right = (x.strip() for x in piece.split("="))
        left = left.split()[-8:]  # drop leading words like "solve"
        while left and re.fullmatch(r"[a-z]{2,}", left[0]):
            left = left[1:]
        left = " ".join(left)
        if not left or not right or not _SIDE.match(left) or not _SIDE.match(right):
            continue
        if re.search(r"[a-z]{2,}", left + " " + right) or not re.search(r"[a-z]", left + right):
            continue
        out.append(f"{left} = {right}")
    return out


def precompute(text, limit=3):
    """[(what, answer)] for the calculations written plainly in the message."""
    found, seen = [], set()
    t = text.replace("×", "*").replace("÷", "/")
    for m in _CALC.finditer(t):
        expr = m.group(0).strip()
        if re.fullmatch(r"\d+\s*x\s*\d+", expr) and not re.search(r"\d\s*x\s*\d", text):  # "2 x 4" only as times
            continue
        expr = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", expr)
        if expr in seen or not re.search(r"[-+*/^%]|sqrt|√", expr) or re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", expr):
            continue  # "13-5" is probably a score
        seen.add(expr)
        answer = run({"expression": expr})
        if not answer.startswith("ERROR"):
            found.append((expr, answer))
    eqs = equations(text)
    if eqs:
        answer = run({"expression": "; ".join(eqs), "op": "solve"})
        if not answer.startswith("ERROR") and answer not in ("true", "false", "no solution"):
            found.append(("; ".join(eqs), answer))
    return found[:limit]
