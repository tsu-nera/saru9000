import config
import dance

SONGS = dance.Dances.from_config(
    {
        "cue": "ミュージック、スタート！",
        "menu": {"phrases": ["踊って", "踊れる"], "cancel": "また今度ね。"},
        "songs": [
            {"motion": "mikumiku", "name": "ミクミク", "phrases": ["ミクミクにして"], "choices": ["ミクミク", "1番"]},
            {
                "motion": "tellyourworld",
                "name": "テルユアワールド",
                "phrases": ["テルユアワールド"],
                "choices": ["テルユア", "2番"],
                "cue": "いくよ！",
            },
            {
                "motion": "tellyourworld_full",
                "name": "テルユアワールド完全版",
                "phrases": ["テルユアワールド完全版"],
                "choices": ["完全版", "3番"],
            },
        ],
    }
)


def motion(song):
    return song.motion if song else None


def test_a_phrase_picks_its_song_in_either_kana_width_and_with_punctuation():
    assert motion(SONGS.requested("みくみくにして！")) == "mikumiku"
    assert motion(SONGS.requested("ミク、ミクミク にして")) == "mikumiku"
    assert motion(SONGS.requested("てるゆあわーるど")) == "tellyourworld"
    assert motion(SONGS.requested("ﾃﾙﾕｱﾜｰﾙﾄﾞ")) == "tellyourworld"
    assert motion(SONGS.requested("テルユアワールド完全版")) == "tellyourworld_full"
    assert motion(SONGS.requested("てるゆアワールド完全版で")) == "tellyourworld_full"
    assert SONGS.requested("踊って") is None
    assert SONGS.requested("ミクミク") is None  # a choice word only counts after the menu


def test_each_song_has_its_cue_or_the_shared_one():
    assert SONGS.requested("ミクミクにして").cue == "ミュージック、スタート！"
    assert SONGS.requested("テルユアワールド").cue == "いくよ！"


def test_menu_phrases_and_the_menu_line():
    assert SONGS.asks_menu("ミク、踊って")
    assert SONGS.asks_menu("何が踊れる？")
    assert not SONGS.asks_menu("天気は？")
    assert SONGS.menu() == "ミクミクと、テルユアワールドと、テルユアワールド完全版が踊れるよ。どれにする？"


def test_after_the_menu_a_choice_word_name_or_phrase_picks_a_song():
    assert motion(SONGS.chosen("2番")) == "tellyourworld"
    assert motion(SONGS.chosen("２番で")) == "tellyourworld"
    assert motion(SONGS.chosen("ミクミクがいい")) == "mikumiku"
    assert motion(SONGS.chosen("テルユアワールド")) == "tellyourworld"
    assert motion(SONGS.chosen("完全版")) == "tellyourworld_full"
    assert motion(SONGS.chosen("テルユアワールド完全版がいい")) == "tellyourworld_full"
    assert SONGS.chosen("やっぱりいいや") is None


def test_no_songs_means_no_menu_and_no_brain_note():
    empty = dance.Dances.from_config({})
    assert not empty.asks_menu("踊って")
    assert empty.requested("ミクミクにして") is None
    assert empty.brain_note() == ""


def test_brain_note_names_the_songs():
    assert "「ミクミク」、「テルユアワールド」" in SONGS.brain_note()


def test_committed_config_has_the_songs():
    settings = config.load_config(config.CONFIG_PATH, config.CONFIG_PATH.with_name("none.json"))
    songs = dance.Dances.from_config(settings["dances"])
    assert [s.motion for s in songs.songs] == ["mikumiku", "tellyourworld", "tellyourworld_full"]
    assert all(s.cue for s in songs.songs)
    assert songs.cancel
