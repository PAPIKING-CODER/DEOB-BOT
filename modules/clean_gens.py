import re


def clean_name_generators(code):
    code = re.sub(
        r'util\.shuffle\([^)]+\);',
        '',
        code
    )
    
 
    code = re.sub(
        r'local namegenerators = .*?\}\}',
        '',
        code,
        flags=re.DOTALL
    )
    
    return code


def unwrap_functions(code):

    code = [re.sub(
        r'(?:local\s+(\w+)\s*=\s*)?function\(' + re.escape(', '.join([chr(97+i) for i in range(arity)])) + r'\)\s*'
        r'return\s+' + re.escape(', '.join([chr(97+i) for i in range(arity)])) + r'\s+end\s*[,;]?\s*'
        r'return\s+\1(?:\s*end)?',
        lambda m: f'local {m.group(1)} = function({", ".join([chr(97+i) for i in range(arity)])}) return {", ".join([chr(97+i) for i in range(arity)])} end' if m.group(1) else '',
        code
    ) for arity in range(0, 6)][-1]
    
    code = re.sub(
        r'local\s+(\w+)\s*=\s*Z\((\w+)\)\s*'
        r'local\s+(\w+)\s*=\s*function\(([^)]*)\)\s*'
        r'return\s+\3\(\3\)\s*end\s*'
        r'return\s+\3\s*end',
        lambda m: f'local {m.group(1)} = Z({m.group(2)})\nlocal {m.group(3)} = identity_fn',
        code
    )
    
    return code
