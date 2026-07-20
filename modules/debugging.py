import re


def add_debugging(code):
    code = re.sub(
        r"local function V\(V\)return H\[V-(-?\d+)\]end",
        lambda m: f"-- Original offset: {m.group(1)}\n"
        + "local function V(idx) return H[idx - offset] end",
        code,
    )
    return code


def handle_antitamper(code):
    code = re.sub(
        r"local valid=true;.*?if valid then else.*?end",
        "local valid=true;",
        code,
        flags=re.DOTALL,
    )

    code = re.sub(r'debug\.sethook\(.*?end,? "l", 5\);', "", code, flags=re.DOTALL)
    return code
