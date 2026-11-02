import pytest

import camera

LIGHTS = ["light.ceiling_left", "light.ceiling_center", "light.ceiling_right"]
AL = "switch.adaptive_lighting_ceiling"


def test_sheet_filter_layout_row_major():
    f = camera.sheet_filter([f"p{i}" for i in range(5)], cols=3)
    assert f.endswith(
        "[v0][v1][v2][v3][v4]xstack=inputs=5:"
        "layout=0_0|w0_0|w0+w0_0|0_h0|w0_h0:fill=black"
    )


def test_sheet_filter_labels_in_own_chain():
    f = camera.sheet_filter(["a", "b", "c"])
    chains = f.split(";")
    for i, label in enumerate("abc"):
        assert chains[i].startswith(f"[{i}:v]scale=800:-2,drawtext=text='{label}'")
        assert chains[i].endswith(f"[v{i}]")


def test_sheet_filter_third_row():
    f = camera.sheet_filter([f"p{i}" for i in range(7)], cols=3)
    assert f.split("layout=")[1].split(":")[0].split("|")[6] == "0_h0+h0"


def test_sheet_filter_single_has_no_xstack():
    f = camera.sheet_filter(["p0"])
    assert "xstack" not in f
    assert "text='p0'" in f
    assert f.startswith("[0:v]scale=800:-2,") and not f.endswith("]")


def test_sheet_filter_escapes_label():
    f = camera.sheet_filter(["a:b'c\\d%"])
    assert "text='a\\:b'\\''c\\\\d\\%'" in f


class FakeHA:
    """call / state の代わり。apply が stuck 回目に呼ばれるまで点灯中の照明は 255 のまま。"""

    def __init__(self, states, apply_restores_on=1):
        self.states = dict(states)  # entity_id -> (state, brightness)
        self.calls = []
        self.apply_count = 0
        self.apply_restores_on = apply_restores_on

    def call(self, service, entity_ids, data):
        self.calls.append((service, entity_ids, data))
        if service == "adaptive_lighting.apply":
            self.apply_count += 1
            if self.apply_count >= self.apply_restores_on:
                self.states = {k: ("on", 3) if v[0] == "on" else v for k, v in self.states.items()}
        return []

    def state(self, entity_id):
        s, b = self.states[entity_id]
        return {"state": s, "attributes": {"brightness": b}}


@pytest.fixture
def ha(monkeypatch):
    def install(states, apply_restores_on=1):
        fake = FakeHA(states, apply_restores_on)
        monkeypatch.setattr(camera, "call", fake.call)
        monkeypatch.setattr(camera, "state", fake.state)
        monkeypatch.setattr(camera.time, "sleep", lambda s: None)
        return fake
    return install


def names(fake):
    return [c[0] for c in fake.calls]


def test_lights_up_normal(ha):
    # 点灯中の照明は撮影中 255 に上がる想定（apply 後に 3 へ戻る）
    fake = ha({e: ("on", 255) for e in LIGHTS})
    with camera.lights_up():
        pass
    assert fake.calls[0] == ("adaptive_lighting.set_manual_control", [],
                             {"entity_id": AL, "lights": LIGHTS, "manual_control": True})
    assert fake.calls[1] == ("light.turn_on", LIGHTS, {"brightness_pct": 100})
    assert fake.calls[2][2]["manual_control"] is False
    assert fake.calls[3] == ("adaptive_lighting.apply", [],
                             {"entity_id": AL, "lights": LIGHTS, "turn_on_lights": False})
    assert names(fake) == ["adaptive_lighting.set_manual_control", "light.turn_on",
                           "adaptive_lighting.set_manual_control", "adaptive_lighting.apply"]


def test_lights_up_restores_on_exception(ha):
    fake = ha({e: ("on", 3) for e in LIGHTS})
    with pytest.raises(RuntimeError):
        with camera.lights_up():
            raise RuntimeError("boom")
    assert names(fake)[-2:] == ["adaptive_lighting.set_manual_control", "adaptive_lighting.apply"]
    assert fake.calls[-2][2]["manual_control"] is False


def test_lights_up_retries_apply_when_still_255(ha):
    fake = ha({e: ("on", 255) for e in LIGHTS}, apply_restores_on=2)
    with camera.lights_up():
        pass
    assert names(fake).count("adaptive_lighting.apply") == 2


def test_lights_up_turns_off_lights_that_were_off(ha):
    fake = ha({LIGHTS[0]: ("off", None), LIGHTS[1]: ("on", 255), LIGHTS[2]: ("off", None)})
    with camera.lights_up():
        pass
    assert fake.calls[-1] == ("light.turn_off", [LIGHTS[0], LIGHTS[2]], {})


def test_snap_tapo_secrets_only_on_stdin(monkeypatch):
    values = {"TAPO_CAMERA_USERNAME": "SENTINEL_USER", "TAPO_CAMERA_PASSWORD": "SENTINEL_PASS",
              "TAPO_CAMERA_HOST": "SENTINEL_HOST"}
    monkeypatch.setattr(camera, "secret", values.__getitem__)
    seen = {}

    def fake_ssh_bytes(command, stdin=None):
        seen.update(command=command, stdin=stdin)
        return b"\xff\xd8jpeg"

    monkeypatch.setattr(camera, "ssh_bytes", fake_ssh_bytes)
    assert camera.snap_tapo() == b"\xff\xd8jpeg"
    assert seen["stdin"] == "SENTINEL_USER\nSENTINEL_PASS\nSENTINEL_HOST\n"
    for v in values.values():
        assert v not in seen["command"]
    assert seen["command"].startswith("python3 -c ")


def test_snap_tapo_empty_fails(monkeypatch):
    monkeypatch.setattr(camera, "secret", lambda n: "x")
    monkeypatch.setattr(camera, "ssh_bytes", lambda c, stdin=None: b"")
    with pytest.raises(SystemExit):
        camera.snap_tapo()


def test_ptz_repeats_one_second_moves(monkeypatch):
    calls = []
    monkeypatch.setattr(camera, "call", lambda s, e, d: calls.append((s, e, d)))
    camera.ptz("left", 3, 0.5)
    assert len(calls) == 3
    assert calls[0] == ("onvif.ptz", [camera.CONFIG["tapo_camera_entity"]], {
        "pan": "LEFT", "move_mode": "ContinuousMove", "continuous_duration": 1, "speed": 0.5})


@pytest.mark.parametrize("argv,command,output", [
    (["on"], "on", None),
    (["off"], "off", None),
    (["status"], "status", None),
    (["snap"], "snap", "snap.jpg"),
    (["snap", "-o", "x.jpg"], "snap", "x.jpg"),
])
def test_parser_c270_unchanged(argv, command, output):
    args = camera.build_parser().parse_args(argv)
    assert args.command == command
    assert getattr(args, "output", None) == output


def test_parser_tapo():
    p = camera.build_parser()
    a = p.parse_args(["tapo", "move", "left", "2", "--speed", "0.5"])
    assert (a.tapo_command, a.direction, a.times, a.speed) == ("move", "left", 2, 0.5)
    a = p.parse_args(["tapo", "sweep", "--lights"])
    assert (a.steps, a.pan_per_step, a.tilt_down, a.to_left, a.settle, a.lights) == (6, 2, 3, 10, 2, True)
    a = p.parse_args(["tapo", "snap"])
    assert a.output is None and a.lights is False
