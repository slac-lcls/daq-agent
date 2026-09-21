"""Synthetic OpenCode event stream shared by runtime and reporting tests."""

import json


def write_fake_runtime(directory, response, *, delay=False):
    executable = directory / "fake-opencode"
    payload = json.dumps(response)
    executable.write_text(
        "#!/usr/bin/env python3\nimport json,sys,time,os\n"
        "from pathlib import Path\n"
        "if '--version' in sys.argv:\n print('test-runtime'); sys.exit(0)\n"
        "prompt=sys.stdin.read()\n"
        "assert 'log-triage' in prompt\n"
        "config=json.loads((Path(os.environ['OPENCODE_CONFIG_DIR'])/'opencode.json').read_text())\n"
        "assert config['permission']['*']=='deny'\n"
        "assert not config['mcp'] and not config['plugin']\n"
        "print(json.dumps({'type':'tool_use','part':{'tool':'skill','state':{'status':'completed','input':{'name':'log-triage'}}}}))\n"
        "for p in (Path.cwd()/'evidence').glob('*.txt'):\n"
        " print(json.dumps({'type':'tool_use','part':{'tool':'read','state':{'status':'completed','input':{'filePath':str(p)}}}}))\n"
        + ("time.sleep(60)\n" if delay else "")
        + f"print(json.dumps({{'type':'text','part':{{'text':{payload!r}}}}}))\n"
    )
    executable.chmod(0o700)
    return executable
