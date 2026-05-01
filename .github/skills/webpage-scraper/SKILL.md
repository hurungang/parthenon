---
name: webpage-scraper
description: Scrapes webpage content and converts it to clean markdown format. Use this when you need to retrieve and cache web content.
---

Use the built-in web_fetch tool to retrieve webpage content.
Clean up the content and convert to readable markdown format.
Preserve key information: title, headers, main content, links.
Remove ads, navigation, footers, and other boilerplate.

## Process

1. **Fetch**: Use `web_fetch` tool with the target URL
2. **Clean**: Remove navigation, ads, footers, sidebars
3. **Structure**: Organize content with clear headers
4. **Links**: Preserve important internal and external links
5. **Format**: Ensure proper markdown formatting
6. **Metadata**: Add source URL and retrieval date

## Example Usage

When asked to cache a webpage:

1. Call `web_fetch` with the URL
2. Extract the main content
3. Format as markdown with proper structure
4. Save to workspace/_cache/ with metadata header
5. Update workspace/references-metainfo.md with cache status
