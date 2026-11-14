import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import cost_ledger


def make_output(rows):
    tasks = []
    for description, role, model, prompt, completion in rows:
        tasks.append(SimpleNamespace(
            description=description,
            agent=SimpleNamespace(role=role),
            model=model,
            token_usage=SimpleNamespace(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
            ),
        ))
    return SimpleNamespace(tasks_output=tasks)


def test_split_provider_model():
    assert cost_ledger.split_provider_model('OpenAI: gpt-4o-mini') == ('openai', 'gpt-4o-mini')
    assert cost_ledger.split_provider_model('gpt-4o') == ('', 'gpt-4o')
    assert cost_ledger.split_provider_model(None) == ('', '')


def test_price_lookup_known_and_unknown():
    price = cost_ledger.get_price('OpenAI', 'gpt-4o-mini')
    assert price == {'input': 0.15, 'output': 0.60}
    assert cost_ledger.get_price('openai', 'gpt-4o-2024-11-20')['input'] == 2.50
    assert cost_ledger.get_price('nobody', 'mystery-model') == {'input': 0.0, 'output': 0.0}


def test_estimate_cost():
    cost = cost_ledger.estimate_cost('openai', 'gpt-4o-mini', 1_000_000, 1_000_000)
    assert cost == 0.75
    assert cost_ledger.estimate_cost('nobody', 'mystery-model', 5000, 5000) == 0.0


def test_extract_token_usage_from_fake_output():
    output = make_output([
        ('Write the brief', 'Researcher', 'OpenAI: gpt-4o-mini', 1200, 300),
        ('Review the brief', 'Editor', 'Anthropic: claude-haiku-3.5', 800, 200),
    ])
    rows = cost_ledger.extract_token_usage(output)
    assert len(rows) == 2
    assert rows[0]['agent'] == 'Researcher'
    assert rows[0]['total_tokens'] == 1500
    assert rows[1]['model'] == 'Anthropic: claude-haiku-3.5'


def test_extract_skips_tasks_without_usage():
    output = make_output([('No usage', 'Writer', 'OpenAI: gpt-4o', 0, 0)])
    assert cost_ledger.extract_token_usage(output) == []


def test_build_cost_record_totals():
    output = make_output([
        ('Write the brief', 'Researcher', 'OpenAI: gpt-4o-mini', 1_000_000, 0),
        ('Review the brief', 'Editor', 'OpenAI: gpt-4o-mini', 0, 1_000_000),
    ])
    record = cost_ledger.build_cost_record('Nightly digest', output, {'topic': 'pricing'})
    assert record['crew_name'] == 'Nightly digest'
    assert record['total_tokens'] == 2_000_000
    assert record['total_cost_usd'] == 0.75
    assert record['inputs'] == {'topic': 'pricing'}


def test_aggregate_by_crew():
    records = [
        {'crew_name': 'Nightly digest', 'total_tokens': 1000, 'total_cost_usd': 0.10, 'created_at': '2025-03-01T02:00:00'},
        {'crew_name': 'Nightly digest', 'total_tokens': 2000, 'total_cost_usd': 0.20, 'created_at': '2025-03-02T02:00:00'},
        {'crew_name': 'Support triage', 'total_tokens': 500, 'total_cost_usd': 0.05, 'created_at': '2025-03-02T09:00:00'},
    ]
    rows = cost_ledger.aggregate_by_crew(records)
    assert rows[0]['crew_name'] == 'Nightly digest'
    assert rows[0]['runs'] == 2
    assert rows[0]['tokens'] == 3000
    assert round(rows[0]['cost_usd'], 2) == 0.30


def test_aggregate_by_day():
    records = [
        {'total_tokens': 1000, 'total_cost_usd': 0.10, 'created_at': '2025-03-02T02:00:00'},
        {'total_tokens': 500, 'total_cost_usd': 0.05, 'created_at': '2025-03-01T23:00:00'},
    ]
    rows = cost_ledger.aggregate_by_day(records)
    assert [row['day'] for row in rows] == ['2025-03-01', '2025-03-02']
    assert rows[1]['tokens'] == 1000
