import json

import pytest

from fx_talanta.advisor.provider import MODEL
from fx_talanta.dashboard.research import payload
from fx_talanta.dashboard.translation import Translator


def response(text):
    return json.dumps(
        dict(
            status="completed",
            model=MODEL,
            output=[dict(type="message", content=[dict(type="output_text", text=text)])],
        )
    ).encode()


@pytest.mark.parametrize(
    "source,target,expected",
    [
        ("Risk 0.10% on EURUSD", "zh", "EURUSD 风险 0.10%"),
        ("美元日元风险为 0.10%", "en", "USDJPY risk is 0.10%"),
    ],
)
def test_ephemeral_translation(source, target, expected):
    requests = []

    def transport(raw):
        requests.append(json.loads(raw))
        return response(expected)

    translator = Translator(transport)
    assert translator.translate(dict(text=source, target=target)) == dict(
        text=expected, target=target, persisted=False
    )
    assert requests[0]["store"] is False and requests[0]["tools"] == []
    assert requests[0]["input"] == source
    assert vars(translator).keys() == {"transport", "lock", "calls"}


@pytest.mark.parametrize(
    "data",
    [
        {"text": "x", "target": "fr"},
        {"text": "", "target": "en"},
        {"text": "x" * 4001, "target": "zh"},
        {"text": "x", "target": "en", "save": True},
    ],
)
def test_invalid_translation_never_calls_provider(data):
    def transport(_):
        raise AssertionError("must not call")

    with pytest.raises(ValueError):
        Translator(transport).translate(data)


def test_limit_and_no_retry():
    calls = []

    def transport(_):
        calls.append(1)
        raise RuntimeError("provider failure")

    translator = Translator(transport)
    for _ in range(20):
        with pytest.raises(RuntimeError):
            translator.translate(dict(text="hello", target="zh"))
    with pytest.raises(ValueError):
        translator.translate(dict(text="hello", target="zh"))
    assert len(calls) == 20


def test_chinese_brief_preserved():
    brief = "请提出欧元美元突破策略，每笔风险最多百分之零点一。"
    value = json.loads(payload(brief))
    assert value["input"] == brief
    assert "English or Chinese" in value["instructions"]
