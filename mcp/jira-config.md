# Jira MCP Server Configuration

## Server
- **name**: corp-jira
- **command**: node
- **args**: /Users/shashankshekhar/workspace/AI/adobe-mcp-servers/src/corp-jira/dist/index.js
- **transport**: stdio

## Required Environment Variables

These must be set in your shell before running the framework,
or placed in a `.env` file at the framework root.

- `JIRA_PERSONAL_ACCESS_TOKEN` — Your Jira Personal Access Token (generate from Jira profile → Personal Access Tokens)
- `JIRA_EMAIL` — Your email address (e.g., user@adobe.com)

## Optional Environment Variables
- `JIRA_API_BASE_URL` — Default: `https://jira.corp.adobe.com/rest/api/2`
- `JIRA_MAX_RESULTS` — Default: `50`
- `JIRA_TIMEOUT` — Default: `30000` (ms)

## Tools Used By This Framework

### search_jira_issues
Fetches ticket details by JQL query. Used to pull the full ticket
description, summary, acceptance criteria, and comments when
`--jira-ticket PROJ-123` is provided.

**Input**: `{ "jql": "key = PROJ-123", "minimizeOutput": false }`

### get_jira_comments
Fetches all comments on a ticket. Used to pull additional context
that may have been discussed in comments.

**Input**: `{ "issueKey": "PROJ-123" }`
