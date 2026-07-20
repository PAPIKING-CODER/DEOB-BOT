import re


def reverse_pipeline(code):
    code = re.sub(
        r'local Pipeline = require\("prometheus\.pipeline"\)[^}]+end\)',
        "",
        code,
        flags=re.DOTALL,
    )

    # Remove step applications
    code = re.sub(r"pipeline:addStep\([^)]+\)", "", code)

    # Remove name generator setup
    code = re.sub(r"pipeline:setNameGenerator\([^)]+\)", "", code)
    return code
