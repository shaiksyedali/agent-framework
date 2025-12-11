# MCP Agent

The MCP (Model Context Protocol) Agent provides web intelligence and browser automation capabilities using Playwright.

## Tools

| Tool | Description |
|------|-------------|
| `playwright_scrape` | Scrape text and links from any webpage |
| `playwright_navigate` | Navigate with full browser, get accessibility snapshot |
| `playwright_screenshot` | Take screenshots of webpages |
| `playwright_get_text` | Extract text from specific CSS selectors |
| `playwright_click_and_get` | Click elements and capture results |

## Execution Modes

**1. HTTP Fallback (Default - Free)**
- Works for most static websites
- No configuration required
- Limited for JavaScript-heavy pages

**2. Browserless.io (Recommended for Production)**
- Full browser automation in the cloud
- Handles JavaScript, SPAs, dynamic content
- Free tier: 1000 units/month
- Configure: `BROWSERLESS_API_KEY=your-key`

**3. Local Playwright**
- Free and open source
- For local development only (not Azure Functions)
- Install: `pip install playwright && playwright install chromium`

## Example Workflow

```yaml
name: "Competitor Website Analysis"
steps:
  - name: "Scrape Competitor Pricing"
    agent: mcp_agent
    description: "Get pricing info from competitor website"
    
  - name: "Screenshot Homepage"
    agent: mcp_agent
    description: "Take screenshot of competitor homepage"
    
  - name: "Analyze and Report"
    agent: response_generator
```

## Configuration

Add to `.env.azure` (optional - for cloud browser):
```bash
# Browserless.io cloud browser
BROWSERLESS_API_KEY=your-browserless-api-key
```

Without Browserless, the agent uses HTTP requests which work for most websites but may miss JavaScript-rendered content.

## Limitations

1. **Rate Limits**: Browserless free tier has monthly limits
2. **JavaScript**: HTTP fallback can't execute JavaScript
3. **Authentication**: Cannot access login-protected pages
4. **Click actions**: Limited in Azure Functions without Browserless
