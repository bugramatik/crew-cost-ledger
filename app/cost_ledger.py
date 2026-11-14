"""Token and cost accounting for crew runs.

Every finished run is written as a ``cost_record`` entity: one row per agent,
task and model, with the tokens it used and the spend estimated from a small
price table. Records live in the same ``entities`` table as the crews, so the
ledger travels with an export of the database.
"""

import logging
from datetime import datetime

import db_utils
from utils import rnd_id

logger = logging.getLogger(__name__)

ENTITY_TYPE = 'cost_record'

# USD per 1M tokens, keyed by provider and model. Unknown models are recorded
# with zero cost instead of failing the run that produced them.
MODEL_PRICES = {
    'openai': {
        'gpt-4o': {'input': 2.50, 'output': 10.00},
        'gpt-4o-mini': {'input': 0.15, 'output': 0.60},
        'gpt-4.1': {'input': 2.00, 'output': 8.00},
        'gpt-4.1-mini': {'input': 0.40, 'output': 1.60},
        'o3-mini': {'input': 1.10, 'output': 4.40},
    },
    'anthropic': {
        'claude-sonnet-4': {'input': 3.00, 'output': 15.00},
        'claude-haiku-3.5': {'input': 0.80, 'output': 4.00},
        'claude-opus-4': {'input': 15.00, 'output': 75.00},
    },
    'groq': {
        'llama-3.3-70b-versatile': {'input': 0.59, 'output': 0.79},
        'llama-3.1-8b-instant': {'input': 0.05, 'output': 0.08},
        'mixtral-8x7b-32768': {'input': 0.24, 'output': 0.24},
    },
    'ollama': {
        'llama3.1': {'input': 0.0, 'output': 0.0},
        'qwen2.5': {'input': 0.0, 'output': 0.0},
    },
}


def split_provider_model(provider_and_model):
    """Split 'OpenAI: gpt-4o-mini' into ('openai', 'gpt-4o-mini')."""
    if not provider_and_model:
        return '', ''
    if ':' in provider_and_model:
        provider, model = provider_and_model.split(':', 1)
    else:
        provider, model = '', provider_and_model
    return provider.strip().lower(), model.strip()


def get_price(provider, model):
    """Return the input/output price per 1M tokens, or zeros when unknown."""
    provider_key = (provider or '').strip().lower()
    model_key = (model or '').strip().lower()
    prices = MODEL_PRICES.get(provider_key, {})
    if model_key in prices:
        return prices[model_key]
    # Fall back to a prefix match so dated snapshots still resolve.
    for known_model, known_prices in prices.items():
        if model_key.startswith(known_model):
            return known_prices
    return {'input': 0.0, 'output': 0.0}


def estimate_cost(provider, model, prompt_tokens, completion_tokens):
    """Estimate the spend of one call in USD from the price table."""
    prices = get_price(provider, model)
    prompt_tokens = int(prompt_tokens or 0)
    completion_tokens = int(completion_tokens or 0)
    cost = (prompt_tokens / 1_000_000) * prices['input']
    cost += (completion_tokens / 1_000_000) * prices['output']
    return round(cost, 6)


def _read_attr(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _token_usage(usage):
    """Normalise a usage object or dict into (prompt, completion, total)."""
    if usage is None:
        return 0, 0, 0
    prompt = _read_attr(usage, 'prompt_tokens', 0) or 0
    completion = _read_attr(usage, 'completion_tokens', 0) or 0
    total = _read_attr(usage, 'total_tokens', 0) or (prompt + completion)
    return int(prompt), int(completion), int(total)


def extract_token_usage(crew_output):
    """Pull per-task token usage out of a CrewOutput.

    Returns a list of dicts with ``task``, ``agent``, ``model``, ``prompt_tokens``,
    ``completion_tokens`` and ``total_tokens``. A CrewOutput without usage data
    yields an empty list rather than an error.
    """
    rows = []
    tasks_output = _read_attr(crew_output, 'tasks_output', None) or []
    for index, task_output in enumerate(tasks_output):
        usage = _read_attr(task_output, 'token_usage', None)
        prompt, completion, total = _token_usage(usage)
        if total == 0:
            continue
        agent = _read_attr(task_output, 'agent', None)
        model = _read_attr(task_output, 'model', None) or _read_attr(agent, 'llm', None) or ''
        rows.append({
            'task': _read_attr(task_output, 'description', None) or f'Task {index + 1}',
            'agent': _read_attr(agent, 'role', None) or 'unknown',
            'model': str(model),
            'prompt_tokens': prompt,
            'completion_tokens': completion,
            'total_tokens': total,
        })
    return rows


def build_cost_record(crew_name, crew_output, inputs=None, run_id=None):
    """Build the cost record of one finished run, one entry per task."""
    entries = []
    for row in extract_token_usage(crew_output):
        provider, model = split_provider_model(row['model'])
        entries.append({
            'task': row['task'],
            'agent': row['agent'],
            'provider': provider,
            'model': model,
            'prompt_tokens': row['prompt_tokens'],
            'completion_tokens': row['completion_tokens'],
            'total_tokens': row['total_tokens'],
            'cost_usd': estimate_cost(provider, model, row['prompt_tokens'], row['completion_tokens']),
        })
    return {
        'run_id': run_id or f'RUN_{rnd_id()}',
        'crew_name': crew_name,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'inputs': inputs or {},
        'entries': entries,
        'total_tokens': sum(entry['total_tokens'] for entry in entries),
        'total_cost_usd': round(sum(entry['cost_usd'] for entry in entries), 6),
    }


def record_run_cost(crew_name, crew_output, inputs=None):
    """Write the cost record of a finished run and return it.

    Returns None when the run reported no token usage, so a crew without usage
    data does not leave an empty row behind.
    """
    record = build_cost_record(crew_name, crew_output, inputs)
    if not record['entries']:
        logger.info('No token usage reported for crew %s, nothing recorded.', crew_name)
        return None
    db_utils.save_cost_record(record)
    return record


def load_cost_records():
    """Load every cost record, newest first."""
    return db_utils.load_cost_records()


def aggregate_by_crew(records):
    """Total tokens and spend per crew name."""
    totals = {}
    for record in records:
        name = record.get('crew_name') or 'unknown'
        bucket = totals.setdefault(name, {'crew_name': name, 'runs': 0, 'tokens': 0, 'cost_usd': 0.0})
        bucket['runs'] += 1
        bucket['tokens'] += int(record.get('total_tokens') or 0)
        bucket['cost_usd'] += float(record.get('total_cost_usd') or 0.0)
    rows = list(totals.values())
    for row in rows:
        row['cost_usd'] = round(row['cost_usd'], 4)
    return sorted(rows, key=lambda row: row['cost_usd'], reverse=True)


def aggregate_by_day(records):
    """Total tokens and spend per calendar day, oldest first."""
    totals = {}
    for record in records:
        created_at = record.get('created_at') or ''
        day = created_at[:10] or 'unknown'
        bucket = totals.setdefault(day, {'day': day, 'runs': 0, 'tokens': 0, 'cost_usd': 0.0})
        bucket['runs'] += 1
        bucket['tokens'] += int(record.get('total_tokens') or 0)
        bucket['cost_usd'] += float(record.get('total_cost_usd') or 0.0)
    rows = list(totals.values())
    for row in rows:
        row['cost_usd'] = round(row['cost_usd'], 4)
    return sorted(rows, key=lambda row: row['day'])
