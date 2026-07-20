import re
import ast
from typing import Callable, List, Dict, Tuple, Union, Optional
from functools import reduce

PatternHandler = Tuple[str, Callable[[re.Match], str]]
BitwiseReplacement = Tuple[str, str]
TableInfo = Dict[str, Union[str, int]]
DecryptedString = List[str]


def reverse_vmify(code: str) -> str:
    def safe_eval(expr: str) -> str:
        try:
            parsed = ast.parse(expr.replace(" ", ""), mode="eval")
            return str(eval(ast.unparse(parsed), {"__builtins__": None}, {}))
        except:
            return expr

    def process_vm_expression(match: re.Match) -> str:
        var, expr1, expr2 = match.groups()

        print(
            "Reversing VM Expression: ",
            f"({var} and {safe_eval(expr1.strip())} or {safe_eval(expr2.strip())})",
        )

        return f"({var} and {safe_eval(expr1.strip())} or {safe_eval(expr2.strip())})"

    patterns: List[PatternHandler] = [
        (
            r"(?<!\.)\b([a-zA-Z_]\w*|\([^)]+\))\s*and\s*((?:\([^)]+\)|[-+]?\d+)(?:\s*[-+*/]\s*(?:\([^)]+\)|[-+]?\d+))*)\s*or\s*((?:\([^)]+\)|[-+]?\d+)(?:\s*[-+*/]\s*(?:\([^)]+\)|[-+]?\d+))*)(?!\w)",
            process_vm_expression,
        ),
        (
            r"\b([-+]?(?:\d+|\(\s*[-+]?\d+\s*\))(?:\s*[-+*/%]\s*[-+]?(?:\d+|\(\s*[-+]?\d+\s*\)))+\b|\(\s*[-+]?\d+\s*[-+*/%]\s*[-+]?\d+\s*\))",
            lambda m: safe_eval(m.group(0)),
        ),
        (
            r"(?<![\.\w])([-+]?\d+|\(\s*[-+]?\d+\s*\))(?![\.\w])",
            lambda m: safe_eval(m.group(1)),
        ),
        (r"\((\w+)\s+and\s+1\s+or\s+0\)", lambda m: f"int({m.group(1)})"),
        (r"\((\w+)\s+and\s+True\s+or\s+False\)", lambda m: f"bool({m.group(1)})"),
        (
            r"\(\s*(-?\d+)\s*([+-])\s*\((-?\d+)\s*-\s*(-?\d+)\)\s*\)",
            lambda m: str(
                eval(f"{m.group(1)}{m.group(2)}{int(m.group(3)) - int(m.group(4))}")
            ),
        ),
        (
            r"\((\w+)\s+and\s+\((\w+)\s+and\s+(\d+)\s+or\s+(\d+)\)\s+or\s+(\d+)\)",
            lambda m: f"({m.group(1)} and {m.group(2)} and {m.group(3)} or {m.group(4)})"
            if int(m.group(5)) == int(m.group(4))
            else m.group(0),
        ),
        (
            r"(\+\(0\)|-\+0|-\s*-\s*|\+-\s*|-\+\s*)",
            lambda m: "-" if "--" in m.group(0) else "+",
        ),
    ]

    for pattern, handler in patterns:
        code = re.sub(pattern, handler, code, flags=re.ASCII)

    bitwise_replacements: List[BitwiseReplacement] = [
        (r"(\w+)\s*%\s*1", r"\1"),
        (r"(\w+)\s*&\s*0", "0"),
        (r"(\w+)\s*\^\s*0", r"\1"),
        (r"(\w+)\s*\|\s*0", r"\1"),
        (r"(\w+)\s*<<\s*0", r"\1"),
        (r"(\w+)\s*>>\s*0", r"\1"),
    ]
    code = [re.sub(p, r, code) for p, r in bitwise_replacements][-1]

    return code


def handle_prometheus_vm(code: str) -> str:
    return re.sub(
        r"while\s*((?:s\[[^\]]+\]|<|>|\(|\)|\s+)+?)\s+do\s+([^=]+)=\s*([^;]+);\s*(.*?)(?=\bend\b)",
        lambda m: process_array_based_loop(m),
        code,
        flags=re.DOTALL,
    )


def process_array_based_loop(match: re.Match) -> str:
    condition, lhs, rhs, body = match.groups()
    cleaned_condition = re.sub(
        r"s\[(-?\d+)\]", lambda m: f"s{int(m.group(1))}", condition
    )
    assignments = [
        f"{re.sub(r's\[(-?\d+)\]', lambda m: f's{int(m.group(1))}', p.strip())} = {re.sub(r'(-?\d+)-\((-?\d+)\+(-?\d+)\)', lambda m: str(int(m.group(1)) + int(m.group(2)) + int(m.group(3))), r.strip())}"
        for p, r in zip(lhs.split(","), rhs.split(","))
    ]
    opcode = re.search(r"-?\d+", rhs.split(",")[0]).group(0)
    return (
        f"-- Array-based VM OP {opcode} --\nwhile {cleaned_condition} do\n{body}\n"
        + "\n".join(assignments)
        + "\nend"
    )


def decrypt_prometheus_strings(code: str) -> str:
    tables: List[TableInfo] = [
        {
            "name": match.group(1),
            "content": match.group(2),
            "offset": detect_table_offset(code, match.group(1)),
        }
        for match in re.finditer(
            r"local\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*{([^}]+)}", code, re.DOTALL
        )
        if is_encoded_table(match.group(2))
    ]

    for table in tables:
        entries = re.split(r',\s*(?=")', table["content"])
        decrypted_entries: DecryptedString = [
            f'"{entry.strip("\"' \t\r\n").encode("latin-1").decode("unicode-escape").encode("latin-1").decode("utf-8", "ignore")}"'
            for entry in entries
        ]
        code = code.replace(
            f"local {table['name']} = {{",
            f"local {table['name']} = {{\n    "
            + ",\n    ".join(decrypted_entries)
            + "\n}",
        )
        code = re.sub(
            rf"{table['name']}\[(\d+)\]",
            lambda m: f"DECRYPTED_ARRAY[{int(m.group(1)) + table['offset']}]",
            code,
        )
    return code


def detect_string_tables(code: str) -> List[TableInfo]:
    return [
        {
            "name": match.group(1),
            "content": match.group(2),
            "offset": detect_table_offset(code, match.group(1)),
        }
        for match in re.finditer(
            r"local\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*{([^}]+)}", code, re.DOTALL
        )
        if is_encoded_table(match.group(2))
    ]


def is_encoded_table(content: str) -> bool:
    return any(
        re.search(r"\\\d{3}|\\x[0-9a-f]{2}|[^\x20-\x7E]", entry)
        for entry in content.split(",")[:5]
    )


def detect_table_offset(code: str, table_name: str) -> int:
    offset_match = re.search(rf"{re.escape(table_name)}\[.*?([+-])\s*(\d+)\]", code)
    return int(offset_match.group(2)) if offset_match else 0x252C


def enhance_string_decryption(code: str) -> str:
    code = re.sub(
        r"_G\[(\d+)\]\(\"((\\\d{3})+)\",([\d]+)\)",
        lambda m: f'"{decrypt_prometheus_strings(m.group(2), int(m.group(4)))}"',
        code,
    )
    return re.sub(
        r"DECRYPT\(([^,]+),\s*(\d+)\s*([+*]\s*\d+)\)",
        lambda m: f'"{decrypt_prometheus_strings(m.group(1), eval(m.group(2) + m.group(3)))}"',
        code,
    )


class PrometheusDecryptor:
    def __init__(self):
        self.lcg_multiplier: Optional[int] = None
        self.lcg_multiplier = self.lcg_increment = self.xor_multiplier = (
            self.xor_seed
        ) = None
        self.lcg_state = self.xor_state = 0
        self.prev_bytes = []

    def extract_parameters(self, code):
        if lcg_match := re.search(
            r"state_45 = \(state_45 \* (\d+) \+ (\d+)\) % 35184372088832", code
        ):
            self.lcg_multiplier, self.lcg_increment = map(int, lcg_match.groups())
        if xor_match := re.search(r"state_8 = state_8 \* (\d+) % 257", code):
            self.xor_multiplier = int(xor_match.group(1))
        if seed_match := re.search(r"prevVal = (\d+);", code):
            self.xor_seed = int(seed_match.group(1))

    def reset_generators(self, seed):
        self.lcg_state, self.xor_state, self.prev_bytes = (
            seed % 35184372088832,
            seed % 255 + 2,
            [],
        )

    def _generate_byte_batch(self):
        self.lcg_state = (
            self.lcg_state * self.lcg_multiplier + self.lcg_increment
        ) % 35184372088832
        self.xor_state = (self.xor_state * self.xor_multiplier) % 257
        while self.xor_state == 1:
            self.xor_state = (self.xor_state * self.xor_multiplier) % 257
        shift = self.xor_state % 32
        rand_value = int(
            (
                (
                    combined := (
                        self.lcg_state >> (13 - (self.xor_state - shift) // 32)
                    )
                    % (1 << 32)
                )
                / (1 << shift)
            )
            % 1
            * (1 << 32)
        ) + int(combined / (1 << shift))
        self.prev_bytes = [(rand_value >> i) & 0xFF for i in (24, 16, 8, 0)]

    def get_next_byte(self):
        if not self.prev_bytes:
            self._generate_byte_batch()
        return self.prev_bytes.pop(0)

    def decrypt_string(self, encrypted, seed):
        self.reset_generators(seed)
        decrypted, prev_xor = [], self.xor_seed
        for char in encrypted:
            plain_byte = (ord(char) - self.get_next_byte() - prev_xor) % 256
            decrypted.append(chr(prev_xor := plain_byte))
        return "".join(decrypted)


def resolve_memory_aliases(code: str) -> str:
    """Resolve complex memory/global/element aliases with tracking"""
    alias_pattern = r"""
        \b(memory|global|element)       # Capture alias type
        \s*=\s*                         # Assignment operator
        ([\w_]+)                        # Capture variable name
        (?:[\s;]+                       # Optional separator
        \2\s*=\s*nil\b)                 # Nil assignment check
    """
    
    # Find and track all aliases
    aliases = {}
    matches = re.finditer(alias_pattern, code, re.X|re.MULTILINE)
    for match in matches:
        alias_type, var_name = match.groups()
        aliases[var_name] = alias_type
    
    # Remove original assignment lines
    code = re.sub(alias_pattern, '', code, flags=re.X|re.MULTILINE)
    
    # Replace variable usage with alias type
    for var_name, alias_type in aliases.items():
        code = re.sub(rf'\b{var_name}\b', alias_type, code)
    
    return code
