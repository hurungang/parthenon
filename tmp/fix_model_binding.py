import sys
sys.stdout.reconfigure(encoding='utf-8')

FILE = r'c:\Users\rhu\source\personal\coding-workspace\Parthenon\backend\app\services\agents\model_binding.py'

with open(FILE, encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

def find_line(keyword, start=0):
    for i, line in enumerate(lines[start:], start):
        if keyword in line:
            return i
    return -1

stubs_start = find_line('Legacy stubs kept for backward compatibility')
resolve_api_key_line = find_line('def _resolve_api_key(')
call_openai_line = find_line('async def _call_openai_compat(', resolve_api_key_line)
extract_text_line = find_line("def extract_text(response: dict[str, Any]")
extract_tool_calls_line = find_line("def extract_tool_calls(")

print(f'stubs_start: {stubs_start} (1-based: {stubs_start+1})')
print(f'resolve_api_key_line: {resolve_api_key_line} (1-based: {resolve_api_key_line+1})')
print(f'call_openai_line: {call_openai_line} (1-based: {call_openai_line+1})')
print(f'extract_text_line: {extract_text_line} (1-based: {extract_text_line+1})')
print(f'extract_tool_calls_line: {extract_tool_calls_line} (1-based: {extract_tool_calls_line+1})')

# Build the new file content:
# Part 1: Everything up to (not including) the stubs comment
part1 = '\n'.join(lines[:stubs_start])

# Part 2: _resolve_api_key (from resolve_api_key_line to call_openai_line - 1)
part2 = '\n'.join(lines[resolve_api_key_line:call_openai_line - 1])  # -1 to skip blank line before _call_openai

# Part 3: The new extract_text, plus everything from extract_tool_calls onward
# (extract_tool_calls and extract_usage are already updated)
# We need to SKIP the old extract_text (extract_text_line to extract_tool_calls_line - 2)
new_extract_text = '''    @staticmethod
    def extract_text(response, provider) -> str:
        """Extract the assistant\\'s text response from a model response.

        Accepts either a LangChain AIMessage (from the LangChain dispatch path)
        or a raw provider response dict (for backward compat with mocked tests).
        Returns \\"\\" when the response is empty or unrecognised.
        """
        # LangChain AIMessage path (new)
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
                    if isinstance(block, str):
                        return block
            return ""

        # Raw dict path (backward compat / test mocks)
        if not isinstance(response, dict):
            return ""

        provider_str = provider.value if isinstance(provider, ModelProvider) else provider

        if provider_str in (
            "openai", "litellm_proxy", "azure_openai", "mistral", "groq",
            "together", "fireworks", "perplexity", "deepseek",
        ):
            choices = response.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

        if provider_str == "anthropic":
            content = response.get("content", [])
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")

        if provider_str == "gemini":
            candidates = response.get("candidates", [])
            for cand in candidates:
                parts = cand.get("content", {}).get("parts", [])
                for part in parts:
                    text = part.get("text")
                    if isinstance(text, str):
                        return text

        if provider_str == "cohere":
            return response.get("text", "")

        return ""
'''

part3 = '\n'.join(lines[extract_tool_calls_line - 2:])

convert_fn = '''

def _convert_to_lc_messages(messages):
    """Convert Parthenon message dicts to LangChain message objects.

    Handles all Parthenon message roles:
    - "system"    -> SystemMessage
    - "user"      -> HumanMessage
    - "assistant" -> AIMessage (with tool_calls converted from OpenAI raw format)
    - "tool"      -> ToolMessage
    """
    import json as _json
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = str(content)

        if role == "system":
            result.append(SystemMessage(content=content))

        elif role == "user":
            result.append(HumanMessage(content=content))

        elif role == "assistant":
            raw_tool_calls = msg.get("tool_calls") or []
            if raw_tool_calls:
                lc_tool_calls = []
                for tc in raw_tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    func = tc.get("function") or {}
                    args_raw = func.get("arguments", "{}")
                    try:
                        args = _json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                    except (ValueError, TypeError):
                        args = {}
                    lc_tool_calls.append({
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "args": args,
                        "type": "tool_call",
                    })
                result.append(AIMessage(content=content, tool_calls=lc_tool_calls))
            else:
                result.append(AIMessage(content=content))

        elif role == "tool":
            result.append(ToolMessage(
                content=content,
                tool_call_id=msg.get("tool_call_id", ""),
            ))

        else:
            result.append(HumanMessage(content=content))

    return result
'''

new_content = part1 + '\n\n' + part2 + '\n\n' + new_extract_text + '\n' + part3

# Append _convert_to_lc_messages at the end if not already there
if '_convert_to_lc_messages' not in new_content:
    new_content = new_content.rstrip() + convert_fn

with open(FILE, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Done! File written.")
print(f"New line count: {len(new_content.split(chr(10)))}")
