"""
NBA Gemini prompt template.
"""


def _build_nba_prompt(plays: list, games_section: str, n_eliminated: int) -> str:
    return f"""# SHARP BETTING ANALYSIS: NBA SLATE

## TASK
You are a professional NBA sharp handicapper with 15 years of experience. Analyze today's slate and select the SINGLE highest-value betting opportunity from the exact options provided below.

---

## PERMITTED BETTING OPTIONS

{games_section}

---

## 🚨 ABSOLUTE CONSTRAINTS 🚨

**1. LINE DISCIPLINE:**
- These {len(plays)} lines ARE the market consensus
- Do NOT claim different lines exist elsewhere ("the real line is -11.5")
- Do NOT recommend lines not listed above
- The final recommendation MUST be copy-pasted exactly from the list above

**2. MANDATORY OUTPUT SECTIONS:**
- **SHARP BET SELECTION:** Pick ONE option from the {len(plays)} above
- **ELIMINATED OPTIONS:** Explain why ALL {n_eliminated} non-selected options were eliminated

**If you violate either constraint, your analysis is invalid.**

---

## RESEARCH FRAMEWORK

Analyze each of the {len(plays)} options through these factors:

**Factor 1: Market Psychology** - Public bias, recency bias, contrarian value, anchoring effect
**Factor 2: Statistical Matchup** - Offensive/defensive ratings, pace, efficiency, turnover differential (last 15 games)
**Factor 3: Injuries & Personnel** - Key player status, depth, lineup continuity. on/off net rating
**Factor 4: Situational Spots** - Rest, schedule, motivation, home/road context. travel fatigue (time zones/miles)
**Factor 5: Tactical Matchup & Possession Edges** - Rebounding differentials, free-throw rates, and the mathematical shot profile (3-point volume vs. points in the paint)

---

## REQUIRED OUTPUT FORMAT

### SHARP BET SELECTION

**Recommended Bet:** [Copy-paste exactly from the {len(plays)} options above]

**Why This is the Play:**
[2-3 paragraphs explaining which factors create the edge and why this specific line is mispriced]

**Edge Breakdown:**
1. **Market Psychology:** [Strong/Moderate/Weak] - [Brief explanation]
2. **Statistical Matchup:** [Strong/Moderate/Weak] - [Brief explanation]
3. **Personnel Impact:** [Strong/Moderate/Weak] - [Brief explanation]
4. **Situational Spot:** [Strong/Moderate/Weak] - [Brief explanation]
5. **Tactical Matchup & Possession Edges:** [Strong/Moderate/Weak] - [Brief explanation]

**Overall Confidence:** [Low/Medium/High]

**Risk Factors:** [What could go wrong with this bet]

---

### ELIMINATED OPTIONS (MANDATORY)

**YOU MUST EXPLAIN WHY YOU REJECTED ALL {n_eliminated} NON-SELECTED OPTIONS.**

Format each elimination like this:

**Option [X]: [Exact option text] at [odds]**
- **Why Eliminated:** [2-3 sentences citing which of the 5 factors were weak or contradicted this bet]

---

## CRITICAL REMINDERS

✅ The final recommendation must be EXACTLY one of the {len(plays)} options listed at the top
✅ The eliminated options section is MANDATORY—you must write {n_eliminated} elimination paragraphs
✅ Use recent data (last 15 games) and cite sources when possible
✅ Think like a sharp bettor finding market inefficiencies, not a fan picking favorites

❌ Do NOT recommend lines not listed above
❌ Do NOT claim "the consensus line is different than what you provided"
❌ Do NOT skip the eliminated options section"""
