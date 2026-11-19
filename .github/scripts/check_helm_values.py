"""Fail on keys in our Helm values that the chart does not define.

Helm silently ignores unknown keys, so a typo like `retenion: 7d` would deploy the chart default.
Usage: check_helm_values.py <values.yml> <untarred chart dir>
"""
import sys
from pathlib import Path

import yaml

# Maps the chart passes through verbatim (any key is valid inside them).
FREE_FORM = {"grafana.grafana.ini"}
# Keys the chart templates read but values.yaml leaves undefined (only in comments).
TEMPLATE_ONLY = {"grafana.service.nodePort"}  # charts/grafana/templates/service.yaml


def deep_merge(base, override):
    """Parent chart values override subchart defaults key by key, not whole sections."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def chart_defaults(chart):
    defaults = yaml.safe_load((chart / "values.yaml").read_text())
    for sub in (chart / "charts").iterdir():
        if (sub / "values.yaml").exists():
            defaults[sub.name] = deep_merge(yaml.safe_load((sub / "values.yaml").read_text()) or {},
                                            defaults.get(sub.name) or {})
    return defaults


def unknown_keys(ours, defaults, path=""):
    for key, value in ours.items():
        full = f"{path}.{key}" if path else key
        if full in FREE_FORM or full in TEMPLATE_ONLY:
            continue
        if key not in defaults:
            yield full
        elif isinstance(value, dict) and isinstance(defaults[key], dict) and defaults[key]:
            yield from unknown_keys(value, defaults[key], full)


if __name__ == "__main__":
    values, chart = yaml.safe_load(Path(sys.argv[1]).read_text()), Path(sys.argv[2])
    unknown = list(unknown_keys(values, chart_defaults(chart)))
    for key in unknown:
        print(f"::error file={sys.argv[1]}::unknown Helm value '{key}' (not defined by the chart)")
    sys.exit(1 if unknown else 0)
