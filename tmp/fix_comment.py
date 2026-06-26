path = r'c:\Users\rhu\source\personal\coding-workspace\Parthenon\backend\app\services\agents\runtime_executor.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

# Find the lines
idx = content.find('Build response_format for structured output (task 9.8)')
if idx >= 0:
    end = content.find('\nfrom langchain.agents.structured_output import ToolStrategy', idx)
    snippet = content[idx-12:end+60]
    print(repr(snippet[:500]))
else:
    print('NOT FOUND AT ALL')
