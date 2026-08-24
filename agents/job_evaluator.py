"""
job_evaluator.py -- 1 job per API call, small prompt, 2s delay
Output structure compatible with digest_generator and email_notifier.

API failures produce decision "ERROR" with score None: they are excluded from
ranking/metrics downstream instead of polluting history with fake scores.
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json
from utils import (MIN_DESCRIPTION_CHARS, THRESHOLD_APPLY, THRESHOLD_REVIEW,
                   candidate_language_level, effective_decision,
                   is_spurious_blocker, is_truncated_description, levels_above,
                   max_evaluations_per_run)

# Cost guard: cap LLM calls per run (business rule: control daily spend).
MAX_EVALUATIONS_PER_RUN = max_evaluations_per_run()

# The model sees an excerpt of the description (see _excerpt). Window sized
# to Adzuna's storage (4000); the old 1500-char window cut off exactly the
# final "Requirements/Anforderungen" block where Swiss postings put their
# hard language requirements -- a C1-German clause past char 1500 invisibly
# flipped an auto-SKIP job to a 96/APPLY (2026-08-17 audit, scenario 4).
DESCRIPTION_WINDOW = 4000

# Below this much real posting text there is not enough signal for a
# confident evaluation -- evaluate_job caps such jobs at REVIEW so a bare
# title never earns automatic APPLY / CV-CL generation (the model otherwise
# fabricates confidence: a title-only "AI Engineer" posting scored 78 with
# "Technical fit: Strong" in the 2026-08-17 audit). Defined in src/utils.py
# and re-exported here: agents/description_enricher.py shares it.

PROFILE_IS_FALLBACK = False


def load_profile() -> dict:
    """Reads config/candidate_profile.json. Returns {} (and sets the loud
    fallback flag) when it is missing or unreadable."""
    global PROFILE_IS_FALLBACK
    try:
        with open("config/candidate_profile.json", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # Loud, because scoring a whole run against a generic profile
        # silently distorts every score (main() refuses to run in this
        # state; single-job callers like add_job.py only get this warning).
        PROFILE_IS_FALLBACK = True
        print(f"WARNING: config/candidate_profile.json unavailable ({type(e).__name__}) -- "
              "using the generic fallback profile; scores will NOT reflect the real candidate.",
              file=sys.stderr)
        return {}


def load_profile_summary(p: dict = None) -> str:
    """Builds the candidate summary from the profile, so the match criteria
    reflect the real CV (not a fixed summary)."""
    p = load_profile() if p is None else p
    if not p:
        # Minimal summary without PII.
        return ("Candidate: AI Software Engineer Intern, Zurich Area CH (Permit B), "
                "2 weeks notice. Looking for: AI / data platform engineering internship. "
                "Skills: Python, SQL, LLM APIs, GitHub Actions. Languages: PT, EN(C1), ES(B2), DE(A2).")

    skills = p.get("skills", {})
    tech = skills.get("technical_default", [])
    certs = skills.get("certifications", [])
    exp = p.get("experience", [])
    exp_summary = "; ".join(f"{e.get('title', '')} @ {e.get('company', '').split('--')[0].strip()}" for e in exp[:3])
    edu = p.get("education", [])
    edu_summary = edu[0].get("degree", "") if edu else ""
    motivation = p.get("summary", "")
    projects = p.get("projects", [])
    project_summary = "; ".join(pr.get("title", "") for pr in projects[:2])

    # What he is today vs. what he is looking for next are different things,
    # and only the first used to reach the model. A posting is scored on fit
    # to the TARGET: the CV says "seeking an internship to deepen my
    # expertise in agentic systems and data platform engineering", and
    # without that line the scorer just matched against his current job.
    target = p.get("target_role", "")
    target_line = f"Looking for (score fit to THIS, not to his current job): {target}. " if target else ""

    return (
        f"Candidate, currently: {p.get('role', 'AI Software Engineer Intern')}, "
        f"Zurich Area CH ({p.get('permit', 'Permit B')}), "
        f"notice {p.get('notice_period', '2 weeks')}. "
        f"{target_line}"
        f"Motivation (in his own words, weigh this for role-shape/excitement fit): {motivation} "
        f"Skills: {', '.join(tech)}. "
        f"Experience: {exp_summary}. "
        f"Projects: {project_summary}. "
        f"Education: {edu_summary}. "
        f"Certifications: {', '.join(certs)}. "
        f"Languages: {p.get('languages', 'PT native, EN C1, ES B2, DE A2')}."
    )


PROFILE_DATA = load_profile()
PROFILE = load_profile_summary(PROFILE_DATA)

# The candidate's own German level, read from the profile -- never hardcoded.
# Everything about the language rules is derived from it: what counts as an
# unreachable hard requirement, and what counts as the intermediate zone
# (levels above his but below fluent). An empty value means "unknown", and
# the derivation then assumes the weakest level, which is the safe direction.
GERMAN_LEVEL = candidate_language_level(PROFILE_DATA, "german")
INTERMEDIATE_LEVELS = levels_above(GERMAN_LEVEL)
_LEVEL_LABEL = GERMAN_LEVEL.upper() if GERMAN_LEVEL else "beginner"
_INTERMEDIATE_LABEL = "/".join(l.upper() for l in INTERMEDIATE_LEVELS) or "above his level"

SYSTEM_PROMPT = (
    'Evaluate job vs candidate. Return JSON: {"score":0-100,"technical_fit":"brief",'
    '"contextual_fit":"brief","salary_estimate":"range or Not disclosed","culture_fit":"brief",'
    '"language_requirement":"none|soft|intermediate|hard -- hard ONLY for a mandatory '
    'fluent/native/C1-C2 language beyond English (also list it in hard_blockers); '
    'intermediate for working/professional proficiency or a required level in the '
    f'{_INTERMEDIATE_LABEL} band in a language beyond English (above his {_LEVEL_LABEL}, '
    'below fluent); soft for plus/acceptable mentions, for a required level at or below '
    f'his own {_LEVEL_LABEL}, or when English is the working language; none if languages '
    'are never mentioned",'
    '"hard_blockers":["ONLY true hard eligibility blockers: an unmet HARD language requirement, '
    'wrong permit/location. EMPTY LIST when none -- never write None/no-blocker text here"],'
    '"concerns":["soft signals only: skill-depth notes, minor gaps, things merely worth '
    'knowing -- hard blockers belong in hard_blockers, not here"],'
    '"decision":"APPLY|REVIEW|SKIP",'
    '"detected_company":"company name from the job text, or empty if not clearly stated",'
    '"detected_title":"job title from the job text, or empty if not clearly stated",'
    '"detected_location":"city/canton the role is based in, inferred from the job text '
    '(office address, \'based in\', regulatory/site mentions), or empty if not clearly stated"}. '
    f"Rules: >={THRESHOLD_APPLY} APPLY, {THRESHOLD_REVIEW}-{THRESHOLD_APPLY - 1} REVIEW, "
    f"<{THRESHOLD_REVIEW} SKIP. Auto-SKIP: not Zurich/Zug (a fully-remote role based in "
    "Switzerland counts as Zurich-area -- do NOT skip it for location), not English, pure SWE. "
    "Also always auto-SKIP -- score below the SKIP threshold AND an entry in hard_blockers, "
    "no exception, regardless of how strong the rest of the match is -- when the role "
    "explicitly REQUIRES fluent/native German (or any language beyond English) for the "
    f"candidate to do the job: his German is {_LEVEL_LABEL} and improving, so a native/"
    "C1-fluent requirement is a hard eligibility blocker he cannot currently meet, not a "
    "'domain gap' to wave off. This is deliberate: an otherwise-perfect job he is "
    "disqualified from is worse than useless to surface, it's noise. Distinguish that HARD "
    "requirement ('fluent German required', 'German native speaker', 'verhandlungssicheres "
    "Deutsch', 'C1/C2 German') from a SOFT one ('German is a plus', 'German helpful but not "
    f"required', a level at or below his own {_LEVEL_LABEL}, or the role states English as "
    "the working language) -- a soft requirement is a minor signal like any other soft "
    "criterion, stays out of hard_blockers, and should NOT trigger this auto-SKIP. "
    "The INTERMEDIATE zone ('working/professional proficiency in German', or a required "
    f"level in the {_INTERMEDIATE_LABEL} band) is also NOT a blocker: it is above his "
    f"{_LEVEL_LABEL} but below fluent, and it is exactly what he is studying towards -- set "
    "language_requirement='intermediate', report it as a prominent concern, and score "
    "normally; the pipeline caps such jobs at REVIEW so he judges case by case. "
    "Weighting: candidate is a deliberate career changer, open to unfamiliar business "
    "domains (finance, healthcare, retail, etc.) -- do NOT penalize lack of domain "
    "experience if the technical/functional role itself matches. Technical fit and "
    "logistics (location, permit, availability) should drive the score; culture_fit and "
    "domain unfamiliarity are minor, non-decisive signals and should rarely by "
    "themselves keep a technically strong match out of APPLY. "
    "Perspective: score as the candidate would score it for himself -- how excited he'd "
    "be, how much he'd grow -- not as an HR recruiter filtering out risk. "
    "Calibration example (candidate-rated 100/APPLY): 'AI Platform Engineer Intern' at a "
    "small regulated investment firm, no finance background required of him and some "
    "tools in the stack (Microsoft no-code) he'd never used. Rated 100 because: hands-on "
    "ownership from day one ('junior builder, not support hand'), greenfield AI/"
    "automation building on a real platform, direct work with LLMs and agentic "
    "workflows in production. Role SHAPE -- ownership, building vs. maintaining, "
    "hands-on AI/automation work -- matters more than a perfect skills or domain "
    "checklist match. Weigh it accordingly."
)

ERROR_LOG = os.path.join("digests", "evaluation_errors.txt")  # .txt: *.log is in .gitignore and would not be committed
HISTORY_DIR = os.path.join("data", "history")


def log_error(msg):
    """Logs real API errors for diagnosis (committed by the workflow)."""
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


# Hard or significant language requirements in Swiss postings live in the
# final 'Requirements/Anforderungen' block -- past the excerpt window on long
# descriptions. This deterministic pre-check scans the FULL text so such a
# clause is never invisible to the scorer. English is deliberately absent
# (the candidate is C1); German/French/Italian are the local risks. Two
# tiers: HARD (fluent/native/C1-C2/verhandlungssicher) and INTERMEDIATE
# (working/professional proficiency, plus every CEFR level above the
# candidate's own and below C1 -- see utils.levels_above; a 'working
# proficiency in German' clause sat past the excerpt of a 92/APPLY posting
# on 2026-08-17 and reached the scorer invisibly).
_HARD_LEVEL_RE = r"fluent|native|mother[\s-]?tongue|verhandlungssicher\w*|\bc1\b|\bc2\b"
# The intermediate band is DERIVED from the candidate's own level, not fixed:
# for A2 it is B1 and B2, for B1 only B2. Hardcoding "B2" here meant that a
# "German B1 required" posting read as a soft mention while his German was
# actually A2 -- a real gap rendered as no gap.
_LANG_NAME_RE = r"german|deutsch|french|fran[cç]ais|franz[oö]sisch|italian\w*|italienisch"


def intermediate_level_pattern(levels=None) -> str:
    """Level alternation for the intermediate band. DERIVED from the
    candidate's own level, never fixed: for A2 it is B1 and B2, for B1 only
    B2. Hardcoding 'B2' here meant a 'German B1 required' posting read as a
    soft mention while his German was actually A2 -- a real gap rendered as
    no gap."""
    levels = INTERMEDIATE_LEVELS if levels is None else levels
    return "|".join([r"(?:professional|working)[\s-]proficienc\w*"] +
                    [rf"\b{level}\b" for level in levels])


def _lang_re(level: str):
    return re.compile(
        rf"(?:{level})[^.\n]{{0,80}}(?:{_LANG_NAME_RE})"
        rf"|(?:{_LANG_NAME_RE})[^.\n]{{0,80}}(?:{level})",
        re.IGNORECASE,
    )


_HARD_LANGUAGE_RE = _lang_re(_HARD_LEVEL_RE)
_INTERMEDIATE_LANGUAGE_RE = _lang_re(intermediate_level_pattern())


def detect_language_requirement_tier(full_description: str, levels=None):
    """'hard' | 'intermediate' | None -- deterministic, scans the FULL text.
    `levels` overrides the intermediate band (tests; callers scoring for a
    different candidate level)."""
    text = full_description or ""
    if _HARD_LANGUAGE_RE.search(text):
        return "hard"
    pattern = (_INTERMEDIATE_LANGUAGE_RE if levels is None
               else _lang_re(intermediate_level_pattern(levels)))
    if pattern.search(text):
        return "intermediate"
    return None


def detect_hard_language_requirement(full_description: str):
    """Scans the FULL description for what looks like a hard (or significant
    intermediate) language requirement beyond English and beyond the
    candidate's own German level, returning a
    short evidence snippet (or None). Soft mentions without a level marker
    ('German is a plus') deliberately do not match. The snippet is injected
    into the prompt as pipeline evidence -- the model still judges severity,
    but can no longer be blind to a requirement past the excerpt window."""
    text = full_description or ""
    m = _HARD_LANGUAGE_RE.search(text) or _INTERMEDIATE_LANGUAGE_RE.search(text)
    if not m:
        return None
    start = max(0, m.start() - 80)
    end = min(len(text), m.end() + 80)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _excerpt(text: str) -> str:
    """Head+tail window: Swiss postings put the Requirements/Anforderungen
    block at the END, so a single head window hides exactly the block that
    decides eligibility. For postings longer than the window, keep the
    first 2/3 and the last 1/3."""
    if len(text) <= DESCRIPTION_WINDOW:
        return text
    head = DESCRIPTION_WINDOW * 2 // 3
    tail = DESCRIPTION_WINDOW - head
    return text[:head] + "\n[... middle of the posting omitted ...]\n" + text[-tail:]


def _job_block(job):
    return {
        "company": job.get("company", "Unknown"),
        "title": job.get("title", "Unknown"),
        "location": job.get("location", "Unknown"),
        "url": job.get("url", ""),
        "portal": job.get("portal", job.get("source", "adzuna")),
        # Persisted (same excerpt the score was based on) so doc_generator.py
        # can write a CV/CL grounded in the actual posting -- it used to only
        # have title/company/location to work with, since this was never
        # saved, producing generic-sounding materials regardless of how good
        # the underlying description was.
        "description": _excerpt(job.get("description") or ""),
    }


def _sanitize_score(raw):
    """Coerces the model's score to an int in [0, 100]; None when absent or
    unparseable. The model sometimes returns "85" (a string -- used to crash
    the threshold comparison and turn a good evaluation into ERROR) or 120
    (passed straight through as APPLY)."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = raw
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0, min(100, int(round(value))))


def _no_text_record(job, chars):
    """A posting with no usable text gets NO SCORE, and costs no API call.

    The system already refuses to invent a score when the API fails ("a fake
    55/REVIEW once polluted 8 weeks of data"). Scoring a bare title is the
    same fabrication with a friendlier face: asked to judge six words, the
    model answered 88, 85 and 82 for three postings nobody had read. The
    low-confidence cap then held those at REVIEW, which is the right decision
    attached to a meaningless number -- and a dashboard showing "88 REVIEW"
    invites exactly the question it cannot answer.

    So below MIN_DESCRIPTION_CHARS there is no number at all. NOT_EVALUATED
    is an honest state: the posting exists, it was never readable, and it is
    excluded from ranking rather than competing on a score it never earned.
    """
    return {
        "score": None,
        "recommendation": "NOT_EVALUATED",
        "hard_blockers": [],
        "insufficient_info": True,
        "no_posting_text": True,
        "language_gap_intermediate": False,
        "key_match_points": [],
        "red_flags": [],
        "job": _job_block(job),
        "technical_fit": "Not evaluated: the posting text was never captured.",
        "contextual_fit": "Not evaluated",
        "salary_estimate": "Not disclosed",
        "culture_fit": "Not evaluated",
        "concerns": [f"No posting text available ({chars} characters). "
                     f"Paste the description into the Add Job workflow for a real score."],
        "decision": "NOT_EVALUATED",
        "materials_needed": [],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def _error_record(job, err_msg):
    """No invented score: ERROR entries are excluded from ranking and
    metrics downstream. A fake 55/REVIEW once polluted 8 weeks of data."""
    return {
        "score": None,
        "recommendation": "ERROR",
        "hard_blockers": [],
        "insufficient_info": False,
        "language_gap_intermediate": False,
        "key_match_points": [],
        "red_flags": [err_msg[:150]],
        "job": _job_block(job),
        "technical_fit": "Not evaluated",
        "contextual_fit": "Not evaluated",
        "salary_estimate": "Not disclosed",
        "culture_fit": "Not evaluated",
        "concerns": [err_msg[:150]],
        "decision": "ERROR",
        "materials_needed": [],
    }


# Half-width of the re-sampling band around each threshold. 8 is roughly one
# standard deviation of the observed score noise, so a job this close to a
# boundary is genuinely a coin flip on a single sample.
DEFAULT_BORDERLINE_BAND = 8
DEFAULT_BORDERLINE_SAMPLES = 2


def _borderline_band() -> int:
    """Read dynamically, like max_evaluations_per_run, so tests and CI can
    override it via env without re-importing the module."""
    try:
        return int(os.environ.get("BORDERLINE_BAND") or DEFAULT_BORDERLINE_BAND)
    except ValueError:
        return DEFAULT_BORDERLINE_BAND


def _borderline_samples() -> int:
    """Extra opinions to buy for a borderline job. 0 disables the whole
    mechanism -- used by the test suite, and available for a run on a tight
    Kimi budget."""
    try:
        return int(os.environ.get("BORDERLINE_SAMPLES") or DEFAULT_BORDERLINE_SAMPLES)
    except ValueError:
        return DEFAULT_BORDERLINE_SAMPLES


def _is_borderline(score) -> bool:
    """Close enough to a decision boundary that noise could flip the outcome."""
    if _borderline_samples() <= 0:
        return False
    band = _borderline_band()
    return any(abs(score - t) <= band
               for t in (THRESHOLD_APPLY, THRESHOLD_REVIEW))


def _median_of_three(prompt, first_ev, first_score, title, company):
    """Re-scores a borderline job and returns (record, median score).

    The record kept is the sample whose score IS the median, so the reasoning
    the candidate reads always matches the number he is shown -- pairing a
    median score with the first sample's reasoning would be its own quiet lie.
    A failed re-sample is skipped, never fatal: one good score beats none.
    """
    samples = [(first_score, first_ev)]
    for _ in range(_borderline_samples()):
        try:
            again = call_kimi_json(prompt, system=PROFILE + "\n" + SYSTEM_PROMPT,
                                   max_tokens=1000)
        except Exception as e:
            print(f"  [borderline] re-sample failed ({type(e).__name__}) -- "
                  f"keeping what we have")
            break
        again_score = _sanitize_score(again.get("score"))
        if again_score is not None:
            samples.append((again_score, again))
        time.sleep(1)

    if len(samples) == 1:
        return first_ev, first_score
    samples.sort(key=lambda pair: pair[0])
    median_score, median_ev = samples[len(samples) // 2]
    spread = samples[-1][0] - samples[0][0]
    print(f"  [borderline] {title[:34]} @ {company[:20]}: "
          f"{[s for s, _ in samples]} -> {median_score} (spread {spread})")
    return median_ev, median_score


def evaluate_job(job):
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    location = job.get("location", "Unknown")
    desc_full = job.get("description", "") or ""
    desc = _excerpt(desc_full)
    # Too short to judge, OR long enough to look complete while actually being
    # a cut-off teaser. Adzuna returns exactly 500 characters for every single
    # posting, and the requirements never survive that cut -- see
    # utils.is_truncated_description for the measurement.
    insufficient_info = (len(desc_full.strip()) < MIN_DESCRIPTION_CHARS
                         or is_truncated_description(desc_full))

    # No usable text: refuse to produce a number, and do not spend the call.
    # A truncated 500-character teaser still carries real signal and IS
    # scored, capped at REVIEW; an empty card carries none.
    if len(desc_full.strip()) < MIN_DESCRIPTION_CHARS:
        print(f"NOT EVALUATED -> no posting text ({len(desc_full.strip())} chars); "
              f"no score invented, no API call spent")
        return _no_text_record(job, len(desc_full.strip()))

    url = job.get("url", "")

    # Today's date grounds any timeline reasoning (notice period vs start
    # date, posting age) -- without it the model works off its training
    # cutoff and once invented a "start date 16+ months away" blocker for a
    # start 2 months out.
    prompt = (f"Today's date: {date.today().isoformat()}\n"
              f"Job: {title} at {company}\nLocation: {location}\nDesc: {desc}\nURL: {url}")
    if is_truncated_description(desc_full):
        # Without this the model reads a truncated posting as a complete one.
        # What survives the cut is the pitch ("join our AI innovation lab,
        # bring agentic solutions to production"), which reads as a perfect
        # match; what is lost is "at least 5 years", "B.Sc. required" and
        # every other disqualifier. That is not a hypothetical: it scored the
        # Avaloq posting 82/APPLY blind and 58/SKIP with the full text.
        prompt += ("\n[Pipeline note: the description above is TRUNCATED -- it stops "
                   "mid-sentence and the requirements/qualifications section is missing "
                   "entirely. Judge only what is visible, assume nothing about seniority, "
                   "years of experience or degree requirements, and keep the score "
                   "conservative. Say in `concerns` that the requirements were not visible.]")

    lang_evidence = detect_hard_language_requirement(desc_full)
    if lang_evidence:
        if detect_language_requirement_tier(desc_full) == "hard":
            prompt += (f"\n[Pipeline note: the full posting contains this text, possibly beyond "
                       f"the excerpt above: \"{lang_evidence}\" -- if it is a HARD language "
                       f"requirement beyond English (or beyond {_LEVEL_LABEL}-level German), "
                       f"the auto-SKIP rule applies and it belongs in hard_blockers.]")
        else:
            prompt += (f"\n[Pipeline note: the full posting contains this text, possibly beyond "
                       f"the excerpt above: \"{lang_evidence}\" -- this looks like an "
                       f"INTERMEDIATE language requirement (working proficiency / "
                       f"{_INTERMEDIATE_LABEL}: above his {_LEVEL_LABEL}, below fluent). NOT a "
                       f"hard blocker: set language_requirement='intermediate' and report it "
                       f"as a prominent concern.]")
    prompt += "\nEvaluate."

    try:
        ev = call_kimi_json(prompt, system=PROFILE + "\n" + SYSTEM_PROMPT, max_tokens=1000)

        score = _sanitize_score(ev.get("score"))
        # Borderline jobs get a second opinion. Measured 2026-08-23 on one
        # posting, five samples each: the score wanders by up to 20 points
        # between identical calls (55, 55, 55, 35, 45 on the full text). That
        # is not fixable by turning the temperature down -- kimi-k2.6 answers
        # "invalid temperature: only 1 is allowed for this model" -- and it
        # usually does not matter, because all ten samples still agreed on
        # SKIP. It matters only when the score sits on a threshold, where the
        # same job becomes APPLY or REVIEW depending on which sample arrived.
        # So re-sample exactly there, take the median of three, and leave the
        # other ~90% of jobs at one call each.
        # Partial evidence cannot certify an APPLY-band score. A truncated
        # teaser is the marketing intro with the requirements cut off, and
        # the Avaloq posting proved what that is worth: 82 on the teaser, 58
        # on the full text. Capping only the DECISION left an unexplained
        # "85, REVIEW" on the dashboard, which is the question nobody can
        # answer in front of a manager.
        #
        # So the score itself is capped just below the APPLY threshold. The
        # invariant is then true by construction: a score in the APPLY band
        # means the posting was actually read.
        if (score is not None and score >= THRESHOLD_APPLY
                and (insufficient_info or ev.get("language_requirement") == "intermediate")):
            print(f"  capped {score} -> {THRESHOLD_APPLY - 1}: partial evidence "
                  f"cannot support an APPLY-band score")
            score = THRESHOLD_APPLY - 1

        if score is not None and _is_borderline(score):
            ev, score = _median_of_three(prompt, ev, score, title, company)
        if score is None:
            # A missing/invalid score is an evaluation failure, NOT a silent
            # 50/SKIP -- the old default fabricated exactly the kind of score
            # the no-fake-scores rule exists to prevent.
            msg = f"Model returned no usable score: {ev.get('score')!r}"
            print(f"EVALUATION ERROR -> {msg}")
            log_error(f"{title} @ {company}: {msg}")
            return _error_record(job, f"Evaluation error: {msg}")

        raw_concerns = ev.get("concerns") or []  # 'concerns': null must not propagate None
        if not isinstance(raw_concerns, list):
            raw_concerns = [raw_concerns]
        concerns = [str(c) for c in raw_concerns]
        soft_concerns = [c for c in concerns if not c.startswith("Blocker:")]

        model_blockers = ev.get("hard_blockers")
        if model_blockers is None:
            # Backward compat: a model still on the old contract reports
            # blockers as 'Blocker: '-prefixed concerns.
            model_blockers = [c[len("Blocker:"):].strip() for c in concerns
                              if c.startswith("Blocker:")]
        if not isinstance(model_blockers, list):
            model_blockers = [model_blockers]
        # Spurious 'Blocker: None -- ...' entries are filtered: the model
        # uses the prefix to say there is NO blocker, and taking the prefix
        # literally would SKIP the best jobs (2026-08-17 smoke, scenario 1).
        real_blockers = [b for b in (str(x).strip() for x in model_blockers)
                         if b and not is_spurious_blocker(b)]

        # Intermediate language zone (working proficiency, or a level above
        # his own but below fluent) -> never a blocker, but APPLY is capped
        # at REVIEW so the call stays his (2026-08-17 product decision).
        lang_req = str(ev.get("language_requirement", "") or "").strip().lower()
        if lang_req in ("none", "soft", "intermediate", "hard"):
            language_gap_intermediate = lang_req == "intermediate"
            # Defence in depth: 'hard' in language_requirement must always
            # come with a matching hard_blocker entry.
            if lang_req == "hard" and not real_blockers:
                real_blockers = [lang_evidence or "Hard language requirement flagged by model"]
        else:
            # Field absent/invalid (older model contract): deterministic fallback.
            language_gap_intermediate = detect_language_requirement_tier(desc_full) == "intermediate"
            if language_gap_intermediate:
                soft_concerns.append(
                    f"Intermediate language requirement detected (working proficiency/"
                    f"{_INTERMEDIATE_LABEL}): above his {_LEVEL_LABEL}, below fluent")

        # Concerns always surface, regardless of tier (a real bug used to
        # drop them for APPLY-tier jobs -- exactly where they matter most).
        red_flags = [f"Blocker: {b}" for b in real_blockers] + soft_concerns
        if insufficient_info:
            if is_truncated_description(desc_full):
                red_flags.append(
                    "Low confidence: the posting text is CUT OFF (the source returns only "
                    "the opening pitch). The requirements section was never seen, so any "
                    "disqualifier in it is invisible -- open the original before trusting "
                    "this score")
            else:
                red_flags.append("Low confidence: posting text under "
                                 f"{MIN_DESCRIPTION_CHARS} chars -- score is title-based")
        if not red_flags and score < THRESHOLD_REVIEW:
            red_flags = ["Score below threshold"]

        key_match_points = []
        if score >= THRESHOLD_APPLY:
            key_match_points = [ev.get("technical_fit", ""), ev.get("contextual_fit", "")]
            key_match_points = [p for p in key_match_points if p]
        elif score >= THRESHOLD_REVIEW:
            key_match_points = [ev.get("technical_fit", "")]
            key_match_points = [p for p in key_match_points if p]

        # Backfill company/title/location from what the model detected in
        # the description when the caller didn't supply them: this is the
        # same reasoning the model already does for technical_fit/
        # contextual_fit (e.g. it correctly wrote "Zurich area (Wallisellen)"
        # in contextual_fit while the structured `location` field stayed
        # "Unknown" -- manually-added jobs in particular never had any
        # location-extraction logic at all).
        resolved_job = dict(job)
        for field, detected_key in (("company", "detected_company"), ("title", "detected_title"), ("location", "detected_location")):
            if resolved_job.get(field, "Unknown") in ("Unknown", "", None):
                detected = ev.get(detected_key)
                # Not just != "unknown": the model answers with speculation
                # when it cannot tell, and "Unknown (likely Palantir or
                # similar given 'Forward deployed')" was stored as a company
                # name. A guess in a field that reaches a CV is worse than an
                # empty one.
                detected_clean = (detected or "").strip()
                speculative = (detected_clean.lower().startswith("unknown")
                               or "likely" in detected_clean.lower())
                if detected_clean and not speculative:
                    resolved_job[field] = detected.strip()

        record = {
            "score": score,
            "hard_blockers": real_blockers,
            "insufficient_info": insufficient_info,
            "language_gap_intermediate": language_gap_intermediate,
            "key_match_points": key_match_points,
            "red_flags": red_flags,
            "job": _job_block(resolved_job),
            "technical_fit": ev.get("technical_fit", ""),
            "contextual_fit": ev.get("contextual_fit", ""),
            "salary_estimate": ev.get("salary_estimate", "Not disclosed"),
            "culture_fit": ev.get("culture_fit", ""),
            "concerns": concerns,
        }

        # Decision is ALWAYS derived locally, never trusted verbatim from the
        # model: thresholds on the score + the hard-blocker lock (business
        # rule, no exception) + the low-confidence cap. See utils.py.
        decision = effective_decision(record)
        model_decision = ev.get("decision")
        if model_decision and model_decision != decision:
            print(f"  Note: model said decision={model_decision} but local rules map to "
                  f"{decision} (score={score}, blockers={len(real_blockers)}, "
                  f"insufficient={insufficient_info}); using {decision}.")

        record["recommendation"] = decision
        record["decision"] = decision
        record["materials_needed"] = ["cv"] if decision == "APPLY" else []
        return record
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        print(f"API ERROR -> decision ERROR (no fake score) | {err_msg[:200]}")
        log_error(f"{title} @ {company}: {err_msg}")
        return _error_record(job, f"API error: {err_msg}")


def append_history(evaluations):
    """Appends this run's evaluations to data/history/evaluations_YYYYMMDD.json
    so the full evaluation history survives (job_evaluations_latest.json is
    overwritten every run and digests only keep the top 5)."""
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        path = os.path.join(HISTORY_DIR, f"evaluations_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json")
        existing = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = []
        run_ts = datetime.now(timezone.utc).isoformat()
        for ev in evaluations:
            entry = dict(ev)
            entry["evaluated_at"] = run_ts
            existing.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"History: {len(evaluations)} evaluations appended to {path}")
    except OSError as e:
        print(f"WARNING: could not write history: {e}")


def main():
    if PROFILE_IS_FALLBACK:
        # Scoring the whole run against a generic profile would silently
        # distort every score -- fail loud instead (usually means the
        # CANDIDATE_PROFILE_B64 secret was not restored in CI).
        print("FATAL: config/candidate_profile.json missing/invalid. "
              "Refusing to evaluate with the generic fallback profile.")
        sys.exit(1)

    os.makedirs("digests", exist_ok=True)
    def _no_jobs():
        """Nothing to score: say so, and make the rest of the pipeline agree.

        job_evaluations_latest.json is what the digest and the document
        generator read. Leaving the PREVIOUS run's evaluations in a file
        called "latest" makes a quiet day indistinguishable from a busy one:
        on 2026-08-24 a run with zero new jobs re-sent the previous run's top
        five stamped with the new timestamp, and the quiet-day heartbeat --
        which exists precisely for that case -- never fired, because
        total_evaluated was 5 rather than 0. It would also have re-generated
        and re-announced documents for yesterday's APPLY jobs.

        Writing an empty list is the honest state, and it is what makes the
        heartbeat reachable.
        """
        print("No jobs to evaluate.")
        with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as fh:
            json.dump([], fh)

    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _no_jobs(); return
    if not jobs:
        _no_jobs(); return

    if len(jobs) > MAX_EVALUATIONS_PER_RUN:
        print(f"Cost guard: {len(jobs)} jobs found, capping at {MAX_EVALUATIONS_PER_RUN} "
              f"(set MAX_EVALUATIONS_PER_RUN to change).")
        jobs = jobs[:MAX_EVALUATIONS_PER_RUN]

    print(f"Loaded {len(jobs)} jobs. 1 by 1 with 2s delay...\n")
    evaluations = []
    for i, job in enumerate(jobs, 1):
        title = job.get("title", "Unknown")[:50]
        print(f"[{i}/{len(jobs)}] {title}...", end=" ", flush=True)
        ev = evaluate_job(job)
        evaluations.append(ev)
        print(f"score={ev.get('score','?')} ({ev.get('decision','?')})")
        if i < len(jobs):
            time.sleep(2)

    scored = [e for e in evaluations if e.get("score") is not None]
    errors = [e for e in evaluations if e.get("decision") == "ERROR"]
    apply_ = [e for e in scored if e["score"] >= THRESHOLD_APPLY]
    review = [e for e in scored if THRESHOLD_REVIEW <= e["score"] < THRESHOLD_APPLY]
    skip = [e for e in scored if e["score"] < THRESHOLD_REVIEW]

    blind = [e for e in evaluations if e.get("insufficient_info")]

    print(f"\n{'='*50}")
    print(f"DONE: {len(evaluations)} jobs | APPLY: {len(apply_)} | REVIEW: {len(review)} | "
          f"SKIP: {len(skip)} | ERROR: {len(errors)}")
    if blind:
        # Visible on purpose: a title-only job can never reach APPLY (the
        # low-confidence cap), so a high blind ratio means the run mostly
        # burned LLM calls on postings it could not really judge. If this
        # stays high, agents/description_enricher.py is not finding matches.
        print(f"Scored on the title alone (no description): {len(blind)}/{len(evaluations)} "
              f"-- these are capped at REVIEW by design.")
    print(f"{'='*50}")
    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

    append_history(evaluations)

    if errors:
        print(f"WARNING: {len(errors)}/{len(evaluations)} evaluations failed "
              f"(see digests/evaluation_errors.txt). These jobs were NOT scored.")

    # Fail loud: if EVERY evaluation failed, the LLM provider is down or the
    # account has no credits -- a green "0 APPLY" run hides outages.
    if errors and len(errors) == len(evaluations):
        print(f"FATAL: all {len(errors)} evaluations failed. "
              f"Check KIMI_API_KEY / KIMI_BASE_URL and account balance.")
        sys.exit(1)


if __name__ == "__main__":
    main()
