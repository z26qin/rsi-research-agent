"""Read input coverage only. This program never invokes an engine or model."""
import json
import sys
from datetime import date
from pathlib import Path

def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root / 'src'))
    try:
        from momentum_research_agent.config import load_env
        from momentum_research_agent.brief_readiness import inspect_inputs
        from momentum_research_agent.tools.engine_pipeline import resolve_pipeline_root
        load_env(root)
        engine = resolve_pipeline_root(root)
        if engine is None:
            raise ValueError('No engine')
        result = inspect_inputs(engine, date.fromisoformat(sys.argv[2]))
        missing = sum(item['status'] not in ('covered', 'coverage_unverified') for item in result['inputs'].values())
        print(json.dumps({'ready': result['ready'], 'message': 'Inputs ready' if result['ready'] else f'{missing} input panels lack requested-date coverage'}))
    except Exception:
        print(json.dumps({'ready': False, 'message': 'Engine configuration or cached input coverage unavailable'}))


if __name__ == '__main__':
    main()
