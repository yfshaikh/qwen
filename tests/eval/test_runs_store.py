from engram.eval import runs


def test_run_store_roundtrip(tmp_path):
    run_id, run_dir = runs.new_run("scn", base_dir=tmp_path)
    assert run_dir.name.endswith(run_id) and run_dir.is_dir()
    runs.write_run(run_dir, {"run_id": run_id, "status": "running", "started_at": "t"})
    assert runs.read_run(run_dir)["status"] == "running"

    runs.append_event(run_dir, {"type": "status", "status": "running"})
    runs.append_event(run_dir, {"type": "turn", "role": "user"})
    evs, cursor = runs.read_events(run_dir, 0)
    assert len(evs) == 2 and cursor == 2
    evs2, cursor2 = runs.read_events(run_dir, cursor)
    assert evs2 == [] and cursor2 == 2


def test_list_runs_skips_corrupt(tmp_path):
    _, d1 = runs.new_run("a", base_dir=tmp_path)
    runs.write_run(d1, {"run_id": "x", "status": "passed", "started_at": "2026-01-02"})
    (tmp_path / "junk").mkdir()  # no run.json
    out = runs.list_runs(base_dir=tmp_path)
    assert [r["run_id"] for r in out] == ["x"]
