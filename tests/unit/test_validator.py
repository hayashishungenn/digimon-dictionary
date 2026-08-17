"""T2 tests: data-quality gates, conflict auditing, and dedup.

Covers the expanded validator checks, provenance/conflict recording with real
source ids, idempotent merge (no duplicate aliases/provenance/conflicts), and
non-zero exit codes for verify_samples / validate_data.
"""
from __future__ import annotations

import json

from pipeline.core.models import MatchedEntity, SourceDigimon, SourceName
from pipeline.core.schema import connect, create_schema
from pipeline.merge.store import CanonicalStore
from pipeline.validation.validator import validate
from tests.conftest import _mk


def _rec(source: str, sid: str, en: str, *, level=None, attr=None) -> SourceDigimon:
    return SourceDigimon(
        source=source, source_id=sid,
        names=[SourceName(en, "en", status="community", source=source)],
        level_raw=level, attribute_raw=attr,
        extra={"source_url": f"https://example.invalid/{source}/{sid}"},
    )


def _upsert(conn, slug, *recs):
    CanonicalStore(conn).upsert_entity(MatchedEntity(canonical_slug=slug, records=list(recs)))
    conn.commit()


# ---------------------------------------------------------------------------
# conflict auditing: two real sources, both values + the selection reason
# ---------------------------------------------------------------------------
def test_conflict_records_real_sources_and_reason(tmp_path):
    conn = connect(tmp_path / "c.sqlite")
    create_schema(conn)
    dapi = _rec("dapi", "1", "Agumon", level="Child", attr="Vaccine")
    official = _rec("official", "agumon", "Agumon", level="Adult", attr="Virus")
    _upsert(conn, "agumon", dapi, official)

    # world-view level follows the documented source priority (official > dapi)
    row = conn.execute("SELECT level, attribute FROM digimon WHERE canonical_slug='agumon'").fetchone()
    assert row["level"] == "adult"
    assert row["attribute"] == "virus"

    conflicts = conn.execute(
        """SELECT field, source_a, source_id_a, value_a, source_b, source_id_b, value_b,
                  chosen_value, chosen_source, review_status, resolution, candidates
           FROM data_conflict ORDER BY field"""
    ).fetchall()
    by_field = {r["field"]: r for r in conflicts}
    assert set(by_field) == {"level", "attribute"}
    for field in ("level", "attribute"):
        c = by_field[field]
        assert c["source_a"] in ("dapi", "official")
        assert c["source_id_a"] in ("1", "agumon")
        assert c["source_b"] in ("dapi", "official")
        assert c["value_a"] != c["value_b"]
        assert c["chosen_source"] == "official"
        assert c["review_status"] == "auto"
        assert "source priority" in c["resolution"]
        cands = json.loads(c["candidates"])
        assert {x["source"] for x in cands} == {"dapi", "official"}
        assert {x["source_id"] for x in cands} == {"1", "agumon"}


def test_conflict_tie_goes_to_review_queue(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    create_schema(conn)
    # two dapi records (equal priority) disagree on level -> must not guess
    a = _rec("dapi", "1", "Agumon", level="Child")
    b = _rec("dapi", "2", "Agumon", level="Adult")
    _upsert(conn, "agumon", a, b)
    c = conn.execute("SELECT chosen_value, review_status FROM data_conflict WHERE field='level'").fetchone()
    assert c["chosen_value"] is None
    assert c["review_status"] == "review"
    reviews = conn.execute("SELECT reason FROM manual_review_queue").fetchall()
    assert reviews and "level conflict" in reviews[0]["reason"]


def test_merge_is_idempotent(tmp_path):
    """Re-running merge for the same entity must not duplicate aliases/
    provenance/conflicts."""
    conn = connect(tmp_path / "idem.sqlite")
    create_schema(conn)
    dapi = _rec("dapi", "1", "Agumon", level="Child")
    official = _rec("official", "agumon", "Agumon", level="Adult")
    store = CanonicalStore(conn)
    store.upsert_entity(MatchedEntity(canonical_slug="agumon", records=[dapi, official]))
    store.commit()
    store.upsert_entity(MatchedEntity(canonical_slug="agumon", records=[dapi, official]))
    store.commit()

    assert conn.execute("SELECT COUNT(*) FROM digimon WHERE canonical_slug='agumon'").fetchone()[0] == 1
    n_conflict = conn.execute("SELECT COUNT(*) FROM data_conflict WHERE entity_type='digimon' AND entity_id=1 AND field='level'").fetchone()[0]
    assert n_conflict == 1
    # provenance: one row per (entity, field, source)
    n_prov = conn.execute("SELECT COUNT(*) FROM provenance WHERE entity_type='digimon' AND entity_id=1").fetchone()[0]
    fields_srcs = conn.execute(
        "SELECT field, source, COUNT(*) c FROM provenance WHERE entity_type='digimon' AND entity_id=1 GROUP BY field, source"
    ).fetchall()
    assert all(r["c"] == 1 for r in fields_srcs)
    assert n_prov == len(fields_srcs)


# ---------------------------------------------------------------------------
# validator gates
# ---------------------------------------------------------------------------
def test_validator_detects_orphan_join_row(tmp_path):
    conn = connect(tmp_path / "o.sqlite")
    create_schema(conn)
    _upsert(conn, "agumon", _rec("dapi", "1", "Agumon"))
    # FK enforcement normally prevents orphan rows; disable it to simulate
    # corruption/a legacy DB, then insert an orphan digimon_type reference.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO digimon_type(digimon_id, type_id) VALUES(999, 999)")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    report = validate(conn)
    assert any(i["check"] == "orphan_join" and "digimon_type" in i["message"] for i in report["issues"])


def test_validator_detects_invalid_enum(tmp_path):
    conn = connect(tmp_path / "e.sqlite")
    create_schema(conn)
    _upsert(conn, "agumon", _rec("dapi", "1", "Agumon"))
    conn.execute("UPDATE digimon SET level='not-a-level' WHERE canonical_slug='agumon'")
    conn.commit()
    report = validate(conn)
    assert any(i["check"] == "invalid_enum" and "level" in i["message"] for i in report["issues"])


def test_validator_detects_broken_relation(tmp_path):
    conn = connect(tmp_path / "r.sqlite")
    create_schema(conn)
    _upsert(conn, "agumon", _rec("dapi", "1", "Agumon"))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO digimon_relation(from_digimon_id, to_digimon_id, relation_type) VALUES(1, 999, 'variant')")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    report = validate(conn)
    assert any(i["check"] == "broken_relation" for i in report["issues"])


def test_validator_blocks_absolute_image_paths(tmp_path):
    """P0-1: a local_path or digimon.thumbnail that is an absolute filesystem
    path is a publish-blocking error; a relative value passes."""
    conn = connect(tmp_path / "i.sqlite")
    create_schema(conn)
    _upsert(conn, "agumon", _rec("dapi", "1", "Agumon"))
    did = conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()[0]
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status)
           VALUES(?, 'main_image', 'https://x/a.png', ?, 'downloaded')""",
        [did, r"C:\Users\old\Github\Digimon_Dictionary\data\images\digi_00001_Agumon.png"],
    )
    conn.commit()
    report = validate(conn)
    assert any(i["check"] == "absolute_image_path" for i in report["issues"])
    assert report["coverage"]["images"]["absolute_local_paths"] == 1

    # a relative value is fine
    conn.execute("UPDATE digimon_image SET local_path='digi_00001_ab12cd34.png' WHERE digimon_id=?", [did])
    conn.commit()
    report = validate(conn)
    assert not any(i["check"] == "absolute_image_path" for i in report["issues"])
    assert report["coverage"]["images"]["absolute_local_paths"] == 0


def test_validator_detects_fts_mismatch(tmp_path):
    conn = connect(tmp_path / "f.sqlite")
    create_schema(conn)
    _upsert(conn, "agumon", _rec("dapi", "1", "Agumon"))
    CanonicalStore(conn).rebuild_fts()
    conn.execute("INSERT INTO digimon_fts(digimon_fts, rowid, canonical_slug) VALUES('delete-all',0,'')")
    conn.commit()
    report = validate(conn)
    assert any(i["check"] == "fts_mismatch" for i in report["issues"])


def test_validator_detects_snapshot_stale(tmp_path):
    conn = connect(tmp_path / "s.sqlite")
    create_schema(conn)
    _upsert(conn, "agumon", _rec("dapi", "1", "Agumon"))
    # write a snapshot claiming the wrong total
    conn.execute("INSERT INTO snapshot(snapshot_date, official_count, extended_count, total_count) VALUES('2026-01-01', 0, 0, 999)")
    conn.commit()
    report = validate(conn)
    assert any(i["check"] == "snapshot_stale" for i in report["issues"])


def test_validator_coverage_verified_vs_present(tmp_path):
    conn = connect(tmp_path / "v.sqlite")
    create_schema(conn)
    # agumon: community-status zh name (present + verified)
    agumon = _rec("dapi", "1", "Agumon")
    agumon.names.append(SourceName("亚古兽", "zh_cn", status="community", source="digimons_net"))
    # another entity with a transliteration zh name (present but NOT verified)
    fan = _rec("dapi", "2", "Fandomon")
    fan.names.append(SourceName("翻斗兽", "zh_cn", status="transliteration", source="generated"))
    for slug, rec in (("agumon", agumon), ("fandomon", fan)):
        _upsert(conn, slug, rec)
    CanonicalStore(conn).rebuild_fts()
    conn.execute("INSERT INTO snapshot(snapshot_date, official_count, extended_count, total_count) VALUES('2026-01-01',0,0,2)")
    conn.commit()

    report = validate(conn)
    cov = report["coverage"]["zh_cn"]
    assert cov["present"] == 2
    assert cov["verified"] == 1  # only the community-status name counts as verified
    assert cov["total"] == 2


# ---------------------------------------------------------------------------
# script exit codes
# ---------------------------------------------------------------------------
def _full_rec(slug: str, en: str, ja: str, zh: str) -> SourceDigimon:
    rec = _mk(slug, en, ja, zh, dapi_id=1, level="child", attribute="vaccine",
              types=("Reptile",), fields=("Dragon's Roar",), skills=["Baby Flame"],
              profile_en="A Reptile Digimon.")
    rec.image_url = "https://example.invalid/main.png"
    return rec


def test_verify_samples_nonzero_on_failure(monkeypatch, tmp_path):
    import scripts.verify_samples as vs

    db = tmp_path / "bad.sqlite"
    conn = connect(db)
    create_schema(conn)
    # a digimon with only an English name — fails every field check
    lonely = SourceDigimon(
        source="dapi", source_id="1",
        names=[SourceName("Lonelymon", "en", status="community", source="dapi")],
        extra={},
    )
    _upsert(conn, "lonelymon", lonely)
    conn.commit()
    conn.close()

    monkeypatch.setattr(vs, "DB_PATH", db)
    assert vs.main(["--n", "10"]) != 0


def test_verify_samples_zero_on_success(monkeypatch, tmp_path):
    import scripts.verify_samples as vs

    db = tmp_path / "good.sqlite"
    conn = connect(db)
    create_schema(conn)
    _upsert(conn, "agumon", _full_rec("agumon", "Agumon", "アグモン", "亚古兽"))
    conn.commit()
    conn.close()

    monkeypatch.setattr(vs, "DB_PATH", db)
    monkeypatch.setattr(vs, "FIXED", ["Agumon"])  # fixed list must all be present
    assert vs.main(["--n", "1"]) == 0


def test_verify_samples_category_mapping():
    """P1-2: a sample's failure/gap reason maps to the documented categories."""
    import scripts.verify_samples as vs

    assert vs._sample_category({"found": False}) == "match_failure"
    assert vs._sample_category({"found": True, "problems": [{"status": "sync_failure"}],
                                "conflicts": [], "gaps": []}) == "parse_failure"
    assert vs._sample_category({"found": True, "problems": [{"status": "unexplained"}],
                                "conflicts": [], "gaps": []}) == "fetch_failure"
    assert vs._sample_category({"found": True, "problems": [], "conflicts": [{"field": "level"}],
                                "gaps": []}) == "conflict"
    assert vs._sample_category({"found": True, "problems": [], "conflicts": [],
                                "gaps": [{"field": "image"}]}) == "image_missing"
    assert vs._sample_category({"found": True, "problems": [], "conflicts": [],
                                "gaps": [{"field": "level"}]}) == "no_source"


def test_verify_samples_report_has_audit_fields(monkeypatch, tmp_path):
    """P1-2: the JSON gate report carries run_id, sources, review-queue status
    and failure categories — it is auditable against the live DB."""
    import scripts.verify_samples as vs

    db = tmp_path / "g.sqlite"
    conn = connect(db)
    create_schema(conn)
    _upsert(conn, "agumon", _full_rec("agumon", "Agumon", "アグモン", "亚古兽"))
    conn.execute(
        """INSERT INTO sync_run(run_id, status, sources, snapshot_date, started_at, finished_at)
           VALUES('run-x','ok','dapi','2026-01-01','2026-01-01T00:00:00+00:00','2026-01-01T00:00:01+00:00')"""
    )
    conn.execute(
        """INSERT INTO source_sync(source, run_id, status, started_at, finished_at, records,
           parsed_count, failed_count, raw_completeness, content_hash, payload_hash)
           VALUES('dapi','run-x','ok','2026-01-01T00:00:00+00:00','2026-01-01T00:00:01+00:00',1,1,0,1,'h','p')"""
    )
    conn.execute(
        "INSERT INTO manual_review_queue(entity_type, entity_id, reason, status) "
        "VALUES('digimon', 1, 'needs review', 'open')"
    )
    conn.commit()
    conn.close()

    out = tmp_path / "vs.json"
    monkeypatch.setattr(vs, "DB_PATH", db)
    monkeypatch.setattr(vs, "FIXED", ["Agumon"])
    assert vs.main(["--n", "1", "--json", str(out)]) == 0
    report = json.loads(out.read_text("utf-8"))
    assert report["run_id"] == "run-x"
    assert report["sources"] == ["dapi"]
    assert report["review_queue"]["open"] == 1
    assert "failure_categories" in report
    assert report["seed"] == vs.DEFAULT_SEED


def test_validate_data_exit_code(monkeypatch, tmp_path):
    import scripts.validate_data as vd

    db = tmp_path / "v.sqlite"
    conn = connect(db)
    create_schema(conn)
    _upsert(conn, "agumon", _rec("dapi", "1", "Agumon"))
    CanonicalStore(conn).rebuild_fts()
    # _rec entities are extended (is_official=0, is_extended=1): 0 official + 1 extended = 1 total
    conn.execute("INSERT INTO snapshot(snapshot_date, official_count, extended_count, total_count) VALUES('2026-01-01',0,1,1)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(vd, "DB_PATH", db)
    # reports must go to a temp dir, never the repo's real data/reports/
    assert vd.main(["--json", str(tmp_path / "report.json"),
                    "--reports-dir", str(tmp_path / "reports")]) == 0

    # inject an invalid enum -> validator errors -> non-zero exit
    conn = connect(db)
    conn.execute("UPDATE digimon SET level='bogus' WHERE canonical_slug='agumon'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(vd, "DB_PATH", db)
    assert vd.main(["--reports-dir", str(tmp_path / "reports")]) != 0


# ---------------------------------------------------------------------------
# source timestamps + verified flag
# ---------------------------------------------------------------------------
def test_source_last_updated_uses_source_timestamp(tmp_path):
    """A real source timestamp is preserved instead of being overwritten with now."""
    conn = connect(tmp_path / "slu.sqlite")
    create_schema(conn)
    rec = _rec("dapi", "1", "Agumon", level="Child")
    rec.extra["source_last_updated"] = "2020-05-01T00:00:00Z"
    _upsert(conn, "agumon", rec)
    val = conn.execute("SELECT source_last_updated FROM digimon WHERE canonical_slug='agumon'").fetchone()[0]
    assert val == "2020-05-01T00:00:00Z"


def test_name_verified_updates_on_reupsert(tmp_path):
    """name_zh_cn_verified must also be set on the UPDATE path (not just INSERT)."""
    conn = connect(tmp_path / "nv.sqlite")
    create_schema(conn)
    rec1 = SourceDigimon(
        source="dapi", source_id="1",
        names=[SourceName("Agumon", "en", status="community", source="dapi")],
        level_raw="Child", extra={},
    )
    _upsert(conn, "agumon", rec1)
    assert conn.execute("SELECT name_zh_cn_verified FROM digimon WHERE canonical_slug='agumon'").fetchone()[0] == 0
    # same entity re-upserted now carries an official zh name -> UPDATE path sets verified
    rec2 = SourceDigimon(
        source="dapi", source_id="1",
        names=[
            SourceName("Agumon", "en", status="community", source="dapi"),
            SourceName("亚古兽", "zh_cn", status="official", source="official"),
        ],
        level_raw="Child", extra={},
    )
    _upsert(conn, "agumon", rec2)
    assert conn.execute("SELECT name_zh_cn_verified FROM digimon WHERE canonical_slug='agumon'").fetchone()[0] == 1
