from pathlib import Path

import pytest

from servicedoc.er.detector import GoGORMDetector, PySQLAlchemyDetector, RawSQLDetector


@pytest.fixture
def go_model_source() -> bytes:
    return Path(__file__).parent.parent / "fixtures" / "sample_go" / "model.go"


@pytest.fixture
def py_models_source() -> bytes:
    return Path(__file__).parent.parent / "fixtures" / "sample_python" / "models.py"


def test_gorm_detector_finds_entities(go_model_source):
    detector = GoGORMDetector()
    source = go_model_source.read_bytes()
    entities, relations = detector.detect(source, go_model_source)
    names = {e.name for e in entities}
    assert "User" in names
    assert "Post" in names


def test_gorm_detector_marks_primary_keys(go_model_source):
    from servicedoc.models.er import ERFieldKind
    detector = GoGORMDetector()
    source = go_model_source.read_bytes()
    entities, _ = detector.detect(source, go_model_source)
    user = next(e for e in entities if e.name == "User")
    pk_fields = [f for f in user.fields if f.kind == ERFieldKind.PK]
    assert len(pk_fields) >= 1


def test_sqlalchemy_detector_finds_models(py_models_source):
    detector = PySQLAlchemyDetector()
    source = py_models_source.read_bytes()
    entities, relations = detector.detect(source, py_models_source)
    names = {e.name for e in entities}
    assert "User" in names
    assert "Post" in names


def test_raw_sql_detector():
    source = b"""
    def get_users():
        cursor.execute("SELECT * FROM users WHERE deleted_at IS NULL")
        cursor.execute("INSERT INTO audit_log VALUES (%s, %s)", (1, 'action'))
    """
    detector = RawSQLDetector()
    entities, _ = detector.detect(source, Path("test.py"))
    names = {e.name for e in entities}
    assert "Users" in names
