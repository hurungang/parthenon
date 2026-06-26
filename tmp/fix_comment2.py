import sys
path = r'backend/app/services/agents/runtime_executor.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

target = 'Build response_format for structured output (task 9.8)'
idx = content.find(target)
sys.stdout.write(f"idx={idx}\n")
sys.stdout.flush()

if idx < 0:
    sys.stdout.write("NOT FOUND\n")
    sys.exit(1)

# Find full block to replace: from start of this comment line to the ToolStrategy import line
line_start = content.rfind('\n', 0, idx) + 1
block_end_marker = '\n        from langchain.agents.structured_output import ToolStrategy'
block_end = content.find(block_end_marker, idx)
sys.stdout.write(f"line_start={line_start}, block_end={block_end}\n")
sys.stdout.flush()

old_block = content[line_start:block_end]
sys.stdout.write(f"old_block=\n{repr(old_block)}\n")
sys.stdout.flush()

new_block = '        # \u2500\u2500 Build response_format for structured output \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n        # ToolStrategy uses tool calling \u2014 works on any model that supports tools.\n        # LangChain auto-promotes to ProviderStrategy when the model capability\n        # profile reports native structured-output support.'

content = content[:line_start] + new_block + content[block_end:]
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
sys.stdout.write("DONE\n")
sys.stdout.flush()
