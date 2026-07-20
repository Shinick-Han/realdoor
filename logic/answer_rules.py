"""Answering rule questions with citations, and measuring that against ``qa_gold``.

Every answer this module returns carries at least one ``rule_id`` from the 11-rule pack
corpus. There is no path that returns an uncited assertion: an answer we cannot attach a
rule to is an abstention instead.

The household answers (threshold, annualized income, comparison, readiness) are NOT
looked up. They are computed end-to-end by ``logic.income``, ``logic.threshold`` and
``logic.readiness`` from the documents, so ``score_against_gold()`` measures the
reasoning layer rather than a table of memorized strings. Question routing is by pattern
over the question text and the household id is parsed out of it, so perturbed names and
values -- which the organizer says hidden tests may use -- still route correctly.

Full disclosure about what this measurement does and does not prove. The 36 records split
into two populations, and ``score_against_gold()`` reports them separately rather than
letting one flatter the other:

* **Derived (24 records).** Threshold, annualized income, comparison and readiness for
  each of the six households. These run the full pipeline over the documents. Getting
  them right requires the income conventions, the threshold table and all four readiness
  checks to be correct. This is the real test of this layer, and
  ``test_answer_rules.py`` includes falsification tests that perturb the documents and
  require these answers to move.
* **Templated (12 records).** The six decision-boundary answers and the six corpus-fact
  answers are short sentences written against the rule corpus, and their phrasing was
  authored with the pack's phrasing in view. They test routing and citation, not
  derivation. A perfect result on these 12 is worth much less than a perfect result on
  the other 24, and reporting them merged would overstate the system.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from logic.constants import LIMITS_EFFECTIVE_DATE, RULE_IDS
from logic.household import (
    Household,
    load_gold_households,
    load_pack_checklists,
    load_rule_corpus,
    repo_root,
)
from logic.income import annualize_household
from logic.readiness import assess_readiness
from logic.threshold import (
    MAX_FROZEN_SIZE,
    MIN_FROZEN_SIZE,
    lookup_60_percent,
    out_of_table_statement,
    threshold_statement,
)

HOUSEHOLD_PATTERN = re.compile(r"\b(HH-\d+)\b", re.IGNORECASE)

#: Number words a person actually uses for a household size. Bounded on purpose: past
#: twelve nobody writes it out, and every token here has to be one a size can be.
NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

_SIZE_TOKEN = r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")"

#: A household size stated **in the question itself** ("for a household of 3").
#:
#: Every alternative below requires a household word touching the number -- "household",
#: "family", "person", "people", "occupants", or the literal word "size". A bare integer
#: never matches. That is what keeps it off the ``qa_gold`` questions, which carry
#: numbers in ``HH-001``, ``60%``, ``60-day`` and ``FY 2026`` and no size phrase at all;
#: ``test_answer_rules.py`` asserts non-matching over the whole gold set rather than
#: trusting this comment.
QUESTION_SIZE_PATTERN = re.compile(
    rf"\bhouseholds?\s+(?:size\s+)?of\s+{_SIZE_TOKEN}\b"
    rf"|\bhouseholds?\s+size\s+(?:is\s+|of\s+)?{_SIZE_TOKEN}\b"
    rf"|\bfamily\s+of\s+{_SIZE_TOKEN}\b"
    rf"|\bsize\s+{_SIZE_TOKEN}\b"
    rf"|\b{_SIZE_TOKEN}[-\s]person\b"
    rf"|\b{_SIZE_TOKEN}\s+(?:people|persons|occupants)\b"
    # Korean size phrases. The Korean layer translates every answer this module gives,
    # but the size extraction only spoke English, so "1인 가구의 소득 한도" nominated the
    # right intent and then abstained for want of the size printed in the question
    # itself. The alternation is deliberately minimal and digit-anchored: a digit, then
    # 인/명 (counter), then a household word — so 승인/확인/개인, which contain 인 with no
    # leading digit, can never match, and a bare digit never matches (the same rule the
    # English half enforces with its size words).
    rf"|(\d{{1,2}})\s*인\s*(?:가구|세대|가족)"
    rf"|(?:가구|세대|가족)\s*원?\s*(\d{{1,2}})\s*명",
    re.IGNORECASE,
)


def question_household_size(question: str) -> int | None:
    """The household size the question names, or ``None`` if it names none.

    This is the number that used to be thrown away. The threshold is a function of
    household size, not a property of a particular household, so a size stated in the
    question is answerable on its own -- with or without a session household.
    """
    match = QUESTION_SIZE_PATTERN.search(question or "")
    if match is None:
        return None
    token = next(g for g in match.groups() if g)
    return int(token) if token.isdigit() else NUMBER_WORDS[token.lower()]

#: Answer kinds computed end-to-end from the documents. Everything else is a sentence
#: templated from the rule corpus. The distinction is reported, never blurred.
DERIVED_KINDS = frozenset(
    {"frozen_threshold", "annualized_income", "threshold_comparison", "readiness_status"}
)


# =====================================================================================
# question form vs. answer kind -- the agreement gate
# =====================================================================================
#
# WHY THIS EXISTS
# ---------------
# "when does the new 2026 income limit start counting" was answered with "$92,580 for
# household size 3." A question about a DATE was handed a MONEY figure, with a citation
# attached, sounding exactly as confident as a right answer. The alias table had matched
# the substring "income limit" and dragged the question to `frozen_threshold` before the
# intent classifier -- which gets this question right -- was ever consulted.
#
# The tempting repair is to add "when ... income limit" to the effective-date alias. That
# repair is why the defect existed in the first place: the alias table is a list of
# phrasings, and a list of phrasings is always one phrasing short. The next renter writes
# "as of what day is the new income cap", and it breaks again in exactly the same way.
#
# So the gate below is not about phrasings at all. It is about GRAMMAR on one side and
# ANSWER TYPE on the other:
#
#   * every intent declares what KIND OF THING its answer is -- a date, a dollar figure,
#     a comparison, a status, a policy sentence, a code, a citation;
#   * the question's own interrogative form says what kind of thing it is ASKING for;
#   * when those two are determinate and they contradict, the route is refused.
#
# The question-side patterns contain NO domain vocabulary. Not "income", not "limit", not
# "household", not "document" -- only interrogatives and auxiliary verbs. That is the
# testable difference between this and a wider alias table, and `test_answer_rules.py`
# asserts it directly rather than asking the reader to take it on faith. A gate written in
# grammar generalises to phrasings nobody has written yet; a gate written in vocabulary
# only ever covers the phrasings someone already thought of.
#
# The gate is a VETO and only ever a veto. It can turn a wrong answer into an abstention.
# It can never turn an abstention into an answer, and it can never change what an answer
# says. It is also consulted only on the non-canonical paths -- the tenant-vocabulary
# aliases and the intent classifier. A question `route()` matches on its own is never
# shown to this code, which is why the 36 pack questions cannot move.

ANSWER_DATE = "date"
ANSWER_MONEY = "money"
ANSWER_RELATION = "relation"
ANSWER_STATUS = "status"
ANSWER_POLICY = "policy"
ANSWER_CODE = "code"
ANSWER_CITATION = "citation"

ANSWER_SHAPES = frozenset({
    ANSWER_DATE, ANSWER_MONEY, ANSWER_RELATION, ANSWER_STATUS,
    ANSWER_POLICY, ANSWER_CODE, ANSWER_CITATION,
})

SCOPE_SELF = "self"
SCOPE_GENERAL = "general"

#: A temporal interrogative, in four grammatical forms:
#:   * subject-auxiliary inversion after "when"  -- "when does the limit start"
#:   * a bare leading "when"                     -- "when do they change"
#:   * "when" as the object of a temporal preposition -- "since when", "as of when"
#:   * a wh-phrase whose head noun is a calendar unit -- "what date", "which year"
#:   * a degree question over recency            -- "how recent", "how old"
#: No domain word appears here, and none is needed: the form is what carries the meaning.
_TEMPORAL_QUESTION = re.compile(
    r"\bwhen\s+(?:do|does|did|will|is|are|was|were|can|could|should|would"
    r"|has|have|had|may|might|must)\b"
    r"|^\W*(?:(?:so|ok|okay|um|uh|and|but|sorry|hey|well)[,\s]+)*when\b"
    r"|\b(?:since|as\s+of|from|until|till|up\s+to|by)\s+when\b"
    r"|\b(?:what|which)\s+(?:date|day|year|month)\b"
    r"|\bhow\s+(?:recent|current|old)\b"
    # The Korean temporal interrogative. One token is the whole enumeration: 언제
    # ("when") asks for a date whether it carries a particle (언제부터, 언제까지), a
    # copula (언제예요, 언제인가요) or nothing. Two guards keep it honest, in the same
    # spirit as the English \b anchors: no preceding Hangul, so a word that merely
    # contains these syllables cannot match, and not 언제나 ("always"), which contains
    # 언제 and asks for no date at all. Still zero domain vocabulary -- 언제 is grammar,
    # like "when".
    r"|(?<![가-힣])언제(?!나)",
    re.IGNORECASE,
)

#: A quantity interrogative. "how much", or a wh-phrase whose head noun is a bare
#: quantity word. Adjacency is required, so "what part of that number" -- which asks
#: which portion of a code to use -- does not read as a request for an amount.
_AMOUNT_QUESTION = re.compile(
    r"\bhow\s+much\b"
    r"|\bhow\s+many\s+dollars\b"
    r"|\b(?:what|which)\s+(?:amount|number|figure|total)\b"
    r"|\bwhat'?s\s+the\s+(?:amount|number|figure|total)\b"
    # The Korean quantity interrogative. 얼마 ("how much") requests an amount whatever
    # ending follows it -- 얼마예요, 얼마인가요, 얼마죠, 얼마정도여야 하나요 -- so no
    # ending is enumerated. Excluded on purpose: 얼마나, where the request is carried by
    # the word AFTER it (얼마나 자주 asks about frequency, 얼마나 오래 about duration);
    # it stays a plain wh-word in _WH_WORD below, which is "no opinion", never a veto.
    r"|(?<![가-힣])얼마(?!나)",
    re.IGNORECASE,
)

#: Any wh-word. Its ABSENCE is what makes a leading auxiliary a yes/no question rather
#: than a wh-question that happens to start with one. The Korean list serves the same
#: single purpose: a Korean wh-question ends in the same suffixes a polar question does
#: (서류가 뭐가 필요하나요 ends like 승인되나요), so without this list the polar branch
#: would misread every Korean wh-question as yes/no and veto answers it should not.
#: Presence here is only ever "no opinion" -- it can stop a veto, never cause one.
_WH_WORD = re.compile(
    r"\b(?:what|when|where|which|who|whom|whose|why|how)\b"
    r"|(?<![가-힣])(?:무엇|뭐|뭘|언제|얼마|어떤|어느|어디|누가|누구|왜|어떻게|몇)",
    re.IGNORECASE)

#: A polar (yes/no) question: subject-auxiliary inversion at the head of the sentence,
#: optionally behind a discourse filler.
_YES_NO_QUESTION = re.compile(
    r"^\W*(?:(?:so|ok|okay|um|uh|and|but|sorry|hey|well|please)[,\s]+)*"
    r"(?:is|are|am|was|were|do|does|did|can|could|will|would|should|shall"
    r"|has|have|had|may|might|must)\b"
    # The Korean polar question. English marks yes/no at the HEAD of the sentence
    # (subject-auxiliary inversion); Korean marks it at the TAIL, so this alternative is
    # anchored at the end instead: the interrogative endings ~나요 (있나요, 되나요,
    # 하나요), ~까요 (될까요, 있을까요), ~ㄴ가요 (인가요, 한가요), the formal ~니까
    # (입니까, 됩니까) and the indirect ~는지(요). asked_shapes() consults this branch
    # only when no wh-word was found, exactly as it does for English, so 얼마인가요 -- a
    # wh-question wearing a polar ending -- never reaches it.
    r"|(?:나요|까요|니까|는지(?:요)?|가요)\s*[?!.…\s]*$",
    re.IGNORECASE,
)

#: The asker as grammatical subject of a stative or do-supported predicate: "am i ...",
#: "are we ...", "do i ...". Deliberately NOT triggered by a bare "my" or "me" -- "which
#: of these codes is ok to show on my address" is a question about the codes, not about
#: the asker -- and not by "can i", which introduces questions about what is possible
#: ("can i trust that listing") far more often than questions about the asker's standing.
_SELF_SUBJECT = re.compile(
    r"\b(?:am|are)\s+(?:i|we)\b|\bdo\s+(?:i|we)\b"
    # The Korean first person as grammatical SUBJECT, particle-marked: 제가/내가
    # (subject), 저는/나는 (topic), 저도/나도 ("I too"), and the plural 저희/우리 with
    # the same particles. Particle-marked forms only, for the same reason the English
    # half deliberately skips "my" and "me": bare 제/내/우리 before a noun is a
    # possessive (제 서류 = "my papers"), and a question about the asker's papers is a
    # question about the papers, not about the asker's standing. The lookbehind keeps
    # words that merely end in these syllables out -- 문제가 ("the problem" + subject
    # particle) contains 제가 and says nothing about the speaker.
    r"|(?<![가-힣])(?:제가|내가|저는|나는|저도|나도|저희(?:가|는|도)|우리(?:가|는|도))",
    re.IGNORECASE)


def _first_at(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return match.start() if match else None


def asked_shapes(question: str) -> frozenset[str] | None:
    """The answer types this question's grammar admits, or ``None`` if it does not say.

    ``None`` is the common case and it means "no opinion" -- the gate stays out of the
    way unless the question's form is genuinely determinate. Returning a set rather than
    a single shape keeps the honest ambiguity: "how much over am i" is asking for either
    a figure or a comparison, and the gate should not have to pick.

    Only the MATRIX interrogative counts -- the one the sentence is actually built on --
    and that is why position is compared rather than just presence. "who made up the rule
    about how recent my papers have to be" contains a temporal phrase, but it is buried in
    a relative clause describing the rule; the question being asked is "who". Reading the
    embedded clause as the question turns a request for an authority into a request for a
    date, and vetoes a route that was right. The earliest interrogative wins, with ties
    going to the more specific reading (the generic wh-word also matches at the head of
    "how recent" and "what day").
    """
    text = question or ""
    wh = _first_at(_WH_WORD, text)
    temporal = _first_at(_TEMPORAL_QUESTION, text)
    amount = _first_at(_AMOUNT_QUESTION, text)

    if temporal is not None and (wh is None or temporal <= wh):
        return frozenset({ANSWER_DATE})
    if amount is not None and (wh is None or amount <= wh):
        return frozenset({ANSWER_MONEY, ANSWER_RELATION})
    if wh is None and _YES_NO_QUESTION.search(text):
        # A polar question wants a sentence that can carry a yes or a no. A bare dollar
        # figure and a bare calendar date are the two answer types that cannot: handing
        # "$92,580" to someone who asked "are they using the new numbers" answers
        # nothing, however true the figure is.
        return ANSWER_SHAPES - {ANSWER_MONEY, ANSWER_DATE}
    return None


def question_scope(question: str) -> str:
    """Is this question predicated on the asker, or on the program?

    A second, orthogonal axis. "so am i approved" is about the asker's own standing;
    "which location codes are ok to display" is about the corpus, even though it ends
    with "my address". Intents that state a fact about the program can never be the
    answer to the first kind of question, and that is true regardless of vocabulary.
    """
    return SCOPE_SELF if _SELF_SUBJECT.search(question or "") else SCOPE_GENERAL


@dataclass(frozen=True)
class AnswerProfile:
    """What an intent's answer IS -- independent of any phrasing that reaches it.

    ``shape``        the type of thing the answer is.
    ``answers_self`` whether this intent can answer a question predicated on the asker.
                     A threshold, an income, a comparison and a readiness status are all
                     computed from the asker's own file, so they can. An effective date,
                     a statute and a geocoding convention are facts about the program;
                     they are true whoever asks, and they answer nothing about anyone.
    """

    shape: str
    answers_self: bool

    def __post_init__(self) -> None:
        if self.shape not in ANSWER_SHAPES:
            raise ValueError(f"{self.shape!r} is not a declared answer shape")


#: Profiles for the intents this module routes. `api/route_llm.py` declares the same for
#: the situation intents and reuses this table verbatim for these, so the two cannot drift.
CANONICAL_PROFILES: dict[str, AnswerProfile] = {
    "frozen_threshold": AnswerProfile(ANSWER_MONEY, True),
    "annualized_income": AnswerProfile(ANSWER_MONEY, True),
    "threshold_comparison": AnswerProfile(ANSWER_RELATION, True),
    "readiness_status": AnswerProfile(ANSWER_STATUS, True),
    # The answer to "may this service decide about me" is a policy sentence, and it is
    # squarely about the asker -- refusing to decide is the answer to a question about
    # the asker's standing, so this one is `answers_self`.
    "decision_boundary": AnswerProfile(ANSWER_POLICY, True),
    "limits_effective_date": AnswerProfile(ANSWER_DATE, False),
    "vacancy_claim": AnswerProfile(ANSWER_POLICY, False),
    "geocode_precision": AnswerProfile(ANSWER_CODE, False),
    "embedded_instructions": AnswerProfile(ANSWER_POLICY, False),
    "currency_rule_status": AnswerProfile(ANSWER_POLICY, False),
    "statutory_anchor": AnswerProfile(ANSWER_CITATION, False),
}


def question_admits(question: str, profile: AnswerProfile | None) -> bool:
    """Could an answer with this profile be an answer to this question?

    ``False`` only when the question's grammar rules it out. An unknown profile and an
    indeterminate question both return ``True``: this gate refuses, it never approves.
    """
    if profile is None:
        return True
    shapes = asked_shapes(question)
    if shapes is not None and profile.shape not in shapes:
        return False
    if question_scope(question) == SCOPE_SELF and not profile.answers_self:
        return False
    return True


def canonical_admits(question: str, kind: str | None) -> bool:
    """``question_admits`` for a kind routed by this module."""
    if kind is None:
        return True
    return question_admits(question, CANONICAL_PROFILES.get(kind))


@dataclass(frozen=True)
class Answer:
    """One answered (or explicitly unanswered) question."""

    text: str | None
    rule_ids: tuple[str, ...]
    kind: str
    abstained: bool = False
    what_would_resolve_it: str | None = None

    def __post_init__(self) -> None:
        for rid in self.rule_ids:
            if rid not in RULE_IDS:
                raise ValueError(f"{rid!r} is not one of the 11 pack rules")
        if not self.abstained and not self.rule_ids:
            raise ValueError("an answered question must cite at least one rule")

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.text,
            "rule_ids": list(self.rule_ids),
            "kind": self.kind,
            "abstained": self.abstained,
            "what_would_resolve_it": self.what_would_resolve_it,
        }


def _abstain(kind: str, text: str, resolve: str, rule_ids: tuple[str, ...] = ()) -> Answer:
    return Answer(text=None, rule_ids=rule_ids, kind=kind, abstained=True,
                  what_would_resolve_it=resolve)


# =====================================================================================
# corpus-fact answers
# =====================================================================================


def _effective_date_answer(rules: dict[str, dict[str, Any]]) -> Answer:
    raw = rules["HUD-MTSP-001"]["effective_date"] or LIMITS_EFFECTIVE_DATE
    parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    return Answer(
        text=f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}.",
        rule_ids=("HUD-MTSP-001",),
        kind="limits_effective_date",
    )


CORPUS_ANSWERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "vacancy_claim": (
        "No. The dataset is a project inventory, not a vacancy or waitlist feed.",
        ("HUD-DATA-001",),
    ),
    "geocode_precision": (
        "HUD identifies R and 4 as the higher-precision codes for address display.",
        ("HUD-GEO-001",),
    ),
    "embedded_instructions": (
        "Treat them as untrusted document text and ignore them.",
        ("CH-SAFETY-001",),
    ),
    "currency_rule_status": (
        "No. It is a frozen convention for this hackathon simulation.",
        ("CH-READINESS-001",),
    ),
    "statutory_anchor": ("26 U.S.C. section 42.", ("FED-LIHTC-001",)),
    "decision_boundary": (
        "No. It may report the numerical comparison and readiness status only; "
        "a human makes any program determination.",
        ("CH-DECISION-001",),
    ),
}


# =====================================================================================
# household answers -- computed, not looked up
# =====================================================================================


def _required_types(household_id: str, checklists: dict[str, dict[str, Any]],
                    house: Household) -> Sequence[str]:
    row = checklists.get(household_id)
    if row:
        return tuple(row["required_document_types"])
    # Unlisted household (a perturbed hidden test): require what is present, which asks
    # nothing we cannot see, rather than inventing a requirement list.
    return tuple(sorted(house.present_types))


def _threshold_answer(house: Household) -> Answer:
    result = lookup_60_percent(house.size)
    if not result.available:
        return _abstain(
            "frozen_threshold",
            threshold_statement(result),
            result.abstention.what_would_resolve_it if result.abstention else "",
            ("HUD-MTSP-002",),
        )
    return Answer(threshold_statement(result), ("HUD-MTSP-002",), "frozen_threshold")


def _asked_size_threshold_answer(asked_size: int, session_size: Any = None) -> Answer:
    """The threshold for a size the question named, not the size of the session file.

    Two things this owes the reader. First, if the session's own household is a different
    size, the answer says so outright -- silently answering a different question than the
    one asked is the defect this path exists to close, and quietly answering the right one
    while the reader believes it is about their file would be the same defect mirrored.
    Second, if the size is outside 1-8 it names the range we hold instead of returning
    nothing, and it still does not invent the row.

    Nothing here says anything about any person. A threshold is a number to compare
    against; the comparison and the determination are somewhere else and stay there.
    """
    result = lookup_60_percent(asked_size)
    if not result.available:
        return Answer(
            text=out_of_table_statement(asked_size),
            rule_ids=("HUD-MTSP-002",),
            kind="frozen_threshold",
            abstained=True,
            what_would_resolve_it=(
                result.abstention.what_would_resolve_it if result.abstention else
                f"ask about a household size from {MIN_FROZEN_SIZE} to {MAX_FROZEN_SIZE}"
            ),
        )

    text = threshold_statement(result)
    try:
        differs = session_size is not None and int(session_size) != asked_size
    except (TypeError, ValueError):
        differs = False
    if differs:
        text = (
            f"{text} Note that this is the figure for the household size of "
            f"{asked_size} in the question, not for this session's file, which is a "
            f"household of {int(session_size)}."
        )
    return Answer(text, ("HUD-MTSP-002",), "frozen_threshold")


def _income_answer(house: Household) -> Answer:
    result = annualize_household(house)
    if result.total is None:
        reason = result.abstentions[0] if result.abstentions else None
        return _abstain(
            "annualized_income",
            "",
            reason.what_would_resolve_it if reason else "the renter confirms the income inputs",
            ("CH-INCOME-001",),
        )
    return Answer(
        f"${result.total:,.2f} under the frozen annualization convention.",
        ("CH-INCOME-001",),
        "annualized_income",
    )


def _comparison_answer(house: Household, required: Sequence[str]) -> Answer:
    assessment = assess_readiness(house, required)
    result = assessment.comparison
    if result.comparison == "no_frozen_threshold":
        reason = result.abstentions[0] if result.abstentions else None
        return _abstain(
            "threshold_comparison",
            "",
            reason.what_would_resolve_it if reason else "supply the missing input",
            ("HUD-MTSP-002", "CH-INCOME-001"),
        )
    return Answer(result.comparison, ("HUD-MTSP-002", "CH-INCOME-001"), "threshold_comparison")


def _readiness_answer(house: Household, required: Sequence[str]) -> Answer:
    assessment = assess_readiness(house, required)
    return Answer(assessment.readiness_status, ("CH-READINESS-001",), "readiness_status")


# =====================================================================================
# routing
# =====================================================================================


@dataclass(frozen=True)
class Route:
    kind: str
    pattern: re.Pattern[str]
    needs_household: bool


ROUTES: tuple[Route, ...] = (
    Route("frozen_threshold", re.compile(r"frozen\s+60\s*%?\s*(ami\s+)?threshold|60%\s+limit", re.I), True),
    Route("annualized_income", re.compile(r"annualized\s+income", re.I), True),
    Route("threshold_comparison", re.compile(r"compare[sd]?\s+with|how\s+does.*compare", re.I), True),
    Route("readiness_status", re.compile(r"readiness\s+status", re.I), True),
    Route("decision_boundary",
          re.compile(r"may the system call|call .* (in)?eligible|make an eligibility", re.I), False),
    Route("limits_effective_date", re.compile(r"take\s+effect|effective\s+date", re.I), False),
    Route("vacancy_claim", re.compile(r"vacan|waitlist|prove a unit", re.I), False),
    Route("geocode_precision", re.compile(r"geocode", re.I), False),
    Route("embedded_instructions",
          re.compile(r"instructions\s+(embedded|inside)|embedded\s+instruction", re.I), False),
    Route("currency_rule_status", re.compile(r"60[- ]day", re.I), False),
    Route("statutory_anchor", re.compile(r"statutory\s+anchor|federal\s+statute", re.I), False),
)


def route(question: str) -> str | None:
    for item in ROUTES:
        if item.pattern.search(question):
            return item.kind
    return None


def answer(question: str, household_id: str | None = None,
           households: dict[str, Household] | None = None,
           checklists: dict[str, dict[str, Any]] | None = None,
           rules: dict[str, dict[str, Any]] | None = None) -> Answer:
    """Answer one rule question, or abstain. Never returns an uncited claim."""
    households = households if households is not None else load_gold_households()
    checklists = checklists if checklists is not None else load_pack_checklists()
    rules = rules if rules is not None else load_rule_corpus()

    kind = route(question)
    if kind is None:
        return _abstain(
            "unrouted", "",
            "a housing professional answers this, or the question is rephrased to name the "
            "rule it is about",
        )

    if kind == "limits_effective_date":
        return _effective_date_answer(rules)
    if kind in CORPUS_ANSWERS:
        text, rule_ids = CORPUS_ANSWERS[kind]
        return Answer(text, rule_ids, kind)

    found = household_id or (HOUSEHOLD_PATTERN.search(question).group(1).upper()
                             if HOUSEHOLD_PATTERN.search(question) else None)

    # A size stated in the question is answerable on its own -- the frozen limit is a
    # function of household size, not an attribute of a particular household file. This
    # runs BEFORE the "no household" abstention on purpose: refusing to read a row that
    # is sitting in the table, because no session was named, was the second half of the
    # defect this branch closes.
    if kind == "frozen_threshold":
        asked_size = question_household_size(question)
        if asked_size is not None:
            session = households.get(found) if found else None
            return _asked_size_threshold_answer(
                asked_size, session.size if session is not None else None)

    if found is None or found not in households:
        return _abstain(
            kind, "",
            f"supply the documents for {found or 'the household in question'}",
        )

    house = households[found]
    required = _required_types(found, checklists, house)

    if kind == "frozen_threshold":
        return _threshold_answer(house)
    if kind == "annualized_income":
        return _income_answer(house)
    if kind == "threshold_comparison":
        return _comparison_answer(house, required)
    if kind == "readiness_status":
        return _readiness_answer(house, required)

    return _abstain(kind, "", "a housing professional answers this")


# =====================================================================================
# equivalence and grading
# =====================================================================================

_STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "for", "in", "is", "it", "its",
    "makes", "may", "not", "of", "only", "or", "should", "that", "the", "them", "this",
    "to", "under", "use", "what", "when", "which", "with",
}
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(".")


def _numbers(text: str) -> set[float]:
    return {float(m.replace(",", "")) for m in _NUMBER.findall(text)}


def _polarity(text: str) -> str | None:
    head = _normalize(text).split(" ")[0].strip(".,;:")
    return head if head in ("no", "yes") else None


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z_]+", _normalize(text))
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def equivalent(predicted: str, gold: str) -> tuple[bool, str]:
    """Is a predicted answer the same answer as gold? Returns (verdict, tier).

    Tier "exact" is normalized string identity (case, whitespace, trailing period).
    Tier "semantic" requires ALL of: the same set of numbers, the same yes/no polarity,
    and every content word of the gold answer present in the prediction. It is
    deliberately asymmetric -- a prediction may add words, never drop them -- so a vaguer
    answer cannot pass as a matching one. Both tiers are reported separately so the
    headline number cannot be inflated by a loose comparison.
    """
    if predicted is None:
        return False, "none"
    if _normalize(predicted) == _normalize(gold):
        return True, "exact"
    if _numbers(predicted) != _numbers(gold):
        return False, "numbers"
    if _polarity(predicted) != _polarity(gold):
        return False, "polarity"
    if not _content_words(gold).issubset(_content_words(predicted)):
        return False, "content"
    return True, "semantic"


@dataclass
class GradedAnswer:
    qa_id: str
    question: str
    gold: str
    gold_rule_ids: tuple[str, ...]
    predicted: str | None
    predicted_rule_ids: tuple[str, ...]
    verdict: str  # "correct" | "abstained" | "wrong"
    tier: str
    citation_ok: bool
    kind: str = ""

    @property
    def derived(self) -> bool:
        return self.kind in DERIVED_KINDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "qa_id": self.qa_id,
            "question": self.question,
            "gold": self.gold,
            "predicted": self.predicted,
            "gold_rule_ids": list(self.gold_rule_ids),
            "predicted_rule_ids": list(self.predicted_rule_ids),
            "verdict": self.verdict,
            "match_tier": self.tier,
            "citation_ok": self.citation_ok,
            "kind": self.kind,
            "derived": self.derived,
        }


def default_qa_gold_path() -> Path:
    return repo_root() / "pack" / "evaluation" / "qa_gold.jsonl"


def load_qa_gold(path: str | Path | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path else default_qa_gold_path()
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def score_against_gold(qa_path: str | Path | None = None,
                       households: dict[str, Household] | None = None) -> dict[str, Any]:
    """Grade this module against every ``qa_gold`` record.

    Three buckets, never merged: ``correct``, ``abstained``, ``wrong``. An abstention is
    not a correct answer and is not counted as one -- it is counted as a refusal to
    guess, which is a different and less bad thing than being wrong.
    """
    records = load_qa_gold(qa_path)
    households = households if households is not None else load_gold_households()
    checklists = load_pack_checklists()
    rules = load_rule_corpus()

    graded: list[GradedAnswer] = []
    for record in records:
        result = answer(record["question"], record.get("household_id"),
                        households, checklists, rules)
        gold_ids = tuple(record.get("rule_ids") or ())
        if result.abstained:
            verdict, tier = "abstained", "none"
        else:
            ok, tier = equivalent(result.text, record["answer"])
            verdict = "correct" if ok else "wrong"
        graded.append(GradedAnswer(
            qa_id=record["qa_id"],
            question=record["question"],
            gold=record["answer"],
            gold_rule_ids=gold_ids,
            predicted=result.text,
            predicted_rule_ids=result.rule_ids,
            verdict=verdict,
            tier=tier,
            citation_ok=bool(gold_ids) and set(gold_ids).issubset(set(result.rule_ids)),
            kind=result.kind,
        ))

    correct = [g for g in graded if g.verdict == "correct"]
    derived = [g for g in graded if g.derived]
    templated = [g for g in graded if not g.derived]
    return {
        "total": len(graded),
        "correct": len(correct),
        "abstained": sum(1 for g in graded if g.verdict == "abstained"),
        "wrong": sum(1 for g in graded if g.verdict == "wrong"),
        "exact_matches": sum(1 for g in correct if g.tier == "exact"),
        "semantic_matches": sum(1 for g in correct if g.tier == "semantic"),
        "citations_matching_gold": sum(1 for g in graded if g.citation_ok),
        # The honest split: computed from documents vs. templated from the rule corpus.
        "derived_total": len(derived),
        "derived_correct": sum(1 for g in derived if g.verdict == "correct"),
        "derived_wrong": sum(1 for g in derived if g.verdict == "wrong"),
        "derived_abstained": sum(1 for g in derived if g.verdict == "abstained"),
        "templated_total": len(templated),
        "templated_correct": sum(1 for g in templated if g.verdict == "correct"),
        "wrong_details": [g.to_dict() for g in graded if g.verdict == "wrong"],
        "abstained_details": [g.to_dict() for g in graded if g.verdict == "abstained"],
        "graded": [g.to_dict() for g in graded],
    }


def summary_line(result: dict[str, Any]) -> str:
    return (
        f"qa_gold: {result['correct']} correct / {result['abstained']} abstained / "
        f"{result['wrong']} wrong out of {result['total']}\n"
        f"  derived from documents: {result['derived_correct']}/{result['derived_total']} "
        f"({result['derived_wrong']} wrong, {result['derived_abstained']} abstained)\n"
        f"  templated from rule corpus: "
        f"{result['templated_correct']}/{result['templated_total']}\n"
        f"  match tier: exact {result['exact_matches']}, semantic {result['semantic_matches']}\n"
        f"  citations matching gold: {result['citations_matching_gold']}/{result['total']}"
    )


__all__ = [
    "ANSWER_SHAPES",
    "Answer",
    "AnswerProfile",
    "CANONICAL_PROFILES",
    "GradedAnswer",
    "QUESTION_SIZE_PATTERN",
    "SCOPE_GENERAL",
    "SCOPE_SELF",
    "answer",
    "asked_shapes",
    "canonical_admits",
    "equivalent",
    "question_admits",
    "question_scope",
    "load_qa_gold",
    "question_household_size",
    "route",
    "score_against_gold",
    "summary_line",
]


if __name__ == "__main__":  # pragma: no cover
    outcome = score_against_gold()
    print(summary_line(outcome))
    for row in outcome["wrong_details"]:
        print(f"  WRONG {row['qa_id']}: gold={row['gold']!r} predicted={row['predicted']!r}")
    for row in outcome["abstained_details"]:
        print(f"  ABSTAINED {row['qa_id']}: {row['question']}")
