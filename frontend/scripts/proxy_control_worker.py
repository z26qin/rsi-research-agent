"""Fixed local bridge to ETF core from commit 773468b; never calls an LLM."""
from datetime import date
import json
import os
from pathlib import Path
import sys


def validate_proxy(folder, target):
    from momentum_research_agent.proxy_brief import ProxyBrief, checked_path, replay_snapshot
    b = ProxyBrief.model_validate_json((folder / 'brief.json').read_text())
    if b.requested_as_of.isoformat() != target:
        raise ValueError('Wrong proxy target date')
    if b.status == 'partial':
        checked_path(folder, 'manifest.json', b.manifest_sha256)
        manifest = json.loads((folder / 'manifest.json').read_text())
        if not isinstance(manifest, dict) or manifest.get('target_date') != target:
            raise ValueError('Snapshot target does not match requested date')
        try:
            metrics = replay_snapshot(folder)
        except (KeyError, TypeError) as exc:
            raise ValueError('Invalid snapshot structure') from exc
        if metrics != b.metrics:
            raise ValueError('Proxy metrics do not replay')
    return b


def factor_context(project, target):
    import pandas as pd
    from momentum_research_agent.brief_readiness import sha256_file
    from momentum_research_agent.config import load_env
    from momentum_research_agent.tools.engine_pipeline import resolve_engine_root
    load_env(project)
    root = resolve_engine_root(project)
    result = {'model_status': 'unavailable', 'message': 'Original engine assessment not run. Factor observations are dated background only.', 'inputs': {}}
    if root is None:
        return result
    for name in ('french_research_factors_daily.parquet', 'french_momentum_factor_daily.parquet'):
        p = root / 'data/processed' / name
        try:
            frame = pd.read_parquet(p, columns=['date'])
            dates = pd.to_datetime(frame.date, errors='raise', utc=True).dt.date
            past = dates[dates <= target]
            result['inputs'][name] = {'as_of': max(past).isoformat() if len(past) else None,
                                      'sha256': sha256_file(p), 'source': 'Existing engine cache; not refreshed by ETF collection'}
        except (OSError, ValueError, KeyError, TypeError):
            result['inputs'][name] = {'as_of': None, 'source': 'Unavailable'}
    return result


def main():
    project, target, output = Path(sys.argv[1]), date.fromisoformat(sys.argv[2]), Path(sys.argv[3])
    source = str(Path(__file__).resolve().parents[2] / 'src')
    sys.path.insert(0, source)
    os.environ['PYTHONPATH'] = source
    from momentum_research_agent.proxy_brief import run_proxy_brief
    from momentum_research_agent.proxy_data import save_json
    result = run_proxy_brief(target, output)
    save_json(output / 'factor_context.json', factor_context(project, target))
    validate_proxy(output, target.isoformat())
    raise SystemExit(0 if result.status == 'partial' else 2)


if __name__ == '__main__':
    main()
