"""Explicit Claude deployment selection, with no shell-helper execution."""

import json
import os
from pathlib import Path
import shutil

LCLS_BINARY = '/sdf/group/lcls/ds/dm/apps/dev/claude/bin/current'
LCLS_KEY_FILE = '/sdf/group/lcls/ds/dm/apps/dev/env/slac-key.dat'
OPTION_FIELDS = ('claude', 'claude_deployment', 'claude_effort', 'claude_cache_ttl')
AUTH_ENV = {
    'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
    'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
    'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_FABLE_MODEL',
    'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS',
}


def validate_options(deployment, effort=None, cache_ttl=None):
    if deployment not in ('personal', 'lcls'):
        raise ValueError('claude_deployment must be personal or lcls')
    if effort not in (None, 'low', 'medium', 'high', 'max'):
        raise ValueError('claude_effort must be low, medium, high or max')
    if cache_ttl not in (None, '5m', '1h'):
        raise ValueError('claude_cache_ttl must be 5m or 1h')


def options(settings):
    return {name: getattr(settings, name) for name in OPTION_FIELDS}


def isolated_settings(deployment='personal', effort=None, cache_ttl=None):
    validate_options(deployment, effort, cache_ttl)
    result = {'autoMemoryEnabled': False}
    if effort is not None or deployment == 'lcls':
        result['effortLevel'] = effort or 'medium'
    if cache_ttl is not None or deployment == 'lcls':
        result['promptCacheTtl'] = cache_ttl or '1h'
    return result


def executable_path(executable='claude', deployment='personal'):
    validate_options(deployment)
    if deployment == 'lcls' and executable in ('claude', 'claude-lcls'):
        executable = LCLS_BINARY
    path = shutil.which(str(Path(executable).expanduser()))
    if not path:
        raise ValueError('Claude executable not found; configure claude or pass --claude')
    with open(path, 'rb') as stream:
        if b'# Central LCLS Claude;' in stream.read(512):
            if deployment != 'lcls':
                raise ValueError('The claude command is the LCLS interactive launcher; '
                                 'select --claude-deployment lcls for isolated application sessions')
            path = LCLS_BINARY
    # Resolve the shared "current" link once, so version checks and this call
    # use the same binary even if the deployment changes during a session.
    return str(Path(path).resolve(strict=True))


def claude_environment(directory, deployment='personal'):
    """Load only approved API/model values; no hooks, plugins or helper commands."""
    validate_options(deployment)
    source = (Path.home() / '.claude-lcls' if deployment == 'lcls' else
              Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))).expanduser())
    saved = {}
    settings_path = source / 'settings.json'
    if deployment == 'lcls' and not settings_path.is_file():
        raise ValueError('Install claude-lcls before selecting the lcls deployment')
    if settings_path.exists():
        try:
            saved = json.loads(settings_path.read_text()).get('env', {})
            if not isinstance(saved, dict):
                raise ValueError()
        except (ValueError, AttributeError):
            raise ValueError('cannot read Claude API environment from settings.json') from None
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE', 'ANTHROPIC_', 'OPENCODE_'))}
    for key in AUTH_ENV:
        if deployment == 'lcls' and key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'):
            continue
        value = saved.get(key) if deployment == 'lcls' else os.environ.get(key, saved.get(key))
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f'Claude environment value {key} must be a string')
            env[key] = value
    if deployment == 'lcls':
        if not env.get('ANTHROPIC_BASE_URL', '').startswith('https://'):
            raise ValueError('claude-lcls requires an HTTPS gateway in its settings')
        try:
            with open(LCLS_KEY_FILE) as stream:
                token = stream.read(16385).strip()
        except OSError:
            raise ValueError('Cannot read the shared LCLS API key; check ps-users access') from None
        if not token or len(token) > 16384 or any(c.isspace() for c in token):
            raise ValueError('Invalid shared LCLS API key file')
        env['ANTHROPIC_API_KEY'] = token
    elif not (env.get('ANTHROPIC_AUTH_TOKEN') or env.get('ANTHROPIC_API_KEY')):
        raise ValueError('Claude requires ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY '
                         'in your environment or Claude settings.json; OAuth/apiKeyHelper is not supported. '
                         'Use claude_deployment=lcls for the centralized LCLS installation.')
    env['CLAUDE_CONFIG_DIR'] = str(directory / 'runtime/claude/config')
    env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
    env['DISABLE_AUTOUPDATER'] = '1'
    return env


def resolved_model(model, env):
    from .config import validate_model
    validate_model(model, 'claude')
    selected = env.get(f'ANTHROPIC_DEFAULT_{model.upper()}_MODEL', model) if model in {
        'sonnet', 'opus', 'haiku', 'fable'} else model
    validate_model(selected, 'claude')
    return selected


def provenance(path, version, model, env, deployment, settings):
    return {'name': 'claude', 'deployment': deployment, 'executable': path,
            'version': version, 'requested_model': model, 'model': resolved_model(model, env),
            'effort': settings.get('effortLevel'),
            'prompt_cache_ttl': settings.get('promptCacheTtl')}
