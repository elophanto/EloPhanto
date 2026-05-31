"""Strategy generation prompts — port of tmp/strategy.js (Phase 11).

Verbatim port of the operator's proven strategy-creator prompts from
their other app. Keeping it 1:1 lets the operator maintain the prompt
once and diff changes across apps. Schema additions for EloPhanto
(``vault_requirements``, ``tool_requirements``, ``voice_seed``,
``agent_role_assignments``, ``execution_priority``) are appended to
the JSON schema section.

When the operator updates the upstream strategy.js, mirror the
changes here verbatim. See ``docs/76-ABE-FRAMEWORK.md`` §Phase 11.
"""

from __future__ import annotations

from typing import Any

_FOCUS_DESCRIPTIONS: dict[str, str] = {
    "full": "",
    "geo": """
STRATEGY FOCUS: Generative Engine Optimization (GEO)
Focus exclusively on optimizing for AI search engines (ChatGPT, Perplexity, Gemini, Copilot).
Key areas: structured content for LLM citation, schema markup, entity optimization, FAQ-rich pages,
authority signals, question-format content that matches how people query AI assistants.
Do NOT include traditional paid advertising tactics — focus on content and authority building.""",
    "seo": """
STRATEGY FOCUS: Search Engine Optimization (SEO)
Focus on organic search visibility, keyword strategy, technical SEO, content optimization,
backlink building, and SERP feature optimization. Include both quick wins and long-term plays.""",
    "content": """
STRATEGY FOCUS: Content Strategy
Focus on content creation, distribution, and amplification. Cover content pillars, formats,
editorial calendar, repurposing workflows, and content-led growth.""",
    "paid": """
STRATEGY FOCUS: Paid Advertising
Focus on paid channel strategy across search, social, display, and programmatic.
Cover budget allocation, audience targeting, creative strategy, and ROAS optimization.""",
    "social": """
STRATEGY FOCUS: Social Media Strategy
Focus on organic and paid social presence, platform selection, content cadence,
community building, influencer partnerships, and social commerce.""",
    "email": """
STRATEGY FOCUS: Email & Lifecycle Marketing
Focus on email strategy, automation flows, segmentation, personalization,
deliverability, and lifecycle marketing across acquisition, activation, retention.""",
    "brand": """
STRATEGY FOCUS: Brand Strategy
Focus on brand positioning, messaging architecture, visual identity guidelines,
brand voice, competitive differentiation, and brand awareness building.""",
}

_MODE_DESCRIPTIONS: dict[str, str] = {
    "standard": """Create a comprehensive, data-driven marketing strategy using proven frameworks from top agencies.

REFERENCE CAMPAIGNS TO LEARN FROM:
- Slack's "So Yeah, We Tried Slack" (B2B viral through authenticity, 8,000 companies in 24hrs)
- HubSpot's Inbound Marketing Flywheel (content-led growth, $1B+ company built on free tools)
- Mailchimp's "Did You Mean Mailchimp?" (9 fake brands, 67M impressions, Cannes Lions winner)
- Spotify Wrapped (User-Generated Content engine, 60M shares annually, zero ad spend)
- Notion's Template Gallery (community-led growth, 30M users through user-created templates)

STRATEGIC FRAMEWORKS TO APPLY:
- Paid, Earned, Shared, Owned (PESO) Model - integrating all media types
- Reach, Act, Convert, Engage (RACE) Framework - full customer journey
- See-Think-Do-Care - intent-based marketing framework by Google
- Jobs-to-be-Done (JTBD) - focus on customer outcomes, not features""",
    "unconventional": """Create highly creative, unconventional marketing strategies that break category conventions and earn massive attention.

LEGENDARY VIRAL CAMPAIGNS TO EMULATE:
- Dollar Shave Club: $4,500 video -> $1B acquisition. Hook: "Our blades are f***ing great." 26M views.
- Cards Against Humanity: Black Friday "Nothing" sale ($71,145 for nothing), Holiday Hole ($100k to dig a hole)
- Liquid Death: Canned water positioned as punk rock. Sold $3 for water by making it cool. $700M valuation.
- Wendy's Twitter: Roasting competitors, "Nuggs for Carter" (3.6M retweets), savage clap-backs
- BrewDog: "Equity for Punks" crowdfunding ($92M raised), naming beers after politicians
- MSCHF: "Satan Shoes" with Lil Nas X (sold out in 1 minute, dominated news cycle for weeks)
- Oatly: Intentionally awkward ads, sued by dairy industry and turned it into marketing gold

UNCONVENTIONAL TACTICS THAT WORK:
- Manufactured controversy (pick a fight with the industry status quo)
- Absurdist humor (the weirder, the more shareable)
- Transparency stunts (share your failures, real numbers, internal memos)
- Enemy marketing (explicitly call out who you're NOT for)
- Limited/artificial scarcity (Supreme model)
- Reverse psychology ("Don't buy this" - Patagonia's Black Friday)""",
    "guerrilla": """Focus on low-budget, high-impact guerrilla marketing tactics that maximize ROI with minimal spend.

GUERRILLA PRINCIPLES:
- Hijack attention (newsjacking, trend-riding, competitor moments)
- Create FOMO (waitlists, invite-only, limited access)
- Weaponize your constraints (turn small budget into authenticity)
- Community as distribution (your users become your marketing team)
- Remarkable > good (Purple Cow - worth remarking about)""",
    "brand-awareness": """Prioritize rapid brand awareness and visibility strategies that get quick results.

RAPID AWARENESS TACTICS:
- Newsjacking (respond within hours)
- Influencer seeding (100 micro > 1 mega for reach)
- Podcast tour strategy (20-50 niche podcasts in 90 days)
- HARO / journalist outreach (become the quoted expert)
- Community embedding (Slack groups, Discords, subreddits)""",
    "controversial": """Generate bold, controversial strategies that push boundaries and dominate the conversation (while staying legal and ethical).

CALCULATED CONTROVERSY PRINCIPLES:
- Punch UP, not down
- Have a defensible position
- Prepare for backlash
- Ladder to brand values (not controversy for its own sake)
- Speed matters (24-48 hours)""",
}


def _budget_tier(budget_type: str, budget: float) -> str:
    if budget_type == "organic" or budget == 0:
        return "organic"
    if budget < 2000:
        return "bootstrap"
    if budget < 10000:
        return "growth"
    if budget < 50000:
        return "scale"
    return "enterprise"


def _budget_focus_line(tier: str) -> str:
    return {
        "organic": "- Focus: Zero-cost tactics only. Content, community, SEO, partnerships, earned media. No paid channels.",
        "bootstrap": "- Focus: Organic tactics, community, content, partnerships. Every dollar must have 10x potential.",
        "growth": "- Focus: Mix of paid and organic. Test paid channels, double down on what works. Build systems.",
        "scale": "- Focus: Omnichannel presence. Invest in brand AND performance. Build team/agency support.",
        "enterprise": "- Focus: Market leadership. Brand campaigns, sophisticated attribution, multi-touch strategies.",
    }.get(tier, "")


def _risk_line(risk: int) -> str:
    if risk < 30:
        return "- Conservative: Prioritize proven tactics with predictable returns. Minimize brand risk."
    if risk < 60:
        return "- Balanced: Mix of proven tactics with some experimental plays. Calculated risks."
    if risk < 80:
        return "- Aggressive: Bold moves, competitive disruption, attention-grabbing tactics."
    return "- Very Aggressive: Category disruption, controversial plays, high-risk/high-reward bets."


def build_system_prompt(
    *,
    strategy_mode: str = "standard",
    focus: str = "full",
    budget_type: str = "mixed",
    budget: float = 5000,
    budget_period: str = "monthly",
    risk_tolerance: int = 50,
    include_controversial: bool = False,
    context: str = "",
    available_tools: list[tuple[str, str]] | None = None,
) -> str:
    """Port of getSystemPrompt() from tmp/strategy.js.

    ``available_tools`` is the live registry as ``[(name, description), ...]``
    pairs. When supplied, the prompt renders a "TOOLS ALREADY AVAILABLE"
    block AND a hard rule telling the LLM to reference those exact
    names rather than invent new capability strings — which used to
    cause every strategy to ship with hallucinated `tool_requirements`
    that became `missing_tool` blockers (e.g. `x_post_and_reply` when
    `twitter_post`+`twitter_reply` already exist). When omitted, the
    prompt falls back to the legacy "list tools you assume exist"
    shape — kept for back-compat with any test fixture / external
    caller that doesn't have a registry handle.
    """

    is_organic = budget_type == "organic" or budget == 0
    tier = _budget_tier(budget_type, budget)
    mode_block = _MODE_DESCRIPTIONS.get(strategy_mode, _MODE_DESCRIPTIONS["standard"])
    focus_block = _FOCUS_DESCRIPTIONS.get(focus, "")

    budget_line = (
        "BUDGET TIER CONTEXT: ORGANIC (No paid budget — organic/earned tactics only)"
        if is_organic
        else f"BUDGET TIER CONTEXT: {tier.upper()} (${int(budget):,} {budget_period})"
    )
    budget_focus = _budget_focus_line(tier)
    risk_block = _risk_line(risk_tolerance)
    context_block = (
        f"""
PRIOR RESEARCH & CONTEXT (from previous analysis steps):
{context}
Use these findings to ground the strategy in real data rather than assumptions."""
        if context
        else ""
    )

    # Render the live tool registry so the LLM stops inventing
    # capability names. One line per tool: ``- <name>: <short desc>``.
    # The block lives early in the prompt (after context, before the
    # JSON schema) and is referenced by name in the tool_requirements
    # field instructions below. If absent, the legacy "list any tool"
    # shape applies.
    registry_block = ""
    if available_tools:
        lines = ["TOOLS ALREADY AVAILABLE (use these EXACT names):"]
        for name, desc in available_tools:
            short = (desc or "").splitlines()[0][:90]
            lines.append(f"- {name}: {short}" if short else f"- {name}")
        registry_block = "\n".join(lines) + "\n"
    controversial_block = (
        """
CONTROVERSIAL MODE ENABLED:
Include at least 2 edgy, provocative tactics that will generate conversation and press. These should:
- Challenge industry norms or call out competitors
- Take a strong stance that some will disagree with
- Have viral/newsworthy potential
- Be defensible and align with brand values"""
        if include_controversial
        else ""
    )

    allocation_block = (
        '"resourceAllocation": { "ChannelOrTactic1": "time/effort percentage (e.g., 40%)" },'
        if is_organic
        else '"budgetAllocation": { "SpecificChannelName1": "percentage (e.g., 55%)" },'
    )
    allocation_note = (
        "CRITICAL FOR RESOURCE ALLOCATION: Since this is an organic/no-budget strategy, allocate TIME and EFFORT (not money) across tactics. Use resourceAllocation with percentage of effort per tactic."
        if is_organic
        else "CRITICAL FOR BUDGET ALLOCATION: Use the ACTUAL channel names from the user's preferred channels (not placeholder names). Distribute the budget across the user's specified marketing channels based on their strategy goals."
    )

    return f"""You are an elite marketing strategist from a $1M+/year agency. You've worked with brands from startups to Fortune 500, and you bring battle-tested frameworks, real campaign learnings, and data-driven insights to every strategy.

YOUR AGENCY PHILOSOPHY:
1. STRATEGY BEFORE TACTICS - Every tactic must ladder to a clear strategic objective
2. DISTINCTIVE > DIFFERENT - Create memory structures, not just differentiation
3. COMPOUND EFFECTS - Prioritize tactics that build on each other over time
4. MEASURE WHAT MATTERS - Vanity metrics are a distraction; focus on business outcomes
5. SPEED TO LEARN - Launch fast, iterate faster, perfection is the enemy

{mode_block}
{focus_block}

{budget_line}
{budget_focus}

{context_block}

{registry_block}
RISK TOLERANCE: {risk_tolerance}%
{risk_block}

{controversial_block}

CRITICAL JSON FORMATTING RULES - MUST FOLLOW EXACTLY:
1. Output ONLY valid JSON. No markdown, no code blocks, no explanations.
2. Start your response with {{ and end with }}
3. Use ONLY double quotes for strings, never single quotes
4. Properly escape ALL special characters in strings
5. NO trailing commas in arrays or objects
6. NO comments or explanatory text outside the JSON
7. NO emojis. Language-specific diacritics/accents ARE ALLOWED.
8. Replace curly quotes with straight quotes; em dashes with --; ellipsis with three dots

Return a comprehensive marketing strategy as a single JSON object with this ENHANCED structure:
{{
  "assumptions": ["If key inputs are missing, state the assumption explicitly"],
  "inputsToConfirm": ["List the 3-7 highest-leverage questions that would materially improve the plan"],
  "strategyName": "Catchy strategy name",
  "tagline": "Memorable one-liner",
  "strategicInsight": "The key insight that makes this strategy work",
  "overview": "Executive summary",
  "coreMessage": "Key brand message",
  "positioningStatement": "For [target], [brand] is the [category] that [key benefit] because [reason to believe]",
  "audienceSegments": [{{
    "name": "Segment name",
    "whoTheyAre": "Specific description",
    "jobToBeDone": "What they are trying to accomplish",
    "topPainPoints": ["Pain 1", "Pain 2"],
    "topObjections": ["Objection 1", "Objection 2"],
    "messageAngle": "Angle that resonates",
    "proofToUse": "Evidence to emphasize"
  }}],
  "offerAndFunnel": {{
    "primaryOffer": "Concrete offer",
    "valueProps": ["Value prop 1"],
    "funnelStages": [{{
      "stage": "Awareness|Consideration|Conversion|Retention",
      "goal": "What success means",
      "primaryChannels": ["Exact channel name"],
      "keyAssets": ["Asset 1"],
      "primaryCTA": "CTA"
    }}]
  }},
  "tactics": [{{
    "priority": 1,
    "name": "Tactic name",
    "description": "Detailed description",
    "channel": "Specific marketing channel name",
    "budget": "Estimated budget as plain text",
    "timeline": "Implementation timeline",
    "expectedImpact": "High/Medium/Low",
    "riskLevel": "High/Medium/Low",
    "timeToImpact": "Days/Weeks/Months",
    "dependencies": ["Dependency 1"],
    "implementation": ["Step 1", "Step 2"],
    "successMetrics": "KPI with target",
    "inspiredBy": "Real campaign or proven framework"
  }}],
  "contentIdeas": [{{
    "type": "Content type",
    "title": "Content title",
    "description": "Content description",
    "viralPotential": "High/Medium/Low"
  }}],
  "creativeDirections": [{{
    "angleName": "Angle name",
    "hookTemplates": ["Hook template 1"],
    "proofPoints": ["Proof 1"],
    "ctaVariants": ["CTA 1"],
    "bestForChannels": ["Exact channel name"]
  }}],
  "metrics": ["KPI 1"],
  "risks": [{{ "risk": "What could go wrong", "mitigation": "How to prevent/respond" }}],
  "experimentRoadmap": [{{
    "hypothesis": "If we do X, then Y will happen because Z",
    "test": "What we will run",
    "primaryMetric": "Metric + threshold",
    "duration": "How long",
    "successCriteria": "When to scale/kill",
    "priority": "High/Medium/Low"
  }}],
  "measurementPlan": {{
    "northStarMetric": "Primary success metric",
    "supportingKPIs": ["KPI 1"],
    "trackingSetup": ["UTMs"],
    "reportingCadence": "Weekly / biweekly",
    "attributionNotes": "How to interpret results"
  }},
  "timeline": {{ "month1": ["Activity 1"], "month2": ["Activity 2"], "month3": ["Activity 3"] }},
  {allocation_block}
  "quickWins": ["Quick win 1"],
  "longTermPlays": ["Long-term play 1"],
  "projectedROI": {{
    "conservative": "Expected minimum outcome",
    "realistic": "Most likely outcome",
    "optimistic": "Best case outcome"
  }},

  "vault_requirements": [{{
    "key": "Required vault credential key (e.g. smtp_company, twitter_session)",
    "needed_for_tactics": ["t1"],
    "resolution_proposal": "ask",
    "note": "Why this credential is needed"
  }}],
  "tool_requirements": [{{
    "tool_name": "Required tool name (e.g. linkedin_post)",
    "needed_for_tactics": ["t5"],
    "resolution_proposal": "build",
    "build_method": "self_create_plugin",
    "build_hint": "Hint for the build tool (one sentence)"
  }}],
  "voice_seed": {{
    "hookTemplates": ["POV: <scenario>"],
    "banned_phrases": ["leverage", "synergy"],
    "tone": ["direct", "concrete"],
    "cta_style": "soft — one line"
  }},
  "agent_role_assignments": {{
    "sales": ["t1", "t3"],
    "content": ["t2"]
  }},
  "execution_priority": "staged"
}}

{allocation_note}

SURFACE COVERAGE (CRITICAL):
When the user prompt's PRIOR RESEARCH & CONTEXT contains an OPERATIONAL CONTEXT block (active schedules / ledger sums / prospect funnel / active missions), the strategy MUST address every distinct surface listed there, not just the company's primary `what_we_sell`. A multi-surface business (e.g. a paid-jobs offering PLUS a token economy PLUS a public X/livestream growth loop) needs tactics that cover EACH surface, with explicit allocation across them in `budgetAllocation` / `resourceAllocation`. A strategy that ignores 4 of 5 active surfaces and calls it done is wrong — flag it as `inputsToConfirm` if you genuinely can't reconcile, but the default expectation is comprehensive coverage. Identify each surface from the OPERATIONAL CONTEXT block and name it as a `funnelStages.primaryChannels` entry or its own tactic.

ABE EXTENSIONS (EloPhanto-specific — populate when relevant):
- vault_requirements: every credential the strategy assumes the operator has stored (SMTP keys, social-platform sessions, API tokens). Each entry needs a `key` (vault key name in snake_case), `needed_for_tactics` (tactic ids it gates), and a `resolution_proposal` of "ask" (operator provides), "build" (only if the *credential itself* can be auto-generated, rare), or "defer". Be exhaustive — missing vault entries become operator blockers.
- tool_requirements: tools/connectors the strategy NEEDS to execute. CRITICAL: ONLY list tools that are NOT already in the "TOOLS ALREADY AVAILABLE" block above. If a tactic can be executed by an existing tool, do NOT list anything for it here — the registry already covers it. When a genuine gap exists: use snake_case names matching the registry's naming convention (`twitter_post` not `x_post_and_reply`, `email_send` not `send_email`); for each, propose "build" with `build_method: "self_create_plugin"` and a one-sentence `build_hint`, OR "ask" if it's a third-party integration the operator must provide, OR "defer" if the tactic can be skipped.
- voice_seed: 3-6 hookTemplates extracted from creativeDirections, 3-8 banned_phrases that contradict the desired voice, 2-4 tone descriptors, and a single cta_style. This pre-seeds Phase 10's voice contract so drafts are lint-gated on day one.
- agent_role_assignments: optional advisory map from role names (sales/content/ops/support/marketing/ceo) to tactic ids. The arbiter still rotates roles by KPI/staleness; this is a hint, not a lock.
- execution_priority: "immediate" (all tactics start day 1), "staged" (default — month1/2/3 ramp), "experimental" (each tactic gated by experiment roadmap).

Remember: Output ONLY the JSON object. No reasoning, no markdown, no code blocks, just pure JSON.
"""


def build_user_prompt(*, inputs: dict[str, Any]) -> str:
    """Port of getUserPrompt() from tmp/strategy.js.

    ``inputs`` mirrors the params object — businessName, productName,
    industry, targetAudience, productDescription, uniqueSellingPoints,
    competitors, currentChallenges, budget, budgetPeriod, budgetType,
    strategyMode, focus, goals, riskTolerance, channels, timeline,
    context.
    """

    def s(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, list):
            return ", ".join(str(v) for v in val)
        return str(val)

    business_name = s(
        inputs.get("businessName") or inputs.get("productName") or "Unknown Business"
    )
    industry = s(inputs.get("industry") or "")
    product_description = s(
        inputs.get("productDescription") or inputs.get("prompt") or ""
    )
    target_audience = s(inputs.get("targetAudience") or "General audience")
    usps = s(inputs.get("uniqueSellingPoints") or "")
    competitors = s(inputs.get("competitors") or "")
    challenges = s(inputs.get("currentChallenges") or "")
    budget = float(inputs.get("budget") or 5000)
    budget_period = s(inputs.get("budgetPeriod") or "monthly")
    budget_type = s(inputs.get("budgetType") or "mixed")
    risk = int(inputs.get("riskTolerance") or 50)
    goals_list = inputs.get("goals") or []
    channels_list = inputs.get("channels") or []
    timeline = s(inputs.get("timeline") or "")
    context = s(inputs.get("context") or "")
    focus = s(inputs.get("focus") or "")
    is_organic = budget_type == "organic" or budget == 0

    channels_bullets = (
        "\n".join(f"- {s(c)}" for c in channels_list)
        if channels_list
        else "- (none provided)"
    )

    return f"""=== CLIENT BRIEF ===

COMPANY: {business_name}
INDUSTRY: {industry or "Not specified (infer from product/service)"}
{f"PRODUCT/SERVICE: {product_description}" if product_description else ""}

TARGET CUSTOMER:
{target_audience}

{f"UNIQUE VALUE PROPOSITION:{chr(10)}{usps}" if usps else "UNIQUE VALUE PROPOSITION: Not provided - identify the most compelling angle from the product/service description"}

{f"COMPETITIVE LANDSCAPE:{chr(10)}{competitors}" if competitors else ""}

{f"CURRENT CHALLENGES:{chr(10)}{challenges}" if challenges else ""}

=== CAMPAIGN PARAMETERS ===

{"BUDGET: Organic only (no paid budget)" if is_organic else f"BUDGET: ${int(budget):,} {budget_period}"}
{f"STRATEGY FOCUS: {focus}" if focus else ""}

RISK TOLERANCE: {risk}%

PRIMARY OBJECTIVES:
{s(goals_list) or "Increase awareness and sales"}

SELECTED CHANNELS:
{channels_bullets}

TIMELINE: {timeline or "3-month rolling strategy with quick wins in Month 1"}

{f"=== PRIOR RESEARCH & CONTEXT ==={chr(10)}{context}{chr(10)}Use these findings to inform the strategy. Do not repeat this research — build ON it." if context else ""}

CRITICAL REQUIREMENTS:
{"- This is an organic strategy - do NOT suggest paid channels or ad spend; use resourceAllocation (effort %)" if is_organic else f"- Budget allocation keys MUST each be one of the listed channels:{chr(10)}{channels_bullets}"}
- All metrics must be specific (e.g., "Increase website traffic by 40%" not "Improve traffic")
- Make this strategy distinctive - avoid generic advice that could apply to any company
- Populate vault_requirements, tool_requirements, voice_seed, agent_role_assignments, execution_priority per the schema above. Missing ABE extensions weaken the autonomy loop.

Output ONLY valid JSON following the exact structure specified.
"""
