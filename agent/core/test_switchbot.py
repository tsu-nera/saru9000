import switchbot


def test_beats_alternate_off_and_the_next_color():
    commands = [switchbot.beat_commands(i) for i in range(8)]
    assert commands[0::2] == [("turnOff", "default")] * 4
    assert [p for _, p in commands[1::2]] == list(switchbot.COLORS) + [switchbot.COLORS[0]]


def test_headers_sign_token_time_and_nonce():
    h = switchbot.headers("token", "secret")
    assert h["Authorization"] == "token"
    assert h["t"].isdigit() and len(h["nonce"]) == 32
    assert h["sign"]
