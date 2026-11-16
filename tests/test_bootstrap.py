from pathlib import Path


BOOTSTRAP = Path(__file__).resolve().parent.parent / "install.sh"


def test_bootstrap_refreshes_an_existing_install():
    content = BOOTSTRAP.read_text()
    assert 'install --quiet --upgrade --force-reinstall "$SRC_DIR"' in content


def test_interactive_bootstrap_reattaches_all_terminal_streams():
    content = BOOTSTRAP.read_text()
    assert "reattach_terminal()" in content
    assert "exec <&3 >&3 2>&3" in content
    assert 'log "Launching the setup wizard..."' in content


def test_noninteractive_bootstrap_does_not_require_a_terminal():
    content = BOOTSTRAP.read_text()
    assert "--non-interactive|-n|--plan" in content
    assert 'if [[ "$needs_terminal" == true && (! -t 0 || ! -t 1 || ! -t 2) ]]; then' in content
