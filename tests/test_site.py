import json
from pathlib import Path

from dartbot import storage
from dartbot.site.build import TEMPLATE_DIR, build_site
from tests.test_models import make_classification, make_disclosure


def seed(root: Path) -> None:
    storage.append_disclosures(
        [
            make_disclosure(rcept_no="20261120000001", rcept_dt="20261120", report_nm="<script>x</script>"),
            make_disclosure(rcept_no="20261121000001", rcept_dt="20261121", candidate_type=None, report_nm="임원소유상황보고서"),
        ],
        root,
    )
    storage.append_classifications(
        [
            make_classification(rcept_no="20261120000001", classifier_version="v1", sentiment="부정",
                                classified_at="2026-11-21T07:00:00+09:00"),
            make_classification(rcept_no="20261120000001", classifier_version="v2", sentiment="긍정",
                                classified_at="2026-11-22T07:00:00+09:00"),
        ],
        root,
    )
    storage.append_ops_log(root, {"kind": "collect", "date": "20261120", "fetched": 10, "listed": 8, "candidates": 1, "new": 1})
    storage.append_ops_log(root, {"kind": "run", "at": "2026-11-22T07:00:00+09:00", "classified": 1, "failed": 0,
                                  "remaining": 0, "stopped_by_quota": False})


def test_build_creates_all_pages_and_json(tmp_path):
    seed(tmp_path / "data")
    out = tmp_path / "site"
    build_site(tmp_path / "data", out)
    for name in ("index.html", "validation.html", "ops.html", "data/summary.json", "data/ops.json",
                 "data/days/index.json", "data/days/20261120.json"):
        assert (out / name).exists(), name
    assert json.loads((out / "data/days/index.json").read_text(encoding="utf-8")) == ["20261120"]


def test_day_json_contains_dart_link(tmp_path):
    seed(tmp_path / "data")
    build_site(tmp_path / "data", tmp_path / "site")
    rows = json.loads((tmp_path / "site/data/days/20261120.json").read_text(encoding="utf-8"))
    assert rows[0]["url"] == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261120000001"
    assert rows[0]["title"] == "<script>x</script>"  # raw in JSON; rendered via textContent


def test_latest_version_used_for_day_json(tmp_path):
    seed(tmp_path / "data")
    build_site(tmp_path / "data", tmp_path / "site")
    rows = json.loads((tmp_path / "site/data/days/20261120.json").read_text(encoding="utf-8"))
    assert rows[0]["sentiment"] == "긍정"


def test_ops_json_lists_excluded_titles(tmp_path):
    seed(tmp_path / "data")
    build_site(tmp_path / "data", tmp_path / "site")
    ops = json.loads((tmp_path / "site/data/ops.json").read_text(encoding="utf-8"))
    assert ops["excluded_titles"] == ["임원소유상황보고서"]
    assert ops["last_run"]["classified"] == 1
    assert ops["daily"][0]["date"] == "20261120"


def test_no_innerhtml_in_templates():
    for path in Path(TEMPLATE_DIR).glob("*.html"):
        assert "innerHTML" not in path.read_text(encoding="utf-8"), path.name


def test_backfill_warning_text_present(tmp_path):
    seed(tmp_path / "data")
    build_site(tmp_path / "data", tmp_path / "site")
    html = (tmp_path / "site/validation.html").read_text(encoding="utf-8")
    assert "미래 정보" in html and "투자 조언이 아닙니다" in html


def test_build_without_summary_writes_empty_groups(tmp_path):
    build_site(tmp_path / "data", tmp_path / "site")
    assert json.loads((tmp_path / "site/data/summary.json").read_text(encoding="utf-8"))["groups"] == []
