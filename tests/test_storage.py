from dartbot import storage
from tests.test_models import make_classification, make_disclosure


def test_append_disclosures_dedupes_by_rcept_no(tmp_path):
    items = [make_disclosure(rcept_no="20261120000001"), make_disclosure(rcept_no="20261120000002")]
    assert storage.append_disclosures(items, tmp_path) == 2
    assert storage.append_disclosures(items, tmp_path) == 0
    assert len(storage.load_disclosures(tmp_path)) == 2


def test_disclosures_split_by_month(tmp_path):
    storage.append_disclosures(
        [
            make_disclosure(rcept_no="20251130000001", rcept_dt="20251130"),
            make_disclosure(rcept_no="20251201000001", rcept_dt="20251201"),
        ],
        tmp_path,
    )
    assert (tmp_path / "disclosures" / "2025" / "2025-11.jsonl").exists()
    assert (tmp_path / "disclosures" / "2025" / "2025-12.jsonl").exists()


def test_load_disclosures_date_filter(tmp_path):
    storage.append_disclosures(
        [
            make_disclosure(rcept_no="20251130000001", rcept_dt="20251130"),
            make_disclosure(rcept_no="20251201000001", rcept_dt="20251201"),
            make_disclosure(rcept_no="20251215000001", rcept_dt="20251215"),
        ],
        tmp_path,
    )
    got = storage.load_disclosures(tmp_path, start="20251201", end="20251210")
    assert [d.rcept_dt for d in got] == ["20251201"]


def test_classification_dedupe_allows_new_version(tmp_path):
    a = make_classification(classifier_version="m+p1")
    b = make_classification(classifier_version="m+p2")
    assert storage.append_classifications([a], tmp_path) == 1
    assert storage.append_classifications([a, b], tmp_path) == 1
    assert len(storage.load_classifications(tmp_path)) == 2


def test_state_missing_file_defaults(tmp_path):
    assert storage.read_state(tmp_path) == {"last_collected_date": None}


def test_state_roundtrip(tmp_path):
    storage.write_state(tmp_path, {"last_collected_date": "20261123"})
    assert storage.read_state(tmp_path)["last_collected_date"] == "20261123"


def test_jsonl_is_utf8_readable(tmp_path):
    storage.append_disclosures([make_disclosure()], tmp_path)
    raw = (tmp_path / "disclosures" / "2026" / "2026-11.jsonl").read_text(encoding="utf-8")
    assert "자기주식" in raw


def test_ops_log_roundtrip(tmp_path):
    storage.append_ops_log(tmp_path, {"date": "20261120", "fetched": 3})
    storage.append_ops_log(tmp_path, {"date": "20261121", "fetched": 4})
    assert [r["fetched"] for r in storage.load_ops_log(tmp_path)] == [3, 4]
