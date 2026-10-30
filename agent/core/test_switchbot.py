import switchbot


def test_beats_alternate_off_and_the_next_color():
    commands = [switchbot.beat_commands(i) for i in range(8)]
    assert commands[0::2] == [[("turnOff", "default")]] * 4
    assert [c[0] for c in commands[1::2]] == [("setColor", c) for c in switchbot.COLORS + switchbot.COLORS[:1]]


def test_only_the_first_light_up_sets_brightness():
    assert ("setBrightness", "100") in switchbot.beat_commands(1)
    assert all(name != "setBrightness" for i in range(2, 20) for name, _ in switchbot.beat_commands(i))


def test_headers_sign_token_time_and_nonce():
    h = switchbot.headers("token", "secret")
    assert h["Authorization"] == "token"
    assert h["t"].isdigit() and len(h["nonce"]) == 32
    assert h["sign"]
