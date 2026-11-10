# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Exercise native OpenCode delegation with a scripted local model.

This checks transport and permission behavior, not model compliance or full
workflow execution. The only data sent to the mock is synthetic fixture data.
"""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from typing import Any

MARKER = 'EGM_PARENT_ONLY_SENTINEL'
SECRET = 'EGM_SYNTHETIC_SECRET'
# Project instructions the host injects; Goldfish reviewers must not see them.
AMBIENT = 'EGM_AMBIENT_INSTRUCTIONS_SENTINEL'
NESTED = 'EGM_NESTED_INSTRUCTIONS_SENTINEL'
NOTES = 'EGM_SYNTHETIC_NOTES'
REVIEWER = 'egm-zoom-out'
# What a reviewer must still receive: its persona file, named in its prompt, and its environment.
KEPT = ('agents/zoom_out.md', 'Working directory:')
TASK_PROMPT = 'Read the synthetic fixture files.'
REQUESTS: list[dict[str, Any]] = []

Call = tuple[str, dict[str, str]]


@dataclass(frozen=True)
class Interface:
    """How one OpenCode configuration interface installs, runs, and reports the probe."""

    major: int
    install_args: tuple[str, ...]
    run_args: tuple[str, ...]
    # The orchestrator's delegation tool call.
    delegate: Call
    # The reviewer's tool calls, given the project directory, in order.
    child_calls: Callable[[Path], list[Call]]
    # Tools the host may offer the reviewer.
    child_tools: frozenset[str]
    # Text that each denied reviewer call returns.
    denials: tuple[str, ...]
    provider: Callable[[str], dict[str, Any]]
    # The child and parent session IDs of a completed delegation event.
    sessions: Callable[[dict[str, Any]], tuple[str, str]]


INTERFACES = {
    'v1': Interface(
        major=1,
        install_args=(),
        run_args=('--agent', 'egm'),
        delegate=('task', {
            'description': 'Probe child isolation',
            'subagent_type': REVIEWER,
            'prompt': TASK_PROMPT,
        }),
        # A denied call ends the child's turn in V1, so the denied read goes last.
        child_calls=lambda project: [
            ('read', {'filePath': str(project / 'pkg' / 'notes.txt')}),
            ('read', {'filePath': str(project / '.env')}),
        ],
        child_tools=frozenset({'read', 'glob'}),
        denials=('prevents you from using this specific tool call',),
        provider=lambda url: {'provider': {'fixture': {
            'npm': '@ai-sdk/openai-compatible',
            'name': 'fixture',
            'options': {'baseURL': url, 'apiKey': 'fixture'},
            'models': {'fixture': {'name': 'fixture'}},
        }}},
        sessions=lambda event: (
            event['part']['state']['metadata']['sessionId'],
            event['part']['state']['metadata']['parentSessionId'],
        ),
    ),
    'v2': Interface(
        major=2,
        install_args=('--interface', 'v2'),
        # The shared V2 background service does not read OPENCODE_CONFIG.
        run_args=('--standalone', '--agent', 'egm'),
        delegate=('subagent', {
            'agent': REVIEWER,
            'description': 'Probe child isolation',
            'prompt': TASK_PROMPT,
        }),
        # V2 offers reviewers the skill tool despite their "*" deny, and refuses its calls. The
        # guard plugin removes it, so the tool is unavailable rather than denied.
        child_calls=lambda project: [
            ('read', {'path': str(project / 'pkg' / 'notes.txt')}),
            ('read', {'path': str(project / '.env')}),
        ],
        child_tools=frozenset({'read', 'glob'}),
        denials=('Permission denied: read',),
        provider=lambda url: {'providers': {'fixture': {
            'package': '@opencode/ai/providers/openai-compatible',
            'settings': {'baseURL': url, 'apiKey': 'fixture'},
            'models': {'fixture': {'name': 'fixture'}},
        }}},
        sessions=lambda event: (
            event['part']['state']['metadata']['metadata']['sessionID'],
            event['sessionID'],
        ),
    ),
}


class MockProvider(BaseHTTPRequestHandler):
    delegate: Call = ('', {})
    # The reviewer makes these calls in order, then stops.
    child_calls: list[Call] = []

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_POST(self) -> None:
        request = json.loads(
            self.rfile.read(int(self.headers['Content-Length']))
        )
        REQUESTS.append(request)
        tools = tool_names(request)
        results = sum(
            message.get('role') == 'tool' for message in request['messages']
        )
        delta = {'role': 'assistant', 'content': 'SCRIPTED_COMPLETION'}
        finish = 'stop'
        if self.delegate[0] in tools and results == 0:
            delta = self.call(*self.delegate)
            finish = 'tool_calls'
        elif self.delegate[0] not in tools and 'read' in tools and results < len(self.child_calls):
            delta = self.call(*self.child_calls[results])
            finish = 'tool_calls'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for payload in (delta, {}):
            event = {
                'id': 'synthetic',
                'object': 'chat.completion.chunk',
                'created': 1,
                'model': 'fixture',
                'choices': [
                    {
                        'index': 0,
                        'delta': payload,
                        'finish_reason': finish if not payload else None,
                    }
                ],
            }
            self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')

    @staticmethod
    def call(name: str, arguments: dict[str, str]) -> dict[str, Any]:
        return {
            'role': 'assistant',
            'tool_calls': [
                {
                    'index': 0,
                    'id': f'fixture-call-{len(REQUESTS)}',
                    'type': 'function',
                    'function': {
                        'name': name,
                        'arguments': json.dumps(arguments),
                    },
                }
            ],
        }


def tool_names(request: dict[str, Any]) -> set[str]:
    return {tool['function']['name'] for tool in request.get('tools', [])}


def parse_version(output: str, major: int) -> str:
    """The version in `opencode --version` output; it must be a `major`.x release."""
    # V1 prints "1.18.29"; V2 prints "opencode v2.2.5".
    match = re.search(r'(?<![\d.])(\d+)\.\d+\.\d+(?![\d.])', output)
    assert match, f'Unrecognized OpenCode version output: {output!r}'
    assert int(match[1]) == major, f'OpenCode {match[0]} is not a {major}.x release'
    return match[0]


def write_fixtures(project: Path) -> None:
    """A project with a secret, project instructions, and a nested instructions file."""
    project.mkdir()
    (project / '.env').write_text(SECRET + '\n')
    # Editors on Windows add a byte order mark, which OpenCode drops when it renders the file.
    (project / 'AGENTS.md').write_bytes(b'\xef\xbb\xbf' + (AMBIENT + '\n').encode())
    (project / 'pkg').mkdir()
    (project / 'pkg' / 'AGENTS.md').write_text(NESTED + '\n')
    (project / 'pkg' / 'notes.txt').write_text(NOTES + '\n')


def configure(interface: Interface, source: Path, install: Path, url: str) -> dict[str, Any]:
    """Install the adapter and point its configuration at the scripted model."""
    subprocess.run(
        ['python3', str(source / 'adapters/opencode/install.py'), *interface.install_args, str(install)],
        check=True,
        stdout=subprocess.DEVNULL,
        timeout=60,
    )
    config = json.loads((install / 'opencode.json').read_text())
    config |= interface.provider(url)
    config['model'] = 'fixture/fixture'
    return config


def run_opencode(
    binary: Path, interface: Interface, project: Path, home: Path, config: Path, output: Path,
) -> list[dict[str, Any]]:
    """Run one orchestrator turn in an isolated home and return its JSON events."""
    env = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'HOME': str(home),
        'XDG_CONFIG_HOME': str(home / 'config'),
        'XDG_DATA_HOME': str(home / 'data'),
        'XDG_CACHE_HOME': str(home / 'cache'),
        'XDG_STATE_HOME': str(home / 'state'),
        'OPENCODE_CONFIG': str(config),
    }
    result = subprocess.run(
        [
            str(binary), 'run', *interface.run_args, '--format', 'json', '--model', 'fixture/fixture',
            f'Parent-only marker: {MARKER}. Delegate without it.',
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )
    (output / 'trace.jsonl').write_text(result.stdout)
    (output / 'stderr.txt').write_text(result.stderr)
    assert result.returncode == 0, f'OpenCode exited {result.returncode}; inspect stderr.txt'
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def check_delegation(interface: Interface, trace: list[dict[str, Any]]) -> tuple[dict[str, Any], str, str]:
    """The single completed delegation: its state and its child and parent sessions."""
    tasks = [
        e for e in trace
        if e.get('type') == 'tool_use' and e['part'].get('tool') == interface.delegate[0]
    ]
    assert (
        len(tasks) == 1 and tasks[0]['part']['state']['status'] == 'completed'
    ), 'No completed native task'
    task = tasks[0]['part']['state']
    assert MARKER not in json.dumps(task['input']), 'Parent marker passed to child'
    child, parent = interface.sessions(tasks[0])
    assert child != parent, 'Child reused parent session'
    return task, child, parent


def check_requests(interface: Interface, task: dict[str, Any]) -> list[dict[str, Any]]:
    """Check what the scripted model received; return the reviewer's requests."""
    delegate = interface.delegate[0]
    parents = [r for r in REQUESTS if delegate in tool_names(r)]
    assert any(MARKER in json.dumps(r) for r in parents), 'Parent marker did not reach provider'
    assert all(
        AMBIENT in json.dumps(r) for r in parents
    ), 'Project instructions did not reach the orchestrator'
    children = [r for r in REQUESTS if 'read' in tool_names(r) and delegate not in tool_names(r)]
    assert children, 'No native child provider request observed'
    assert all(
        task['input']['prompt'] in json.dumps(r) for r in children
    ), 'Child request does not match task prompt'
    assert all(MARKER not in json.dumps(r) for r in children), 'Parent marker reached child'
    assert all(
        kept in json.dumps(r) for r in children for kept in KEPT
    ), 'Reviewer lost its persona prompt or environment'
    assert all(
        tool_names(r) == interface.child_tools for r in children
    ), f'Unexpected child tools: {[sorted(tool_names(r)) for r in children]}'
    return children


def tool_results(children: list[dict[str, Any]]) -> list[str]:
    results = [
        json.dumps(m.get('content'))
        for r in children
        for m in r['messages']
        if m.get('role') == 'tool'
    ]
    assert results, 'No child tool result observed'
    return results


def check_isolation(interface: Interface, children: list[dict[str, Any]], results: list[str]) -> None:
    assert all(SECRET not in r for r in results), 'Synthetic secret reached child'
    assert any(NOTES in r for r in results), 'Nested fixture read did not reach child'
    for denial in interface.denials:
        assert any(denial in r for r in results), f'No native denial result: {denial}'
    assert all(AMBIENT not in json.dumps(r) for r in children), 'Project instructions reached child'
    assert all(NESTED not in json.dumps(r) for r in children), 'Nested instructions reached child'


def present(marker: str, children: list[dict[str, Any]]) -> bool:
    return any(marker in json.dumps(r) for r in children)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--opencode', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interface', choices=tuple(INTERFACES), default='v1')
    args = parser.parse_args()
    interface = INTERFACES[args.interface]
    source, binary = args.source.resolve(), args.opencode.resolve()
    version = parse_version(
        subprocess.check_output([str(binary), '--version'], text=True), interface.major
    )
    sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    status = subprocess.check_output(
        ['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=all'], text=True,
    )
    assert not status, 'Source contains staged, unstaged, or untracked changes'
    args.output.mkdir(parents=True, exist_ok=False)
    server = ThreadingHTTPServer(('127.0.0.1', 0), MockProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='egm-native-probe-') as root:
            # Canonical paths: on macOS /var is a symlink, and OpenCode would treat
            # the unresolved fixture paths as external directories.
            root = Path(root).resolve()
            project, home = root / 'project', root / 'home'
            write_fixtures(project)
            home.mkdir()
            MockProvider.delegate = interface.delegate
            MockProvider.child_calls = interface.child_calls(project)
            config = configure(
                interface, source, root / 'install', f'http://127.0.0.1:{server.server_port}/v1',
            )
            config_path = root / 'config.json'
            config_path.write_text(json.dumps(config))
            trace = run_opencode(binary, interface, project, home, config_path, args.output)
            task, child, parent = check_delegation(interface, trace)
            children = check_requests(interface, task)
            results = tool_results(children)
            observations = {
                'parent_marker_seen_in_parent': True,
                'native_task_input': task['input'],
                'native_task_sessions': {'child': child, 'parent': parent},
                'child_tools': sorted(interface.child_tools),
                'child_marker_present': present(MARKER, children),
                'child_project_instructions_present': present(AMBIENT, children),
                'child_nested_instructions_present': present(NESTED, children),
                'child_tool_results': results,
            }
            (args.output / 'child-observations.json').write_text(
                json.dumps(observations, indent=2) + '\n'
            )
            check_isolation(interface, children, results)
            summary = {
                'head': sha,
                'interface': args.interface,
                'opencode_version': version,
                'model': 'scripted local mock',
                'native_child_completed': True,
                'child_tools': sorted(interface.child_tools),
                'parent_marker_seen_in_parent': True,
                'parent_marker_in_child': False,
                'fixture_env_read': 'denied',
                'project_instructions_in_orchestrator': True,
                'project_instructions_in_child': False,
                'nested_instructions_in_child': False,
                'scope': (
                    'One scripted delegation and its scripted reviewer calls; '
                    'not full workflow, model behavior, or general isolation'
                ),
            }
            (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
            print(json.dumps(summary, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


if __name__ == '__main__':
    main()
