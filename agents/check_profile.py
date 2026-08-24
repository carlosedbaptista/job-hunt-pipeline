#!/usr/bin/env python3
"""
check_profile.py -- Refuses to run the pipeline on a profile that contradicts
itself or the CV.

Why this exists
---------------
config/candidate_profile.json is gitignored. It lives in exactly two places,
one laptop and one GitHub secret, and neither shows up in a diff. When the
candidate's job title changed on 2026-08-24 the profile was updated and the
local CANDIDATE_PROFILE_B64.txt was not, so whether CI scored him under the
right role depended on which of the two files a human happened to pipe into
`gh secret set`. Nothing would have complained either way.

The cost of that silence is not cosmetic. The role is injected into the
scoring prompt as "Candidate, currently: X", so a stale one skews every
score in the run; and it is printed at the top of every generated CV, which
goes to employers.

The same class of bug has already happened once with languages: the prompt
said his German was B1 while the CV said A2, so a "German B1 required"
posting read as a soft mention when it was a real gap.

What is checked
---------------
The CV is treated as the source of truth, because it is the document a human
wrote and an employer reads.

  1. the profile parses and carries the fields the pipeline depends on;
  2. profile.role appears verbatim in the CV reference text;
  3. profile.experience[0].title -- the current job -- matches profile.role;
  4. the CEFR level in language_levels agrees with the prose in
     profile.languages.

Exit code 1 on any failure, by the same reasoning job_evaluator.main() uses
when the profile is missing: scoring a whole run against wrong facts is worse
than not running.

The CV reference is optional (CV_MODEL_B64 may be unset), and its absence is
a warning rather than a failure -- check 2 is simply skipped.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from utils import candidate_language_level  # noqa: E402

PROFILE_PATH = os.environ.get("PROFILE_PATH", "config/candidate_profile.json")
CV_MODEL_PATH = os.environ.get("CV_MODEL_PATH", "config/cv_model.txt")

REQUIRED_FIELDS = ("name", "role", "experience", "education", "skills", "languages")
_CEFR = re.compile(r"\b([ABC][12])\b")


def _normalise(text):
    """Whitespace-insensitive, case-insensitive comparison form.

    A CV line-wraps: "AI Software Engineer\\nIntern" must still match the
    profile's "AI Software Engineer Intern".
    """
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def check(profile, cv_text):
    """Returns a list of human-readable problems. Empty means consistent."""
    problems = []

    missing = [f for f in REQUIRED_FIELDS if not profile.get(f)]
    if missing:
        problems.append(f"profile is missing required field(s): {', '.join(missing)}")
        return problems  # nothing below can be trusted

    role = str(profile.get("role", "")).strip()

    # 2. The CV is what an employer reads; the profile must agree with it.
    if cv_text:
        if _normalise(role) not in _normalise(cv_text):
            problems.append(
                f'profile role "{role}" does not appear in the CV reference text. '
                f"One of the two is stale -- the CV is the document a human wrote, "
                f"so it is usually the profile (or its base64 secret) that is behind.")
    else:
        print("  note: no CV reference text available; skipping the role cross-check")

    # 3. The profile against itself: the current job IS the current role.
    experience = profile.get("experience") or []
    if experience:
        current = str((experience[0] or {}).get("title", "")).strip()
        if current and _normalise(current) != _normalise(role):
            problems.append(
                f'profile role "{role}" does not match the most recent experience '
                f'entry "{current}". The CV header and its first job would disagree.')

    # 4. The CEFR level the rules are derived from, against the prose that
    #    goes into documents. These drifted apart once already.
    german = candidate_language_level(profile, "german")
    languages = str(profile.get("languages", ""))
    if german:
        match = re.search(r"german[^|,;]*", languages, re.I)
        stated = _CEFR.search(match.group(0)) if match else None
        if stated and stated.group(1).upper() != german.upper():
            problems.append(
                f'language_levels says German is {german.upper()} but the languages '
                f'line says {stated.group(1).upper()}. The scoring rules derive from '
                f"the first, the CV prints the second.")

    return problems


def main():
    try:
        with open(PROFILE_PATH, encoding="utf-8") as f:
            profile = json.load(f)
    except FileNotFoundError:
        print(f"FATAL: {PROFILE_PATH} not found. Check the CANDIDATE_PROFILE_B64 secret.")
        return 1
    except json.JSONDecodeError as e:
        print(f"FATAL: {PROFILE_PATH} is not valid JSON ({e}). "
              f"The secret is probably truncated or wrapped.")
        return 1

    cv_text = ""
    try:
        with open(CV_MODEL_PATH, encoding="utf-8") as f:
            cv_text = f.read()
    except (OSError, UnicodeDecodeError):
        pass

    problems = check(profile, cv_text)
    if problems:
        print("FATAL: the candidate profile contradicts itself or the CV.\n")
        for problem in problems:
            print(f"  - {problem}")
        print("\nRefusing to run: the role is injected into every scoring prompt and "
              "printed on every generated CV, so running on stale facts skews the "
              "whole day and sends the wrong title to employers.")
        print("Fix config/candidate_profile.json, then regenerate the secret:")
        print("  base64 -w0 config/candidate_profile.json | gh secret set CANDIDATE_PROFILE_B64")
        return 1

    print(f"Profile consistent: {profile.get('role')} "
          f"(German {candidate_language_level(profile, 'german').upper() or 'unset'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
