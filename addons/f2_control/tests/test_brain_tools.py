"""The Claude brain's tools (jev/brain_tools.json): one stable set for every call, whose answer-key enum is exactly
the union of every built judge's keys, in strict mode's shape (haiku-brain-design section 3, test_brain_tools)."""
import json
import pathlib

import jev_bridge
from jev import feed, plan_task, prompt

FILE = pathlib.Path(prompt.TOOLS)


def _questions():
    found = {f"{j.name}.{q}": vs for j in jev_bridge.judges() for q, vs in j.questions.items()}
    found.update({f"feed.{q}": vs for q, vs in feed.QUESTIONS.items()})
    found.update({f"plan.{q}": vs for q, vs in plan_task.QUESTIONS.items()})
    return found


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


def test_the_enum_is_exactly_every_judges_keys_sorted():
    keys = {k for vs in _questions().values() for v in vs if v["type"] == "choice" for k in v["criteria"]}
    tools = {t["name"]: t for t in prompt.load_tools()}
    choice = tools["answer_choice"]["input_schema"]["properties"]
    assert choice["choice"]["enum"] == sorted(keys)
    assert choice["probabilities"]["items"]["properties"]["key"]["enum"] == sorted(keys)
    assert list(tools) == ["answer_choice", "answer_yes_no", "write_report", "answer_why"]


def test_the_question_catalogue_matches_the_judges():
    data = json.loads(FILE.read_text(encoding="utf-8"))
    qs = _questions()
    assert data["choice_keys_by_question"] == {q: list(vs[0]["criteria"]) for q, vs in qs.items()
                                               if vs[0]["type"] == "choice"}
    assert data["yes_no_questions"] == [q for q, vs in qs.items() if vs[0]["type"] == "noul"]


def test_strict_tools_have_every_property_required_and_no_numeric_limits():
    for tool in prompt.load_tools():
        assert tool["strict"] is True
        for obj in _objects(tool["input_schema"]):
            assert obj["additionalProperties"] is False
            assert sorted(obj["required"]) == sorted(obj["properties"])
        text = json.dumps(tool)
        assert all(word not in text for word in ('"minimum"', '"maximum"', '"maxLength"', '"minLength"'))


def test_the_request_sends_the_file_as_it_is():
    p = prompt.Prompt()
    assert p.request("claude-haiku-5-5", "e", "q", 2048)["tools"] == json.loads(FILE.read_text("utf-8"))["tools"]
