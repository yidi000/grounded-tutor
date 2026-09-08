"""Static publication has a separate explicit approval boundary."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_pages_is_approval_gated_and_contains_no_provider_configuration():
    workflow = (ROOT / ".github/workflows/demo-pages.yml").read_text()
    assert "vars.DEMO_PAGES_APPROVED == 'true'" in workflow
    assert "github.event.repository.default_branch" in workflow
    assert "VITE_APP_MODE: demo_read_only" in workflow
    assert "path: apps/web/dist" in workflow
    assert "needs: build" in workflow
    assert "group: demo-pages-${{ github.ref }}" in workflow
    for private in ("FASTGPT_API_KEY", "LLM_API_KEY", "secrets."):
        assert private not in workflow


def test_local_instructions_return_link_is_relative():
    text = (ROOT / "apps/web/public/local-setup.html").read_text()
    assert 'href="./"' in text
    assert "apps/api/.env.example" in text
