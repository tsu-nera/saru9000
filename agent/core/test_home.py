import home


def body(response_type, speech=""):
    return {
        "response": {
            "response_type": response_type,
            "speech": {"plain": {"speech": speech}},
            "data": {},
        },
        "conversation_id": None,
    }


def test_matched_sentence_gives_the_reply():
    assert home.parse(body("action_done", "間接照明つけます")) == "間接照明つけます"


def test_error_gives_none():
    assert home.parse(body("error", "すみません、わかりませんでした")) is None
