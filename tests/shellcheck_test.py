import json
import os
import pathlib
import sys
from typing import Any
from typing import TypedDict
from typing import Union

import pytest


TESTS_DIR = pathlib.Path(__file__).parent
ROOT = TESTS_DIR.parent
EXAMPLES_DIR = pathlib.Path(__file__).parent / 'shellcheck_examples'
sys.path.insert(0, str(ROOT))

from gitlab_ci_shellcheck import shellcheck_string, ci_yaml_to_shell, load_yaml, yaml_to_jobs


class ExpectedShellcheckResult(TypedDict):
    returncode: int
    stderr: str
    stdout_json: Union[dict, list, str]


examples_scripts = [str(EXAMPLES_DIR / fname) for fname in os.listdir(EXAMPLES_DIR) if fname.endswith('.sh')]
example_yamls = [str(EXAMPLES_DIR / fname) for fname in os.listdir(EXAMPLES_DIR) if fname.endswith('.yaml')]


@pytest.mark.parametrize(argnames='test_file', argvalues=examples_scripts)
def test_shellcheck_from_string(test_file: str):
    assert str(test_file).endswith('.sh')
    test_file = EXAMPLES_DIR / test_file
    expected_file = test_file.parent / str(test_file).replace('.sh', '-expected.json')
    with open(test_file) as f:
        script = f.read()
    with open(expected_file) as f:
        expected: ExpectedShellcheckResult
        expected = json.loads(f.read())

    result = shellcheck_string(script_text=script, shellcheck_args=['-f', 'json', '-s', 'bash'])
    assert result.returncode == expected['returncode']
    assert json.loads(result.stdout) == expected['stdout_json']
    assert result.stderr == expected['stderr']


@pytest.mark.parametrize(argnames='test_file', argvalues=example_yamls)
def test_yaml_to_script(test_file: str):
    assert str(test_file).endswith('.yaml')
    test_file = EXAMPLES_DIR / test_file
    expected_file = test_file.parent / str(test_file).replace('.yaml', '.sh')
    config = load_yaml(test_file)
    (job,) = yaml_to_jobs(config)
    script, after_script = ci_yaml_to_shell(job)
    with open(expected_file) as f:
        expected = f.read().strip()
    assert script == expected

    if after_script:
        expected_after_file = test_file.parent / str(test_file).replace('.yaml', '-after.sh')
        if not os.path.exists(expected_after_file):
            raise Exception('Missing expected shell file for after script')
        with open(expected_after_file) as after_f:
            expected_after = after_f.read()
        assert after_script == expected_after
