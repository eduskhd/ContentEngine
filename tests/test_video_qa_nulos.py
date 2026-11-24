from engine.qa.video_qa import _visual_qa


def test_metadatos_nulos_fallan_con_missing_metadata():
    assert _visual_qa("x.mp4", None) == ("FAIL", ["missing_metadata"])
    assert _visual_qa("x.mp4", {"duration": None, "size": 60_000}) == ("FAIL", ["missing_metadata"])
    assert _visual_qa("x.mp4", {"duration": 20.0, "size": None}) == ("FAIL", ["missing_metadata"])


def test_metadatos_completos_sin_cambios():
    assert _visual_qa("x.mp4", {"duration": 20.0, "size": 60_000}) == ("PASS", [])
