import re
import ast


def reconstruct_tokenized(code):
    substitution_patterns = [
        (r"\b(_[\dA-F]+)\b", lambda m: f"var_{int(m.group(1)[1:], 16)}"),
        (r"\\u\{([0-9a-fA-F]+)\}", lambda m: f"\\{int(m.group(1), 16)}"),
        (
            r"\b(local_var_\d+)\b",
            lambda m: f"var_{int(m.group(1)[10:]) % 1000}"
            if m.group(1).startswith("local_var_")
            else m.group(0),
        ),
        (r"\b(-?\d{7,})\b", lambda m: str(ast.literal_eval(m.group(0)))),
        (r"-\[METATABLE\]-", "--[[Removed metatable]]"),
        (r"\bvar_(\d+)\b", lambda m: f"var_{int(m.group(1)) % 1000}"),
    ]

    for pattern, replacement in substitution_patterns:
        code = re.sub(pattern, replacement, code)

    return code


def restore_control_flow(code):
    patterns = [
        (r"else\s+if", "elseif"),
        (r"(\bif\b.*?)\s*\n\s*(\bthen\b)", r"\1 \2", re.DOTALL),
        (r"return\s+(\w+)\(\)", r"return \1()"),
    ]

    for pattern in patterns:
        code = re.sub(
            *pattern[:2], flags=pattern[2] if len(pattern) > 2 else 0, string=code
        )

    return code


def reconstruct_functions(code):
    substitutions = [
        (r"function\(\.\.\.\)(.*)end\(\.\.\.\)", lambda m: m.group(1), re.DOTALL),
        (r",\s*\.\.\.|\.\.\.\s*,", ""),
        (r"\(\s*\.\.\.\s*\.\.\.\s*\)", "(...)"),
        (
            r"function\(([^)]*)\)",
            lambda m: "function("
            + (m.group(1).strip() or "_")
            + ("" if "..." in m.group(1) else ", ...")
            + ")",
        ),
        (r"function\(\s*_\s*,([^)]*)\)", lambda m: "function(" + m.group(1) + ")"),
        (
            r"return\s+([^{\n]+{.*?})(\s*end)",
            lambda m: "return " + m.group(1).strip() + m.group(2),
            re.DOTALL,
        ),
        (r",\s*function\b", "\nfunction"),
        (r"\b(Ellipsis|_VAR_)\b", "..."),
        (
            r"return (\w+)\(([^)]+)\)",
            lambda m: "return " + m.group(1) + "(" + m.group(2).rstrip(", ") + ")",
        ),
        (r"function\(\s*(\.\.\.)\s*\)", r"function(\1)"),
        (r",\s*\.\.\.\)", ")"),
        (r"end return", "end\nreturn"),
        (r"(\w+)\)local", r"\1\nlocal"),
        (r"(\w+)\)(\w+)", r"\1\n\2"),
        (
            r"=\s*(\w+)\(([^)]+)$",
            lambda m: "= " + m.group(1) + "(" + m.group(2) + ")",
            re.MULTILINE,
        ),
        (
            r"function\(([^)]+)\)",
            lambda m: "function("
            + ", ".join(p.strip() for p in m.group(1).split(","))
            + ")",
        ),
        (
            r"return\s+([^;]+)\s*\n\s*end",
            lambda m: "return " + m.group(1).strip() + "\nend",
            re.DOTALL,
        ),
        (r"local (\w+) = (\w+)\n(function)", r"local \1 = \2\n\3"),
        (r"(\w+)=(\w+)(\([^)]+\))\s*(\w+)\[", r"\1 = \2\3\n\4["),
        (
            r"return\(function\(([^)]+)\)\s*([^=]+)=function\(([^)]+)\)",
            lambda m: "return function("
            + m.group(1)
            + ")\n"
            + m.group(2)
            + " = function("
            + m.group(3)
            + ")",
        ),
        (r"([A-Z_]+,\s*){5,}[A-Z_]+=function\b", ""),
        (
            r"return (\w+) (\w+)=function\(([^)]+)\)\s+return \1\(\1, ([^)]+)\)",
            lambda m: "local "
            + m.group(2)
            + " = function("
            + m.group(3)
            + ")\nreturn "
            + m.group(1)
            + "("
            + m.group(4)
            + ")",
        ),
    ]

    for sub in substitutions:
        code = re.sub(sub[0], sub[1], code, flags=sub[2] if len(sub) > 2 else 0)

    return code


def reconstruct_locals(code):
    patterns = [
        (
            r"(if\s+[^\s]+)(==|~=|<|>)([^\s]+)(then)(\s*\w+.*?local\s+)",
            lambda m: f"{m.group(1)} {m.group(2)} {m.group(3)} {m.group(4)}\n{m.group(5)}",
            re.DOTALL,
        ),
        (
            r"\b(local\s+[^;\n]+?)(\s*)(local\b)",
            lambda m: f"{m.group(1).rstrip()}\n{m.group(3)} ",
        ),
        (r"(-?\w+)([%^*/+-])(=?)", r"\1 \2\3 "),
        (r"local\s+(\w+),\s*\1", r"local \1"),
        (r"([%\*/\+\-])(=?)", lambda m: f" {m.group(1)}{m.group(2)} "),
        (
            r"(\w+)=([^=]+)(\s*)(local\s+\w+=)",
            lambda m: f"{m.group(1)} = {m.group(2).strip()}\n{m.group(4)}",
        ),
        (r"\s+-\s*(\w+)", r" -\1"),
        (
            r"for\s+(\w+)\s*=\s*(-?\w+)(\s+)(#?\w+)(\s+)(-?\w+)",
            r"for \1 = \2, \4, \6 do",
        ),
        (
            r"(\w+)\.(\w+)\s*=\s*(\w+)\(([^)]+)\)",
            lambda m: f"{m.group(1)}.{m.group(2)} = {m.group(3)}({m.group(4)})",
        ),
        (
            r"\.([A-Za-z])([^\.\w]|$)",
            lambda m: f".{ {'J': 'value', 'Z': 'length', 'X': 'key', 'Q': 'quality', 'D': 'data', 'S': 'size', 'T': 'type', 'B': 'buffer'}.get(m.group(1), m.group(1)) }{m.group(2)}",
        ),
        (r"(\b\w+)\(([^)]+)$", lambda m: f"{m.group(1)}({m.group(2)})", re.MULTILINE),
        (r"(\S)(local\s+)", lambda m: f"{m.group(1)}\n{m.group(2)}"),
    ]

    for p in patterns:
        code = re.sub(p[0], p[1], code, flags=p[2] if len(p) > 2 else 0)

    return code


def reconstruct_conditions(code):
    patterns = [
        (r"\b(elseif|else)\s+", lambda m: f"{m.group(1).rstrip()} "),
        (r"([<>]=?)\s*(-?\d+)", lambda m: f"{m.group(1)} {m.group(2)}"),
        (r"(\})(elseif|else)", r"\1\n\2"),
        (r"\[(-?\w+)\](\s*[<>=])", lambda m: f"[{m.group(1)}] {m.group(2).strip()}"),
        (r"(then)(\S)", r"\1\n\2"),
        (
            r"(\w+)=(\w+)([<>=!]=)(\w+)",
            lambda m: f"{m.group(1)} = {m.group(2)} {m.group(3)} {m.group(4)}",
        ),
        (
            r"(then|else)(\s*)([^\n=]+)=([^;]+);([^\n]+)",
            lambda m: f"{m.group(1)}\n{m.group(3)} = {m.group(4)}\n{m.group(5)}",
        ),
        (r"(\w+\.\w+)=(\w+)", r"\1 = \2"),
        (
            r"\b(if|elseif)\b(.*?)\bthen\b",
            lambda m: f"{m.group(1)} {m.group(2).strip()}\n    then",
            re.DOTALL,
        ),
        (r"(end)(\s*)(else)", r"\1\n\3"),
    ]

    for p in patterns:
        code = re.sub(p[0], p[1], code, flags=p[2] if len(p) > 2 else 0)

    return code


def remove_junkcode(code):
    patterns = [
        (r"local function \w+\(.*?\)\s*return \"[^\"]+\"\s*end", "", re.DOTALL),
        (r"if \w+ == -\d+ then \w+ = -\d+ end", ""),
        (
            r"TABLE_INSERT_OPERATION\(\[-\w+\],PRECISION_VALUE\(-\d+,-?\d+,-?\d+\)\);",
            "",
        ),
        (r"\b\w+ = \w+ [%+-\/*] (?:-?\d+|\(-?\d+ [%+-\/*] -?\d+\))", ""),
        (r"\w+\.\w+ = (?:nil|-\d+|\"\")", ""),
        (r"for \w+ = -\d+,#\w+,-?\d+ do end", ""),
        (r"local \w+ = (?:-?\d+|nil)(?=\s*[^\n])", ""),
        (r"\w+\.\w+,\w+\.\w+ = nil,nil", ""),
        (r"local function (\w+)\(.*?\)\s+return \1\(.*?\)\s+end", "", re.DOTALL),
        (r"\b(\w+) = -\d+\s*([^-+/*]|$)", ""),
        (r"function\(\.\.\.\)\s*return \{\}\s*end", ""),
        (r"-\s*\[\[.*?\]\]", ""),
        (r"\b(\w+) = \1 [+-] \d+\b", ""),
        (r"TABLE_INSERT_OPERATION\(\w+,\w+\([-,\w\s]+\),?\);", ""),
        (r"\b\w+ = \w+ [+-] \(\d+\)\s*$", ""),
    ]

    for p in patterns:
        code = re.sub(p[0], p[1], code, flags=p[2] if len(p) > 2 else 0)

    return code


def clean_tokenized_syntax(code):
    code = re.sub(r"--\[\[.*?\]\]", "", code, flags=re.DOTALL)
    code = re.sub(r"--.*", "", code)
    code = re.sub(r"\\\n", " ", code)
    code = re.sub(r"(\w)\s*=\s*(\w)", r"\1 = \2", code)

    code = re.sub(
        r'("|\')(.*?)(?<!\\)\1',
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(1)}",
        code,
        flags=re.DOTALL,
    )

    indent_level = 0
    indent_stack = []
    output = []

    processed_lines = [
        (
            line.strip(),
            any(
                line.strip().startswith(kw)
                for kw in ["function", "if", "for", "while", "repeat"]
            ),
            line.strip() == "do" or line.strip().startswith("do "),
        )
        for line in code.split("\n")
        if line.strip()
    ]

    for stripped, is_control, is_do in processed_lines:
        if stripped.startswith(("end", "until", "else", "elseif")):
            indent_level = max(0, indent_level - 1)
            if indent_stack and indent_stack[-1] == "function":
                indent_level = max(0, indent_level - 1)
                indent_stack.pop()

        current_indent = "    " * indent_level
        output.append(f"{current_indent}{stripped}")

        if is_control:
            if "function" in stripped:
                indent_stack.append("function")
            indent_level += 1
        elif is_do:
            indent_level += 1

    code = "\n".join(output)

    def format_table(match):
        table_body = match.group(1)
        indent = "    " * (code[: match.start()].count("\n") // 4 + 1)
        entries = [e.strip() for e in re.split(r",(?![^{]*})", table_body) if e.strip()]
        formatted = [f"\n{indent}{e}," for e in entries]
        return (
            "{\n"
            + "\n".join(formatted).rstrip(",")
            + "\n"
            + "    " * (indent.count("    ") - 1)
            + "}"
        )

    code = re.sub(
        r"=\s*{([^}]*?)}", lambda m: f"= {format_table(m)}", code, flags=re.DOTALL
    )

    code = re.sub(r"(function|if|for|while)\s*(\()", r"\1 \2", code)

    cleanup_patterns = [
        (r"\s+(\=|\+|\-|\*|\/|\,)", r"\1"),
        (r"(\=|\+|\-|\*|\/|\,)\s+", r"\1 "),
        (r"(\S)\s*(\{)", r"\1 \2"),
        (r"\}\s*(\S)", r"} \1"),
        (
            r"local\s+((?:\w+\s*,\s*)+\w+)\s*=\s*((?:[^,\n]+,?)+)",
            lambda m: format_multi_declaration(m),
        ),
        (
            r"(\S)([=+-\/*%^<>~\(\)\{\}\[\]])|([=+-\/*%^<>~\(\)\{\}\[\]])[^\s\w]",
            lambda m: f"{m.group(1)} {m.group(2)}" if m.group(1) else f"{m.group(3)} ",
        ),
        (
            r"\{\s*([^{}]+?)\s*\}",
            lambda m: "{" + re.sub(r"\s+", " ", m.group(1)).strip() + "}",
        ),
        (r"\n{3,}", "\n\n"),
        (r"\s+:", ":"),
        (r"\s*,\s*", ", "),
        (r"(\b\w+\s*=\s*[^;\n]+)(;\s*\1)+", lambda m: m.group(1)),
        (r"\[\s*([^]]+?)\s*\]", lambda m: f"[{m.group(1).strip()}]"),
    ]

    for pattern, replacement in cleanup_patterns:
        code = re.sub(pattern, replacement, code)

    return code


def format_multi_declaration(match):
    variables = [v.strip() for v in match.group(1).split(",")]
    values = [v.strip() for v in match.group(2).split(",")]
    max_len = max(len(variables), len(values))
    pad = "    "
    formatted = [
        f"{variables[i] if i < len(variables) else 'nil'} = {values[i] if i < len(values) else 'nil'}"
        for i in range(max_len)
    ]
    return "local " + (",\n" + pad).join(formatted)
