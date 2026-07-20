import re
import ast
from functools import reduce


def handle_constant_array(code):
    function_wrapper_pattern = re.compile(
        r"local (\w+)\s*=\s*function\(([^)]*)\)\s*"
        r"return\s+\w+\([^,]+,\s*{([^}]+)}\s*,[^)]*\)\s*end",
        re.DOTALL,
    )

    array_decl_pattern = re.compile(r"local (\w+)\s*=\s*\{([^}]+)\}", re.DOTALL)

    code = function_wrapper_pattern.sub(
        lambda m: _simplify_function_wrapper(m.group(1), m.group(2), m.group(3)), code
    )

    for arr_match in array_decl_pattern.finditer(code):
        arr_name, items_str = arr_match.groups()
        items = [item.strip() for item in items_str.split(",") if item.strip()]

        access_pattern = re.compile(
            rf"{re.escape(arr_name)}\[(\w+)\s*([+\-])\s*(\d+)\]", re.DOTALL
        )

        code = access_pattern.sub(
            lambda m: resolve_array_access(items, m.group(1), m.group(2), m.group(3)),
            code,
        )

        code = code.replace(
            arr_match.group(0),
            f"-- Decompiled array: {arr_name}\nlocal {arr_name} = {{{', '.join(items)}}}",
        )

        print(f"Processed constant array '{arr_name}' with {len(items)} elements")

    code = re.sub(
        r"local function \w+\(a\)\s*"
        r"return \w+\[a[ ]?[+\-][ ]?\d+\]\s*"
        r"end",
        "",
        code,
        flags=re.DOTALL,
    )

    code = re.sub(
        r"(\w+)=(\w+)\[([^\]]+)\]",
        lambda m: _resolve_variable_assignment(m.group(1), m.group(2), m.group(3)),
        code,
    )

    code = re.sub(
        r"(\w+)\s*=\s*{([^}]+)}",
        lambda m: _simplify_tuple_assignment(m.group(1), m.group(2)),
        code,
    )

    code = re.sub(
        r"(\w+)\s*([<>]=?|==?)\s*([\d+\-*/ ]+)",
        lambda m: _evaluate_arithmetic_condition(m.group(1), m.group(2), m.group(3)),
        code,
    )

    code = re.sub(
        r"(\w+\[[^\]]+\])\s*=\s*\1\s*([+\-*/])\s*([^\s;]+)",
        lambda m: _simplify_arithmetic_assignment(m.group(1), m.group(2), m.group(3)),
        code,
    )

    code = re.sub(
        r"local\s+(\w+)\s*=\s*(\w+)\(([^)]+)\)",
        lambda m: _simplify_local_declaration(m.group(1), m.group(2), m.group(3)),
        code,
    )

    code = _simplify_function_parameters(code)
    code = _normalize_table_access(code)
    code = _simplify_function_calls(code)
    code = _format_multiple_assignments(code)
    code = _format_chained_calls(code)
    code = _process_complex_calls(code)

    return code


def _simplify_function_wrapper(name, params, inner_params):
    print(f"Found wrapped function: {name}, {params}, {inner_params}")

    cleaned_params = re.split(r"[;,]", inner_params)
    cleaned_params = [p.strip() for p in cleaned_params if p.strip()]

    return (
        f"local {name}=function({params})\n"
        f"    return {name}({', '.join(cleaned_params)})\n"
        f"end"
    )


def resolve_array_access(items, var, op, offset):
    try:
        idx = ast.literal_eval(var)
    except ValueError:
        return f"{items[0]}"

    offset = int(offset)
    if op == "-":
        idx -= offset
    else:
        idx += offset

    if 0 <= idx < len(items):
        return items[idx]
    return f"{items[0]}"


def _resolve_variable_assignment(var_name, array_name, index_expr):
    try:
        idx = ast.literal_eval(index_expr)
        return f"{var_name} = {array_name}[{idx}]"
    except:
        return f"{var_name} = {array_name}[{index_expr}]"


def _simplify_tuple_assignment(var_name, elements):
    return (
        f"local {var_name} = {{{', '.join([e.strip() for e in elements.split(',')])}}}"
    )


def _evaluate_arithmetic_condition(var, operator, expr):
    try:
        result = ast.literal_eval(expr)
        return f"{var} {operator} {result}"
    except:
        return f"{var} {operator} {expr}"


def _simplify_arithmetic_assignment(lvalue, operator, expr):
    try:
        clean_expr = re.sub(r"([^)\d])([a-zA-Z_]+)$", r"\1", expr)
        value = ast.literal_eval(clean_expr)
        return f"{lvalue} {operator}= {value}"
    except SyntaxError:
        if re.match(r"0[xX][0-9a-fA-F]+", expr):
            return f"{lvalue} = {lvalue} {operator} {expr}"
    except:
        return f"{lvalue} = {lvalue} {operator} {expr}"


def _simplify_local_declaration(var_name, func_name, args):
    try:
        eval_args = ast.literal_eval(args)
        return f"local {var_name} = {func_name}({eval_args})"
    except:
        return f"local {var_name} = {func_name}({args})"


def _simplify_function_parameters(code):
    return re.sub(
        r"\bfunction\(([^)]+)\)",
        lambda m: f"function({', '.join([p.strip() for p in m.group(1).split(',')])})",
        code,
    )


def _normalize_table_access(code):
    code = re.sub(
        r"(\w+)\[([A-Za-z_]+)\]",
        lambda m: f"{m.group(1)}.{m.group(2)}"
        if m.group(2).isidentifier()
        else m.group(0),
        code,
    )
    # Handle table.method calls
    code = re.sub(
        r"(\w+)\.(\w+)\s*=\s*\1\.\2\s*([+\-*/])\s*([\d]+)",
        lambda m: f"{m.group(1)}.{m.group(2)} {m.group(3)}= {m.group(4)}",
        code,
    )
    return code


def _simplify_function_calls(code):
    code = re.sub(
        r"return\((\w+)\(([^)]+)\)\)\((\w+)\((\w+)\)\)",
        lambda m: f"return {m.group(1)}({_try_eval(m.group(2))})({m.group(3)}({m.group(4)}))",
        code,
    )
    return code


def _try_eval(expr):
    try:
        return str(ast.literal_eval(expr))
    except:
        return expr


def _format_multiple_assignments(code):
    return re.sub(
        r"(\w+)\s*=\s*(\w+)\(\)\s*([^\s=]+)\[(\w+)\]\s*=\s*([^\s;]+)",
        lambda m: f"local {m.group(1)} = {m.group(2)}()\n{m.group(3)}[{m.group(4)}] = {m.group(5)}",
        code,
    )


def _format_chained_calls(code):
    patterns = [
        (
            r"(\w+)=(\w+)\(([^)]+)\)(\w+\[[^\]]+\])",
            lambda m: f"local {m.group(1)} = {m.group(2)}({m.group(3)})\n{m.group(4)}",
        ),
        (
            r"\b(\w+)\((\d+\s*\+\s*\d+),{([^}]+)}\)",
            lambda m: _eval_arithmetic_param(m.group(1), m.group(2), m.group(3)),
        ),
    ]
    return reduce(lambda c, p: re.sub(p[0], p[1], c), patterns, code)


def _eval_arithmetic_param(func_name, expr, table_content):
    try:
        node = ast.parse(expr, mode="eval")
        if isinstance(node.body, ast.BinOp):
            value = eval(compile(ast.Expression(node.body), "", "eval"), {})
            return f"{func_name}({value}, {{{table_content}}})"
    except:
        pass
    return f"{func_name}({expr}, {{{table_content}}})"


def _process_complex_calls(code):
    patterns = [
        (
            r"(\w+\.\w+)=(\w+)\(([^)]+)\)",
            lambda m: f"{m.group(1)} = {m.group(2)}({_try_eval(m.group(3))})",
        ),
        (
            r"(\w+)\[([^]]+)\]([\w.]+)",
            lambda m: f"{m.group(1)}[{_try_eval(m.group(2))}]{m.group(3)}",
        ),
    ]
    return reduce(lambda c, p: re.sub(p[0], p[1], c), patterns, code)


def handle_proxified_locals(code):
    proxy_count = sum(
        [
            len(
                re.findall(r"\(function\([^)]*\).*?end\)\(...\)", code, flags=re.DOTALL)
            ),
            len(re.findall(r"\b(getfenv|setmetatable|getmetatable|newproxy)\b", code)),
            len(re.findall(r"unpack\s+or\s+table\[[^\]]+\]", code)),
        ]
    )

    code = [
        re.sub(
            r"\(function\(([^)]*)\)(.*?)end\)(\(...\))",
            lambda m: _simplify_proxy_wrapper(m.group(1), m.group(2), m.group(3)),
            code,
            flags=re.DOTALL,
        ),
        re.sub(
            r"\b(getfenv|setmetatable|getmetatable|newproxy)\b",
            lambda m: _replace_proxy_functions(m.group(1)),
            code,
            flags=re.DOTALL,
        ),
        re.sub(r"unpack\s+or\s+table\[([^\]]+)\]", "table.unpack", code),
    ][-1]

    print(f"\n[PROXY] Found {proxy_count} proxy patterns")
    return code


def _simplify_proxy_wrapper(params, body, args):
    print(f"[PROXY] Original params: {params}")
    print(f"[PROXY] Original body length: {len(body)} chars")

    # Replace common proxy patterns
    replacements = {
        r"getfenv\(\)\s*or\s*_ENV": "_ENV",
        r"newproxy\(true\)": "{}",
        r"setmetatable\([^,]+,\s*{[^}]+}\)": "",
    }

    for pattern, repl in replacements.items():
        if re.search(pattern, body):
            print(f"[PROXY] Replacing pattern: {pattern}")
        body = re.sub(pattern, repl, body, flags=re.DOTALL)

    return body + "\n" + args


def _replace_proxy_functions(fn_name):
    replacements = {
        "getfenv": "_ENV",
        "newproxy": "function() return {} end",
        "setmetatable": "--[METATABLE]--",
        "getmetatable": "--[METATABLE]--",
    }
    print(f"[PROXY] Replacing {fn_name} with {replacements.get(fn_name, fn_name)}")
    return replacements.get(fn_name, fn_name)


def handle_string_splitting(code):
    patterns = [
        (
            r"table\.concat\(\{([^}]+)\}\)",
            lambda m: (
                print(
                    f"[Strings] Found table.concat with {len(re.findall(r'"([^"]+)"', m.group(1)))} parts"
                )
                or '"' + "".join(re.findall(r'"([^"]+)"', m.group(1))) + '"'
            ),
        ),
        (
            r"local function \w+\(t\)(.*?)end.*?return (.*?)\(table\.pack\((.+?)\)\)",
            lambda m: (
                print(f"[Strings] Found custom concat function")
                or f'"{decode_custom_concat(m.group(3))}"'
            ),
        ),
        (
            r"(elseif?|else if|if)\s+(\w+)\s*([<>]=?|==?)\s*(\d+)(\s*then)",
            lambda m: f"{m.group(1)} {m.group(2)}{m.group(3)}{m.group(4)}{m.group(5)}"
            if not _is_string_split_number(m.group(4))
            else (
                print(f"[Strings] Found string split marker: {m.group(4)}")
                or m.group(0)
            ),
        ),
    ]

    return [
        re.sub(p[0], p[1], code, flags=re.DOTALL if i == 1 else 0)
        for i, p in enumerate(patterns)
    ][-1]


def decode_custom_concat(chunks):
    parts = re.findall(r'"([^"]+)"', chunks)
    decoded = "".join(parts)
    print(f"[Strings] Reconstructed string: {decoded[:50]}...")
    return decoded


def _is_string_split_number(num_str):
    try:
        num = int(num_str)
        return num > 10000 and (num % 1000 == 0 or num % 1111 == 0)
    except:
        return False


def handle_random_literals(code):
    print("Random Literals count: ", len(re.findall(r"\b[rR]?(\d{5,})\b", code)))

    patterns = [
        (r"\b[rR]?(\d{5,})\b", lambda m: f"var_{int(m.group(1)) % 1000} "),
        (
            r"(\w+)\s*=\s*(\w+(?:,\s*\w+)*)\s*=\s*([^\n]+)",
            lambda m: "\n".join(
                [f"{var.strip()} = {m.group(3)}" for var in m.group(2).split(",")]
            ),
        ),
        (
            r"\b(-?\d{7,})\b",
            lambda m: str(eval(m.group(0))) if m.group(0).isdigit() else m.group(0),
        ),
        (r"\b(RandomLiterals|r55\d{3})\b", "nil"),
    ]

    return reduce(lambda c, p: re.sub(p[0], p[1], c), patterns, code)


def demangle_names(code):
    patterns = [
        (r"\b_(\d+)\b", lambda m: f"var_{m.group(1)}"),
        (
            r"\b([a-zA-Z]+)(?:_[a-zA-Z]+)+\b",
            lambda m: f"var_{abs(hash(m.group(0)) % 1000)}",
        ),
        (r"\b_([0-9a-fA-F]+)\b", lambda m: f"var_{int(m.group(1), 16)}"),
        (r"local function generateName\(.*?end", "", re.DOTALL),
    ]
    return [
        re.sub(p[0], p[1], code, flags=p[2] if len(p) > 2 else 0) for p in patterns
    ][-1]

def demangle_variables(code):
    var_map = {
        "V": "table",
        "f": "function",
        "R": "string",
        "O": "math",
        "N": "number",
        "X": "char",
        "G": "table.insert",
        "p": "string.sub",
        "i": "string.concat",
        "H": "table",
        "Y": "io.read",
        "q": "io.write",
        "y": "position",
        "t": "accumulator",
        "K": "bit32",
        "J": "table",
        "W": "window",
        "m": "match",
        "C": "char",
        "Z": "temp",
        "Q": "flag",
        "P": "number",
        "L": "for",
        "F": "string.format",
        "D": "buffer",
        "B": "byte",
        "A": "array",
        "S": "state",
        "T": "type",
        "U": "string",
        "E": "error",
        "I": "io",
        "M": "math.max",
        "k": "key",
        "j": "goto",
        "w": "number",
        "z": "zone",
        "x": "x",
        "c": "char",
        "v": "version",
        "b": "buffer",
        "n": "count",
        "m": "memory",
        "u": "user",
        "l": "list",
        "g": "global",
        "d": "pointer",
        "s": "string",
        "r": "result",
        "o": "object",
        "h": "handle",
        "e": "element",
        "a": "array",
    }

    for obf, clean in var_map.items():
        code = re.sub(rf'\b{obf}\b(?![\'"])', clean, code)

    code = re.sub(r"\bvar_(\d+)\b", lambda m: f"local_var_{m.group(1)}", code)

    code = re.sub(
        r"function (\w+)\(([A-Za-z, ]+)\)",
        lambda m: (
            f"function {m.group(1)}("
            + ", ".join(
                [var_map.get(p.strip(), p.strip()) for p in m.group(2).split(",")]
            )
            + ")"
        ),
        code,
    )

    return code
