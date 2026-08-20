"""LLM client tests.

The CLI backend cannot enforce a schema server-side, so `structured()` is what
stands in for that. Its retry behaviour is load-bearing.
"""

import pytest
from pydantic import BaseModel, Field

from referee.ai.client import (
    ClaudeCLIClient,
    LLMError,
    extract_json,
    load_prompt,
    structured,
)
from tests.conftest import FakeLLM


class Toy(BaseModel):
    name: str
    count: int = Field(ge=0)


# -- JSON extraction from messy replies ------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"name": "x", "count": 1}',
        'Here you go:\n```json\n{"name": "x", "count": 1}\n```',
        '```\n{"name": "x", "count": 1}\n```',
        'Sure! {"name": "x", "count": 1} Hope that helps.',
        '\n\n  {"name": "x", "count": 1}  \n',
    ],
)
def test_json_is_recovered_from_prose_and_fences(raw):
    assert extract_json(raw) == '{"name": "x", "count": 1}'


def test_nested_objects_survive_extraction():
    raw = 'text {"a": {"b": [1, 2]}} more'
    assert extract_json(raw) == '{"a": {"b": [1, 2]}}'


@pytest.mark.parametrize("raw", ["no json here", "", "]["])
def test_a_reply_with_no_object_raises(raw):
    with pytest.raises(LLMError, match="no JSON object"):
        extract_json(raw)


# -- validate-and-retry ----------------------------------------------------


def test_valid_first_reply_is_returned_immediately():
    client = FakeLLM(['{"name": "ok", "count": 3}'])
    model, _ = structured(client, "sys", "user", Toy)
    assert model.name == "ok" and len(client.calls) == 1


def test_schema_violation_is_retried_with_the_error_attached():
    """This is what replaces server-side schema enforcement."""
    client = FakeLLM(['{"name": "x", "count": -5}', '{"name": "x", "count": 5}'])

    model, _ = structured(client, "sys", "user", Toy)

    assert model.count == 5
    assert len(client.calls) == 2
    retry_prompt = client.calls[1][1]
    assert "rejected" in retry_prompt
    assert "count" in retry_prompt, "the model must be told which field failed"


def test_unparseable_replies_are_retried():
    client = FakeLLM(["not json at all", '{"name": "x", "count": 1}'])
    model, _ = structured(client, "sys", "user", Toy)
    assert model.name == "x" and len(client.calls) == 2


def test_giving_up_raises_rather_than_returning_junk():
    client = FakeLLM(["bad"] * 3)
    with pytest.raises(LLMError, match="no valid output after 3 attempts"):
        structured(client, "sys", "user", Toy, attempts=3)


def test_the_original_question_is_preserved_across_retries():
    client = FakeLLM(["bad", '{"name": "x", "count": 1}'])
    structured(client, "sys", "EXTRACT THIS PAPER", Toy)
    assert all("EXTRACT THIS PAPER" in user for _, user in client.calls)


# -- prompts ---------------------------------------------------------------


@pytest.mark.parametrize("name", ["extract_spec", "generate_code"])
def test_shipped_prompts_load_and_are_substantial(name):
    text = load_prompt(name)
    assert len(text) > 500, "a system prompt this short is probably truncated"
    assert "#" in text


def test_a_missing_prompt_is_an_explicit_error():
    with pytest.raises(LLMError, match="no prompt named"):
        load_prompt("does_not_exist")


def test_extraction_prompt_states_the_rules_that_matter():
    """These instructions are the guard rails; losing them would be silent."""
    text = load_prompt("extract_spec").lower()
    for rule in ["verbatim", "assumed", "signal_lag_days", "cost_bps"]:
        assert rule in text, f"extraction prompt no longer mentions {rule}"


def test_generation_prompt_forbids_look_ahead_explicitly():
    text = load_prompt("generate_code").lower()
    assert "shift(-" in text or "future" in text
    assert "pandas" in text and "numpy" in text


# -- CLI wiring ------------------------------------------------------------


def test_missing_binary_gives_an_actionable_message():
    client = ClaudeCLIClient(binary="definitely-not-a-real-binary-xyz")
    with pytest.raises(LLMError, match="not found on PATH"):
        client.complete("sys", "user", timeout=5)
