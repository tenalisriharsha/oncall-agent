from pathlib import Path

from oncall_agent.tools.runbooks import RunbookSearchTool

REPO_RUNBOOKS = Path(__file__).resolve().parent.parent / "runbooks"


def test_search_finds_deploy_regression_runbook():
    tool = RunbookSearchTool(REPO_RUNBOOKS)
    result = tool.run(query="high error rate after deploy regression")

    assert result["matches"]
    assert result["matches"][0]["runbook"] == "deploy-regression"
    assert result["matches"][0]["score"] > 0


def test_search_finds_oom_runbook():
    tool = RunbookSearchTool(REPO_RUNBOOKS)
    result = tool.run(query="pods crash looping oom killed memory limit")

    assert result["matches"][0]["runbook"] == "oom-crash-loop"


def test_search_respects_top_k():
    tool = RunbookSearchTool(REPO_RUNBOOKS, top_k=1)
    result = tool.run(query="deploy pod disk network config dependency")

    assert len(result["matches"]) == 1


def test_search_returns_no_matches_for_unrelated_query():
    tool = RunbookSearchTool(REPO_RUNBOOKS)
    result = tool.run(query="xyzzy plugh wibble")

    assert result["matches"] == []


def test_search_on_missing_directory_returns_no_matches(tmp_path: Path):
    tool = RunbookSearchTool(tmp_path / "does-not-exist")
    result = tool.run(query="deploy")

    assert result["matches"] == []


def test_search_on_empty_directory_returns_no_matches(tmp_path: Path):
    tool = RunbookSearchTool(tmp_path)
    result = tool.run(query="deploy")

    assert result["matches"] == []


def test_excerpt_centers_on_a_matched_term(tmp_path: Path):
    (tmp_path / "custom.md").write_text(
        "# Custom\n\nSome unrelated preamble text here. "
        "The root cause was a memory leak in the worker pool. More text follows after.",
        encoding="utf-8",
    )
    tool = RunbookSearchTool(tmp_path)
    result = tool.run(query="memory leak")

    assert result["matches"][0]["runbook"] == "custom"
    assert "memory" in result["matches"][0]["excerpt"].lower()
