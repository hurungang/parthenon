#!/usr/bin/env python3
"""Test YAML source loading."""
import sys
sys.path.insert(0, 'backend')
from app.core.config import Settings, _identity_yaml_path, _SparseYamlSource
from pathlib import Path

yaml_path = _identity_yaml_path()
print(f'YAML path: {yaml_path}')
print(f'Exists: {Path(yaml_path).exists()}')
print()

# Try to manually call the YAML source
yaml_source = _SparseYamlSource(Settings, yaml_file=Path(yaml_path))
data = yaml_source()
print(f'YAML source returned keys: {list(data.keys())}')
print()
print('Full data:')
for key, value in data.items():
    print(f'  {key}: {value}')
print()
print(f'Contains "audience": {"audience" in data}')
print(f'Contains "jwt_audience": {"jwt_audience" in data}')
if 'audience' in data:
    print(f'audience value: {data["audience"]}')
if 'jwt_audience' in data:
    print(f'jwt_audience value: {data["jwt_audience"]}')
