import ast

code = '''
def apply_discount(total, percent):
    """Return the total after a discount."""
    return total * percent / 100
'''

tree = ast.parse(code)

# see the whole AST tree
print(ast.dump(tree, indent=2))

# find the function definition node
print("Function definition node:")
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        args = [arg.arg for arg in node.args.args]
        print(f"Function name: {node.name}, line: {node.lineno}, Arguments: {args}")