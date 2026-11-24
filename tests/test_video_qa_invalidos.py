"""Q3: metadatos numericos invalidos en _visual_qa (cadenas, booleanos y no finitos)."""
from engine.qa.video_qa import _visual_qa


def _invalidos():
    return ("20", False, True, float("nan"), float("inf"), float("-inf"))


def test_duracion_invalida_falla_con_invalid_metadata():
    for valor in _invalidos():
        assert _visual_qa("x.mp4", {"duration": valor, "size": 50_000}) == ("FAIL", ["invalid_metadata"])


def test_tamano_invalido_falla_con_invalid_metadata():
    for valor in _invalidos():
        assert _visual_qa("x.mp4", {"duration": 10, "size": valor}) == ("FAIL", ["invalid_metadata"])


def test_ausentes_y_nulos_siguen_con_missing_metadata():
    for meta in (None, {}, {"duration": None, "size": 50_000}, {"duration": 10, "size": None}):
        assert _visual_qa("x.mp4", meta) == ("FAIL", ["missing_metadata"])


def test_valores_validos_y_umbrales_sin_cambios():
    assert _visual_qa("x.mp4", {"duration": 10, "size": 50_000}) == ("PASS", [])
    assert _visual_qa("x.mp4", {"duration": 9.9, "size": 49_999}) == ("FAIL", ["too_short", "file_too_small"])
    assert _visual_qa("x.mp4", {"duration": 120, "size": 10**12}) == ("PASS", [])
