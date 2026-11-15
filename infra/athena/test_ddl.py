import importlib.util
import os
import re

_spec = importlib.util.spec_from_file_location("gen_ddl", os.path.join(os.path.dirname(__file__), "gen_ddl.py"))
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def test_ddl_matches_what_the_pipeline_writes():
    assert open(gen.OUT).read() == gen.render(gen.schemas()), "run python infra/athena/gen_ddl.py"


def test_ddl_covers_every_table_the_tools_and_research_lambdas_query():
    sql = open(gen.OUT).read()
    created = set(re.findall(r"CREATE EXTERNAL TABLE IF NOT EXISTS cascade\.(\w+)", sql))
    root = os.path.join(os.path.dirname(__file__), "..", "..", "lambdas")
    queried = set()
    for name in ("tools", "research"):
        queried |= set(re.findall(r"FROM (\w+)", open(os.path.join(root, name, "app.py")).read()))
    assert queried <= created, queried - created


def test_rolling_week_is_a_date():
    cols = dict(gen.schemas()["rolling"])
    assert cols["week"] == "date"
