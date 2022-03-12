import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
from typing import Any
from typing import Dict
from typing import Generic
from typing import List
from typing import Literal
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TypedDict
from typing import TypeVar
from typing import Union

import yaml


class ReferenceTag(yaml.YAMLObject):
    yaml_tag = u'!reference'

    def __init__(self, value: Sequence[str]):
        self.value = value

    def __repr__(self) -> str:
        return f'ReferenceTag({self.value!r})'

    @classmethod
    def from_yaml(
        cls, loader: Union[yaml.Loader, yaml.FullLoader, yaml.UnsafeLoader], node: yaml.Node
    ) -> 'ReferenceTag':
        value = loader.construct_sequence(node)  # type: ignore[no-untyped-call]
        return cls(value)

    @classmethod
    def to_yaml(cls, dumper: yaml.Dumper, data: 'ReferenceTag') -> yaml.nodes.SequenceNode:
        representation: yaml.nodes.SequenceNode
        representation = dumper.represent_sequence(cls.yaml_tag, data.value, flow_style=True)
        return representation

    def __hash__(self) -> int:
        return hash(tuple(self.value))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ReferenceTag):
            return False
        return hash(self) == hash(other)


yaml.add_constructor('!reference', ReferenceTag.from_yaml)
yaml.add_multi_representer(ReferenceTag, ReferenceTag.to_yaml)


class ConfigDefaultsType(TypedDict):
    after_script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]
    before_script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]


class _CIConfig(TypedDict):
    default: Optional[Dict[str, str]]
    before_script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]
    after_script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]


class InheritConfig(TypedDict):
    default: Optional[bool]
    variables: Optional[Union[List[str], bool]]


class JobConfig(TypedDict):
    # just the things we care about
    before_script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]
    script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]
    after_script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]
    variables: Optional[Dict[str, str]]
    inherit: Optional[InheritConfig]


class CiConfig(TypedDict, total=False):
    defaults: Optional[ConfigDefaultsType]
    variables: Optional[Dict[str, str]]
    before_script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]
    after_script: Optional[Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]]

    # unimportant global keys
    workflow: Any
    image: Any
    stages: Any
    services: Any
    cache: Any


class JobResult(TypedDict):
    script_result: subprocess.CompletedProcess[str]
    after_script_result: Optional[subprocess.CompletedProcess[str]]
    result: Literal['pass', 'fail']


class ShellcheckNotFound(EnvironmentError):
    ...


class GitNotFound(EnvironmentError):
    ...


def load_yaml(filepath: Union[str, pathlib.Path]) -> CiConfig:
    with open(filepath) as f:
        y: CiConfig
        y = yaml.load(f, Loader=yaml.Loader)
    if not isinstance(y, dict):
        raise ValueError(f'Unexpected CI configuration format. Was expecting a mapping, got {type(y)!r}')
    return y


def shellcheck_string(script_text: str, shellcheck_args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile(mode='w+') as f:
        f.write(script_text)
        f.seek(0)
        cp = subprocess.run(['shellcheck', *shellcheck_args, '-'], input=script_text, capture_output=True, text=True)
    return cp


def yaml_to_jobs(ci_configuration: CiConfig) -> Sequence[Union[JobConfig, Dict[Any, Any]]]:  # TODO cleanup typehint
    # global_configs = {}  # TODO collect global configs to apply to job configs
    global_keywords = [
        'defaults',
        'variables',
        'workflow',
        'image',
        'stages',
        'before_script',
        'after_script',
        'services',
        'cache',
    ]
    jobs: List[Union[JobConfig, Dict[Any, Any]]]
    jobs = []
    for key, value in ci_configuration.items():
        if key not in global_keywords and isinstance(value, dict):
            jobs.append(value)
    return jobs


def script_block_to_str(obj: Union[str, ReferenceTag, List[Union[str, ReferenceTag, List[str]]]]) -> str:
    if isinstance(obj, str):
        return obj
    elif isinstance(obj, list):
        parts = []
        for part in obj:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, list):
                for subpart in part:
                    if isinstance(subpart, str):
                        parts.append(subpart)
                    else:
                        raise ValueError(f'unexpected subpart {subpart!r}')
            elif isinstance(part, ReferenceTag):
                # skip reference tags for now
                continue
        return '\n'.join(parts)
    elif isinstance(obj, ReferenceTag):
        # ignore reference tags for now
        return ''
    else:
        raise ValueError(f'unexpected script value {obj!r}')


def job_config_to_shell(job_config: Union[JobConfig, Dict[Any, Any]], shell: str = 'bash') -> Tuple[str, str]:
    """
    Returns two-item tuple of the 'script' and 'after_script' portion of a job. Includes the before_script as part of script.

    e.g.
         ```
         before_script: |
           abc
           123
         script:
           - foo
           - bar
         after_script:
           - echo "after"
        ```
    becomes something like: ("abc\n123\nfoo\nbar", "echo after")


    :param job_config:
    :param shell:
    :return:
    """
    # TODO: add shebang?
    before_script = script_block_to_str(job_config.get('before_script') or '')
    script = script_block_to_str(job_config.get('script') or '')
    if before_script:
        effective_script = before_script + '\n' + script
    else:
        effective_script = script

    after_script = script_block_to_str(job_config.get('after_script') or '')
    return effective_script, after_script


def _verify_shellcheck_available() -> Optional[str]:
    return shutil.which('shellcheck')


def _verify_git_available() -> Optional[str]:
    return shutil.which('git')


def _print_job_error(job_result: JobResult) -> None:

    if job_result['script_result'].returncode != 0:
        info = json.loads(job_result['script_result'].stdout)
        print('Script validation error:\n', '\n'.join(r.get('message') for r in info))

    if job_result['after_script_result'] and job_result['after_script_result'].returncode != 0:
        info = json.loads(job_result['after_script_result'].stdout)
        print('after_script: validation error:\n', '\n'.join(r.get('message') for r in info))

    return None


def _main(filepath: str, no_fix: bool = False) -> int:
    config = load_yaml(filepath)
    jobs = yaml_to_jobs(ci_configuration=config)
    job_results = []
    overall_status: Literal[0, 1]
    overall_status = 0
    num_jobs = len(jobs)
    if num_jobs < 1:
        print('No jobs to check')
        return 1
    print(f'Collected {len(jobs)} jobs to check...')
    for job in jobs:
        script, after_script = job_config_to_shell(job_config=job)
        # TODO: allow users to provide args
        script_result = shellcheck_string(script_text=script, shellcheck_args=['-f', 'json', '-s', 'bash'])
        if after_script.strip():
            after_script_result = shellcheck_string(
                script_text=after_script, shellcheck_args=['-f', 'json', '-s', 'bash']
            )
        else:
            after_script_result = None

        overall_result: Literal['pass', 'fail']
        overall_result = 'pass'
        if script_result.returncode != 0:
            overall_result = 'fail'
        if after_script_result and after_script_result.returncode != 0:
            overall_result = 'fail'

        job_result: JobResult
        job_result = {
            'script_result': script_result,
            'after_script_result': after_script_result,
            'result': overall_result,
        }
        if job_result['result'] == 'pass':
            print('.', end='')
        else:
            print('F', end='')
        job_results.append(job_result)
    print()
    for res in job_results:
        if res['result'] != 'pass':
            overall_status = 1
            _print_job_error(res)
    return overall_status


def main() -> int:
    parser = argparse.ArgumentParser('gitlab-ci-shellcheck')
    parser.add_argument(
        'gitlab_ci_yaml', default='.gitlab-ci.yml', nargs='?', help='filepath of the gitlab CI YAML configuration'
    )
    parser.add_argument(
        '--no-fix', action='store_true', dest='no_fix', help='Reserved for future use. Has no effect currently'
    )
    args = parser.parse_args()
    if not _verify_shellcheck_available():
        raise ShellcheckNotFound('Could not find shellcheck. Shellcheck must be installed and on PATH')
    if not args.no_fix and not _verify_git_available():
        raise GitNotFound(
            'Could not find git. Git is required for autofixing issues. Install git or pass --no-fix argument'
        )
    if not os.path.exists(args.gitlab_ci_yaml):
        print(f'file path {args.gitlab_ci_yaml!r} does not exist.')
        return 1
    res = _main(filepath=args.gitlab_ci_yaml, no_fix=args.no_fix)
    return res


if __name__ == '__main__':
    raise SystemExit(main())
