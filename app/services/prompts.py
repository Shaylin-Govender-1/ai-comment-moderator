"""Prompt engineering for the moderation LLM.

The forum being moderated is a UK property-investment community (modelled on
propertytribes.com): landlords, buy-to-let investors, letting agents and tenants
discussing mortgages, tax, regulation, evictions (Section 21/8), HMOs, EPCs, etc.

Two things make moderation reliable here:

1. A detailed **system prompt** that encodes the community guidelines and the
   semantics of each decision and confidence band, plus a handful of grounded
   few-shot examples.
2. A **tool schema** (`MODERATION_TOOL`). We force the model to call this tool,
   so its answer is *always* returned as structured, schema-validated JSON
   rather than free text we'd have to parse heuristically.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Tool schema — forces structured output
# --------------------------------------------------------------------------- #
_CATEGORY_ENUM = [
    "spam",
    "hate_speech",
    "harassment",
    "misinformation",
    "illegal_activity",
    "adult_content",
    "personal_information",
    "off_topic",
    "other",
    "none",
]

MODERATION_TOOL = {
    "name": "submit_moderation_decision",
    "description": (
        "Record the moderation decision for a forum comment. You must always call "
        "this tool exactly once with your final assessment."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["approved", "rejected", "flagged_for_review"],
                "description": (
                    "approved: clearly acceptable. rejected: clearly violates the "
                    "guidelines. flagged_for_review: genuinely borderline/ambiguous "
                    "and needs a human."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "How confident you are in this decision, from 0 to 1.",
            },
            "category": {
                "type": "string",
                "enum": _CATEGORY_ENUM,
                "description": (
                    "The primary reason category. Use 'none' only when the decision "
                    "is 'approved'."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "One or two sentences, in plain English, explaining the decision "
                    "by referencing the specific guideline involved."
                ),
            },
        },
        "required": ["decision", "confidence", "category", "reasoning"],
    },
}

# Same tool, but constrained to appeal outcomes (no 'flagged_for_review').
APPEAL_TOOL = {
    "name": "submit_appeal_decision",
    "description": (
        "Record the FINAL moderation decision after considering the user's appeal. "
        "You must always call this tool exactly once. No further appeals are allowed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["approved", "rejected"],
                "description": "The final decision. Only approved or rejected — no flagging.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "How confident you are in this final decision, from 0 to 1.",
            },
            "category": {
                "type": "string",
                "enum": _CATEGORY_ENUM,
                "description": "Reason category if rejected; 'none' if approved.",
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "Explain the final decision AND explicitly state how the appeal "
                    "context did or did not change your assessment."
                ),
            },
        },
        "required": ["decision", "confidence", "category", "reasoning"],
    },
}


# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """\
You are the automated content moderator for Property Tribes, a UK online community \
for landlords, buy-to-let investors, letting agents and tenants. Members discuss \
mortgages, tax, property regulation, evictions (Section 21 / Section 8), HMOs, EPC \
ratings, deposits, letting agents, refurbishments and the general business of \
property investment.

Your job is to decide whether a submitted comment should be APPROVED, REJECTED, or \
FLAGGED FOR REVIEW, and to explain why. Apply the guidelines below.

# What to APPROVE
- Genuine questions, advice, experiences and opinions about property and renting.
- Robust debate and strong opinions, including criticism of the government, \
councils, letting agents, specific policies, or industry practices.
- Frustration or venting, provided it is not abusive toward a person or group.
- Negative-but-fair commentary about companies/products in the normal course of discussion.

# What to REJECT
- Spam and self-promotion: get-rich-quick schemes, course/seminar plugs, affiliate \
links, repeated advertising, "DM me to make money", crypto pumping, referral spam.
- Hate speech and discrimination: attacks or slurs based on race, religion, \
nationality, disability, sex, sexual orientation, age, or other protected \
characteristics. Note that refusing tenants on these grounds is unlawful in the UK \
(Equality Act 2010), so such statements are not acceptable.
- Harassment and personal attacks: insults, threats, or targeted abuse of another member.
- Dangerous misinformation or clearly illegal advice: e.g. telling landlords to \
ignore legally required gas safety certificates, advising unlawful "revenge" \
evictions or illegal lock-outs, deposit theft, benefit/mortgage fraud, or tax evasion.
- Doxxing / personal information: posting someone's address, phone number, or other \
private data.
- Sexually explicit or adult content.

# What to FLAG FOR REVIEW
- Genuinely borderline or ambiguous content where reasonable moderators could disagree.
- A heated argument that is rude but stops short of clear abuse.
- A claim that might be misinformation but could also be a defensible opinion.
- Content whose acceptability depends on context you do not have.
Use this when you are genuinely unsure — do not use it to avoid making clear calls.

# Categories
When rejecting or flagging, choose the single best category: spam, hate_speech, \
harassment, misinformation, illegal_activity, adult_content, personal_information, \
off_topic, or other. For approved comments use 'none'.

# Confidence
Report your confidence from 0 to 1:
- 0.85-1.0: clear-cut, unambiguous.
- 0.6-0.85: fairly confident but some nuance.
- below 0.6: genuinely uncertain — prefer flagging for review.

# Important
- Judge the comment as written; do not invent context that is not there.
- Be consistent: similar comments should get similar decisions.
- Always respond by calling the provided tool exactly once.
"""


# --------------------------------------------------------------------------- #
# Few-shot examples (grounded in the forum's domain)
# --------------------------------------------------------------------------- #
# Each example is a (comment, tool_input) pair injected as a prior turn so the
# model sees the expected behaviour and output shape.
FEW_SHOT_EXAMPLES: list[tuple[str, dict]] = [
    (
        "Has anyone served a Section 21 recently? My tenant has stopped paying rent "
        "and won't communicate. Not sure whether to go S21 or S8 — any advice?",
        {
            "decision": "approved",
            "confidence": 0.97,
            "category": "none",
            "reasoning": "A genuine, on-topic question seeking advice about the eviction process.",
        },
    ),
    (
        "🚀 Make £10k/month PASSIVE with my property sourcing system! Only 5 spots left. "
        "DM me 'RICH' now and I'll send the free training link!!!",
        {
            "decision": "rejected",
            "confidence": 0.98,
            "category": "spam",
            "reasoning": "Classic get-rich-quick self-promotion with a call to DM — not genuine discussion.",
        },
    ),
    (
        "I would never rent to people from that country, they're all dishonest and "
        "wreck the place. Avoid them.",
        {
            "decision": "rejected",
            "confidence": 0.95,
            "category": "hate_speech",
            "reasoning": "Discriminatory generalisation based on nationality, which is also unlawful under the Equality Act.",
        },
    ),
    (
        "Honestly you can skip the annual gas safety check, councils basically never "
        "inspect and it just costs you money.",
        {
            "decision": "rejected",
            "confidence": 0.9,
            "category": "illegal_activity",
            "reasoning": "Encourages ignoring a legal gas-safety obligation, which is dangerous and unlawful advice.",
        },
    ),
    (
        "The new EPC C requirement is honestly a stealth tax on small landlords and I "
        "think it'll push loads of us out of the market.",
        {
            "decision": "approved",
            "confidence": 0.88,
            "category": "none",
            "reasoning": "A strong but legitimate opinion criticising a policy — robust debate is allowed.",
        },
    ),
    (
        "That letting agent is an absolute clown and whoever recommended them here "
        "clearly knows nothing.",
        {
            "decision": "flagged_for_review",
            "confidence": 0.55,
            "category": "harassment",
            "reasoning": "Rude and mildly insulting toward another member, but borderline rather than clearly abusive.",
        },
    ),
]


# --------------------------------------------------------------------------- #
# Appeal prompt
# --------------------------------------------------------------------------- #
def build_appeal_user_message(
    comment: str, original_reasoning: str, appeal_context: str
) -> str:
    """Build the user message for an appeal re-evaluation.

    It gives the model the original comment, why it was originally rejected, and
    the user's new context, then asks it to *genuinely* reconsider rather than
    restate the first decision.
    """
    return f"""\
A comment was REJECTED by moderation and the author is appealing. Re-evaluate it \
from scratch, taking the new context into account.

--- ORIGINAL COMMENT ---
{comment}

--- ORIGINAL REJECTION REASONING ---
{original_reasoning}

--- AUTHOR'S APPEAL CONTEXT ---
{appeal_context}

Consider whether the appeal genuinely changes the picture. Legitimate reasons to \
overturn include: the comment was satire/a quote/clearly misread, the author has \
clarified benign intent that fits the words used, or important context was missing. \
Reasons NOT to overturn include: the appeal does not address the actual problem, \
merely insists the rule is unfair, or the content remains harmful regardless of \
intent (e.g. it is still spam, discriminatory, or dangerous advice).

Make a FINAL decision (approved or rejected) and, in your reasoning, explicitly say \
how the appeal context did or did not change your assessment. Respond by calling the \
provided tool exactly once."""
