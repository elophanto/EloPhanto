# Research & Information Gathering

## Description

Comprehensive guide for researching topics, gathering information from the web, local files, and knowledge base, synthesizing findings, and preserving learned knowledge for future use.

## Triggers

- research
- find information
- look up
- summarize
- investigate
- analyze
- compare
- what is
- how does
- explain
- find out
- check
- verify
- learn about

## Instructions

### 1. Research Strategy Selection

Choose your approach based on the information source:

#### Knowledge Base First (Always Start Here)
1. knowledge_search with the query — you may already know this from past tasks
2. If results are relevant and sufficient, use them — no need for external research
3. If partial results, use them as context and supplement with other sources

#### Local File Research
1. file_list to find relevant files (use pattern matching: `*.py`, `*.md`)
2. file_read for specific files — use line ranges for large files
3. For code analysis, self_read_source gives better context for agent source files
4. For project-wide searches, shell_execute with grep/find for complex patterns

#### Web Research
1. browser_navigate to authoritative sources first (official docs, primary sources)
2. For general queries, start with a search engine (Google, DuckDuckGo)
3. browser_extract for text content, browser_read_semantic for structured overview
4. Cross-reference multiple sources when accuracy matters
5. For APIs, browser_get_network can reveal data endpoints directly

### 2. Source Hierarchy

Prioritize sources in this order:

1. **Primary sources** — Official documentation, original papers, company blogs,
   government sites, specification documents
2. **Authoritative aggregators** — Wikipedia (for overview), MDN (for web tech),
   Python docs (for Python)
3. **Community knowledge** — Stack Overflow (verified answers), GitHub issues,
   technical blogs with code examples
4. **General web** — News articles, forum posts, social media (lowest reliability)

### 3. Research Workflows

#### Fact-Checking / Verification
```
1. knowledge_search → check if we already know this
2. browser_navigate to the most authoritative source
3. browser_extract → get the relevant passage
4. If conflicting claims: check 2-3 additional sources
5. Report findings with source attribution
6. knowledge_write to save verified facts for future use
```

#### Topic Deep-Dive
```
1. knowledge_search → existing knowledge
2. browser_navigate → overview article (Wikipedia, docs homepage)
3. browser_read_semantic → structured overview of the topic
4. Identify key subtopics from the overview
5. browser_navigate to each subtopic's authoritative source
6. browser_extract → detailed information per subtopic
7. Synthesize findings into a structured summary
8. knowledge_write to preserve the research
```

#### Competitive / Comparison Research
```
1. Identify the items to compare
2. For each item:
   a. browser_navigate to its official site
   b. browser_extract → features, pricing, specs
   c. browser_navigate to review/comparison sites
3. Build a comparison matrix from collected data
4. Present findings with clear differentiators
```

#### Current Events / Recent Information
```
1. browser_navigate to news sources
2. browser_extract for article content
3. Check publication dates — prioritize the most recent
4. Cross-reference across 2-3 sources for accuracy
5. Distinguish between confirmed facts and speculation
```

#### Technical Documentation Lookup
```
1. browser_navigate directly to the docs site (e.g., docs.python.org)
2. Use the site's search if available:
   a. browser_get_elements to find the search input
   b. browser_type the query
   c. browser_get_elements to find results
3. browser_extract the relevant documentation section
4. If the docs are paginated, follow links to subpages
```

### 4. Information Synthesis

#### Lead with the Answer
- State the conclusion or answer first
- Then provide supporting evidence and sources
- Don't narrate the research process ("First I searched..., then I found...")

#### Handle Uncertainty
- If confident: state directly
- If likely but not certain: "Based on [source], this appears to be..."
- If conflicting: "Sources disagree — [source A] says X while [source B] says Y"
- If unknown: "I couldn't find reliable information on this"

#### Cite Sources
- When reporting facts from the web, mention where they came from
- For critical decisions, provide the URL so the user can verify
- Don't over-cite obvious/common knowledge

#### Structured Output
- For comparisons: use a table or structured list
- For explanations: start simple, add detail as needed
- For summaries: lead with key points, details below
- For data: present the most relevant subset, offer the full set

### 5. Preserving Knowledge

After completing research, save valuable findings:

```
knowledge_write:
  path: "learned/research/{topic}.md"
  content: |
    # Topic Name
    
    ## Summary
    Key findings in 2-3 sentences.
    
    ## Details
    The full research findings.
    
    ## Sources
    - [Source 1](url)
    - [Source 2](url)
    
    ## Last Updated
    YYYY-MM-DD
```

**When to save:**
- Factual information the user might ask about again
- Technical documentation lookups for tools/services the user uses
- Comparison research that took significant effort
- Any finding that required multiple sources to verify

**When NOT to save:**
- One-off queries the user won't revisit
- Information that changes rapidly (stock prices, weather)
- Content that's trivially searchable

### 6. Common Pitfalls

- **Don't guess** — if you're not sure, research it rather than stating potentially wrong information
- **Don't over-research** — for simple factual questions, one authoritative source is enough
- **Don't forget the knowledge base** — always check knowledge_search first before going to the web
- **Don't scrape paywalled content** — if a page requires login/payment, tell the user
- **Don't present search engine snippets as facts** — navigate to the actual page and read the full content
- **Don't ignore dates** — information from 2020 may be outdated in 2026; check recency

## Notes

The knowledge base (knowledge_search / knowledge_write) is your institutional
memory. Use it aggressively — every substantial research task should leave behind
a knowledge artifact for future sessions. The agent across sessions only remembers
what was explicitly saved to the knowledge base or task memory.
