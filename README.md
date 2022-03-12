# gitlab-ci-shellcheck

![example workflow](https://github.com/spyoungtech/gitlab-ci-shellcheck/actions/workflows/unittests.yaml/badge.svg)
[![Coverage Status](https://coveralls.io/repos/github/spyoungtech/gitlab-ci-shellcheck/badge.svg?branch=main)](https://coveralls.io/github/spyoungtech/gitlab-ci-shellcheck?branch=main)


A utility (and pre-commit hook) for running shellcheck against shell scripts inside GitLab CI YAML files.

```bash
pip install gitlab-ci-shellcheck
```

Usage:
```bash
gitlab-ci-shellcheck --help
```

Note: this requires that `shellcheck` is installed separately and on PATH.
