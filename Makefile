.PHONY: test lint plan build clean

test:
	python -m pytest -q
	python -m compileall -q core management steps ui utils validation cli.py
	bash -n install.sh quick_install.sh openvpn-wizard-linux.sh openvpn-wizard-termux.sh scripts/download-ovpn.sh tests/integration.sh

lint:
	ruff check --select E9,F63,F7,F82 core management steps ui utils validation cli.py tests
	shellcheck -S error install.sh quick_install.sh openvpn-wizard-linux.sh openvpn-wizard-termux.sh scripts/download-ovpn.sh tests/integration.sh

plan:
	python cli.py plan --output ./vpn-plan --profiles 3

build:
	python -m build

clean:
	rm -rf build dist *.egg-info .pytest_cache vpn-plan
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
