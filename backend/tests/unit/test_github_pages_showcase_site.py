from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_showcase_site_assets_and_workflow_exist() -> None:
    repo_root = _repo_root()

    assert (repo_root / "site" / "index.html").exists()
    assert (repo_root / "site" / "src" / "main.ts").exists()
    assert (repo_root / "site" / "src" / "tabs.ts").exists()
    assert (repo_root / "site" / "src" / "animations.ts").exists()
    assert (repo_root / "site" / "src" / "mermaid-init.ts").exists()

    workflow = repo_root / ".github" / "workflows" / "deploy-github-pages.yml"
    assert workflow.exists()

    workflow_text = workflow.read_text(encoding="utf-8")
    assert "actions/upload-pages-artifact" in workflow_text
    assert "actions/deploy-pages" in workflow_text
    assert "branches:" in workflow_text and "main" in workflow_text


def test_showcase_index_contains_required_sections() -> None:
    repo_root = _repo_root()
    site_index = repo_root / "site" / "index.html"
    content = site_index.read_text(encoding="utf-8")

    assert "High-Level Architecture" in content
    assert "Security Deep Dive" in content
    assert "Demo Walkthroughs" in content
    assert "tab-mcp" in content
    assert "tab-skill" in content
    assert "tab-role" in content
    assert "tab-agent" in content
    assert "tab-logs" in content
