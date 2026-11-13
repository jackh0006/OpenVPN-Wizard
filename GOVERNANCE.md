# Governance

OpenVPN Wizard is a small, maintainer-led open-source project.

## Roles

- **Maintainer** — reviews and merges changes, manages releases and security
  reports. Currently `@jackh0006`.
- **Contributor** — anyone who opens an issue or pull request.

## Decisions

Routine fixes are merged by the maintainer after CI passes. Changes that alter
the security model, the on-disk layout, or a public CLI option are documented
in `CHANGELOG.md` and, when practical, discussed in an issue first.

## Quality bar

A change is ready when:

1. `pytest` passes.
2. `python -m compileall` passes.
3. Shell scripts pass `bash -n` and `shellcheck -S error`.
4. Security-relevant changes include a test or a clear explanation.
5. Documentation is updated in the same change.

## Security reports

Do not open a public issue for a vulnerability. Follow `SECURITY.md`.

## Releases

Versions follow semantic versioning. A release is tagged `vX.Y.Z`; the release
workflow rebuilds and retests the package before publishing the wheel and
source archive.
