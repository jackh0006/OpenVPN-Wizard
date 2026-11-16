from pathlib import Path


BOOTSTRAP = Path(__file__).resolve().parent.parent / "install.sh"


def test_bootstrap_refreshes_an_existing_install():
    content = BOOTSTRAP.read_text()
    assert 'install --quiet --upgrade --force-reinstall "$SRC_DIR"' in content


def test_piped_interactive_bootstrap_prints_the_reliable_next_step():
    content = BOOTSTRAP.read_text()
    assert 'ok "Bootstrap complete. Start the guided setup with: sudo vpn-installer install"' in content
    assert "! -t 0" in content


def test_noninteractive_bootstrap_does_not_require_a_terminal():
    content = BOOTSTRAP.read_text()
    assert "--non-interactive|-n|--plan" in content
    assert 'if [[ "$needs_terminal" == true && ! -t 0 ]]; then' in content
