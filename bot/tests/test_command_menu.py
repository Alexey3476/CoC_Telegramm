import ast
from pathlib import Path


def test_bot_command_definitions_have_no_duplicates_per_scope():
    source = (Path(__file__).parents[1] / "app" / "bot.py").read_text()
    mod = ast.parse(source)
    fn = next(x for x in mod.body if isinstance(x, ast.AsyncFunctionDef) and x.name == "sync_bot_commands")
    # Validate the default base commands are unique; Telegram rejects a list with duplicates.
    assignment = next(x for x in fn.body if isinstance(x, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "base" for t in x.targets))
    commands = [n.args[0].value for n in assignment.value.elts]
    assert len(commands) == len(set(commands))
