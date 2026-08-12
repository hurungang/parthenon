"""Cleanup script for test_model_binding.py — remove deleted dispatch tests."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

FILE = r'c:\Users\rhu\source\personal\coding-workspace\Parthenon\backend\tests\unit\test_model_binding.py'

with open(FILE, encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

def find_line(keyword, start=0):
    for i, line in enumerate(lines[start:], start):
        if keyword in line:
            return i
    return -1

# Find key line indices (0-based)
phase52_comment = find_line('Eight new providers (Phase 5.2)')
provider_registry_import_start = find_line('from app.services.agents.model_binding import', phase52_comment)
provider_registry_import_end = find_line(')', provider_registry_import_start + 1)

# Find test_provider_registry section start
test_prov_reg_start = find_line('def test_provider_registry_covers_all_twelve_providers')
# Find test_resolve_model_config_finds_matching_config_for_new_provider (keep this)
test_resolve_new_prov = find_line('def test_resolve_model_config_finds_matching_config_for_new_provider')
# Find test_dispatch start (delete from here)
test_dispatch_start = find_line('def test_dispatch_routes_new_openai_compat_provider_to_openai_caller')
# Find extractor coverage section (keep from here)
extractor_section = find_line('# \u2500\u2500 Extractor coverage for the new providers')
# Find 4xx log section (delete from here to end)
fourxx_section = find_line('# \u2500\u2500 Task 2.6 / 5.2: 4xx / 5xx provider-key log assertion')

print(f'phase52_comment: {phase52_comment+1}')
print(f'provider_registry_import_start: {provider_registry_import_start+1}')
print(f'provider_registry_import_end: {provider_registry_import_end+1}')
print(f'test_prov_reg_start: {test_prov_reg_start+1}')
print(f'test_resolve_new_prov: {test_resolve_new_prov+1}')
print(f'test_dispatch_start: {test_dispatch_start+1}')
print(f'extractor_section: {extractor_section+1}')
print(f'fourxx_section: {fourxx_section+1}')

# Build new content:
# Part 1: Lines 0 to phase52_comment (exclusive) - everything before Phase 5.2 comment
part1_lines = lines[:phase52_comment]

# Part 2: NEW_PROVIDERS list definitions (needed for test_resolve_model_config_finds_matching_config_for_new_provider)
# These are at lines provider_registry_import_end+2 to test_prov_reg_start-1
# Actually, let's just find the NEW_PROVIDERS definition
new_providers_start = find_line('NEW_PROVIDERS: list[ModelProvider] = [', phase52_comment)
new_providers_end = find_line(']', new_providers_start + 1)  # find the closing ]
# Only keep NEW_PROVIDERS (not NEW_OPENAI_COMPAT_PROVIDERS or NATIVE_PROVIDERS, since they're only used in deleted tests)
new_providers_block = lines[new_providers_start:new_providers_end + 1]
print(f'new_providers_start: {new_providers_start+1}')
print(f'new_providers_end: {new_providers_end+1}')

# Part 3: test_resolve_model_config_finds_matching_config_for_new_provider (lines test_resolve_new_prov to test_dispatch_start-1)
test_resolve_block = lines[test_resolve_new_prov - 3:test_dispatch_start - 1]  # include decorators

# Part 4: extractor tests (lines extractor_section to fourxx_section-1)
extractor_block = lines[extractor_section:fourxx_section]

# Combine
new_lines = part1_lines + [''] + new_providers_block + [''] + test_resolve_block + extractor_block
new_content = '\n'.join(new_lines).rstrip() + '\n'

with open(FILE, 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f'\nDone! Old: {len(lines)} lines -> New: {len(new_lines)} lines')
