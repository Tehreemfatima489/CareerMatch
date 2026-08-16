import os

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import re
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz.distance import DamerauLevenshtein
import json
from pathlib import Path
from django.conf import settings
from constants import DEGREE_LEVEL_TIER_MAP
from django.core.cache import cache
from jobs.models import SkillAliasOverride, SkillDistinctOverride, TitleMatchOverride, Job
from django.db.models.functions import Lower, Trim
from users.models import Skill
from django.utils import timezone
from django.db import transaction
from celery import group


  

_ESCO_ALIASES_PATH = getattr(settings, "BASE_DIR", Path(__file__).resolve().parent.parent) / "jobs" / "esco_skill_aliases.json"


os.environ["TOKENIZERS_PARALLELISM"] = "false"


model = SentenceTransformer("TechWolf/JobBERT-v3")


try:
    with open(_ESCO_ALIASES_PATH, encoding="utf-8") as f:
        _ESCO_SKILL_ALIASES = json.load(f)
except FileNotFoundError:
    _ESCO_SKILL_ALIASES = {}
  

_EDU_FIELD_TAXONOMY_PATH = getattr(settings, "BASE_DIR", Path(__file__).resolve().parent.parent) / "jobs" / "education_field_taxonomy.json"

try:
    with open(_EDU_FIELD_TAXONOMY_PATH, encoding="utf-8") as f:
        _EDU_FIELD_TAXONOMY = json.load(f)
except FileNotFoundError:
    _EDU_FIELD_TAXONOMY = {}
    # Missing file just means every job falls back to pure embedding
    # scoring — matching still works, it just loses the tag-based path.


_PK_SKILL_TAXONOMY_PATH = getattr(settings, "BASE_DIR", Path(__file__).resolve().parent.parent) / "jobs" / "pk_skill_taxonomy.json"

try:
    with open(_PK_SKILL_TAXONOMY_PATH, encoding="utf-8") as f:
        _PK_SKILL_TAXONOMY_RAW = json.load(f).get("skills", {})
except FileNotFoundError:
    _PK_SKILL_TAXONOMY_RAW = {}
    # Missing file just means this lookup tier is skipped — matching
    # falls through to ESCO aliases / embeddings as before.




_OVERRIDE_CACHE_TTL = 300  # 5 min; tune as needed

def _ordered_pair(a: str, b: str):     #return a alphabetic ordered tuple of 2 strings
    if a <= b:
        return (a, b)
    else:
        return (b, a)

def _get_skill_alias_overrides() -> set[tuple[str, str]]:
    hit = cache.get("skill_alias_overrides")
    if hit is not None:
        return hit
    
    raw_pairs = set(SkillAliasOverride.objects.values_list("skill_a_norm", "skill_b_norm"))
    pairs = {_ordered_pair(a, b) for a, b in raw_pairs}
    cache.set("skill_alias_overrides", pairs, _OVERRIDE_CACHE_TTL)
    return pairs

def _get_skill_distinct_overrides() -> set[tuple[str, str]]:
    hit = cache.get("skill_distinct_overrides")
    if hit is not None:
        return hit
    
    raw_pairs = set(SkillDistinctOverride.objects.values_list("skill_a_norm", "skill_b_norm"))
    pairs = {_ordered_pair(a, b) for a, b in raw_pairs}
    cache.set("skill_distinct_overrides", pairs, _OVERRIDE_CACHE_TTL)
    return pairs

def _get_title_overrides(kind: str) -> dict[tuple[str, str], bool]:
    cache_key = f"title_overrides_{kind}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit
    
    rows = TitleMatchOverride.objects.filter(kind=kind).values_list("text_a_norm", "text_b_norm", "judged_same")
    result = {}
    for a, b, same in rows:
        result[_ordered_pair(a, b)] = same
    cache.set(cache_key, result, _OVERRIDE_CACHE_TTL)
    return result
# -------------------------------------------------------
# Thresholds
# -------------------------------------------------------
SKILL_PARTIAL_MATCH_THRESHOLD = 0.55   #  near-misses get scaled partial credit
SKILL_MATCH_THRESHOLD  = 0.72
MIN_REQUIRED_SKILL_COVERAGE = 0.5  # must match at least half of required skills to count at all
LEVEL_MISMATCH_PENALTY_PER_TIER = 0.13
LEVEL_MISMATCH_FLOOR = 0.15
LEVEL_OVERQUALIFIED_FLOOR = 0.5
LEVEL_OVERQUALIFIED_DAMPENER = 0.5

REQUIRED_SKILL_WEIGHT  = 1.0
OPTIONAL_SKILL_WEIGHT  = 0.4


def _normalise_education_text(text: str) -> str:
    text = text.lower().strip()
    return " ".join(text.split())


# -------------------------------------------------------
# 1. PROFILE VECTOR PRE-COMPUTATION
# -------------------------------------------------------
def precompute_profile_vectors(profile):
    user_skills = list(profile.skills.values_list("name", flat=True))
    experiences = list(profile.experiences.prefetch_related("skills_used").all())
    educations = list(profile.educations.all())

    vectors = {
        "user_skills": user_skills,
        "user_skills_vecs": None,
        "edu_records": [],
        "exp_records": [],
    }

    if user_skills:
        user_skills_norm = []
        for s in user_skills:
            normalized_text = _light_normalise_skill_text(s)
            user_skills_norm.append(normalized_text)
        vectors["user_skills_vecs"] = model.encode(user_skills_norm)

    edu_rows = []
    for edu in educations:
        # Check if degree is not None or empty
        if edu.degree is not None:
            cleaned_text = edu.degree.strip()
            if cleaned_text != "":
                # Degree is valid, add it!
                edu_rows.append(edu)
    
  
    # Step 6: turn each degree into a vector, and store it with its tier info
    if edu_rows:
        cleaned_degree_texts = []
        for edu in edu_rows:
            # _normalise_education_text ALREADY strips and lowercases!
            clean_text = _normalise_education_text(edu.degree)
            cleaned_degree_texts.append(clean_text)
        
        degree_vecs = model.encode(cleaned_degree_texts)

        for i in range(len(edu_rows)):
            edu = edu_rows[i]
            vectors["edu_records"].append({
                "id": edu.id,
                "degree": edu.degree.strip(),
                "tier": DEGREE_LEVEL_TIER_MAP.get(edu.degree_level),
                "vec": degree_vecs[i].reshape(1, -1),
            })

    # Step 7: turn each past role's title into a vector, and store it with its details
    if experiences:
        role_titles = []
        for exp in experiences:
            role_titles.append(exp.role.strip())
        role_vecs = model.encode(role_titles)

        exp_records = []
        for i in range(len(experiences)):
            exp = experiences[i]
            skill_names = list(exp.skills_used.values_list("name", flat=True))
            exp_records.append({
                "id": exp.id,
                "years": exp.years,
                "role": exp.role.strip(),
                "skills_used": skill_names,
                "vec": role_vecs[i].reshape(1, -1),
            })
        vectors["exp_records"] = exp_records

    return vectors

def build_cached_profile_payload(profile):
    data = precompute_profile_vectors(profile)
    
    # 1. Convert Education Records
    formatted_edu_records = []
    for r in data["edu_records"]:
        record = {
            "id": r["id"],
            "degree": r["degree"],
            "tier": r["tier"],
            "vec": r["vec"].tolist()  # Convert NumPy vector to standard list
        }
        formatted_edu_records.append(record)

    # 2. Convert Experience Records
    formatted_exp_records = []
    for r in data["exp_records"]:
        record = {
            "id": r["id"],
            "years": r["years"],
            "role": r["role"],
            "skills_used": r["skills_used"],
            "vec": r["vec"].tolist()  # Convert NumPy vector to standard list
        }
        formatted_exp_records.append(record)

    # 3. Return the complete dictionary at the very end
    return {
        "user_skills": data["user_skills"],
        "user_skills_vecs": data["user_skills_vecs"].tolist()
                            if data["user_skills_vecs"] is not None else None,
        "edu_records": formatted_edu_records,
        "exp_records": formatted_exp_records,
    }



def load_profile_vectors_from_cache(cached: dict):
    # 1. Restore Top-Level Skill Vectors
    user_skills_vecs = None
    if cached["user_skills_vecs"] is not None:
        user_skills_vecs = np.array(cached["user_skills_vecs"])

    # 2. Restore Education Records
    restored_edu_records = []
    for r in cached["edu_records"]:
        record = {
            "id": r.get("id"),
            "degree": r["degree"],
            "tier": r["tier"],
            "vec": np.array(r["vec"])  # Convert list back into NumPy array
        }
        restored_edu_records.append(record)

    # 3. Restore Experience Records
    restored_exp_records = []
    for r in cached["exp_records"]:
        record = {
            "id": r.get("id"),
            "years": r["years"],
            "role": r["role"],
            "skills_used": r["skills_used"],
            "vec": np.array(r["vec"])  # Convert list back into NumPy array
        }
        restored_exp_records.append(record)

    # 4. Assemble and Return the Final Dictionary
    return {
        "user_skills": cached["user_skills"],
        "user_skills_vecs": user_skills_vecs,
        "edu_records": restored_edu_records,
        "exp_records": restored_exp_records,
    }


def _light_normalise_skill_text(text: str) -> str:
    # 1. Lowercase the text
    clean_text = text.lower()
    
    # 2. Split by any whitespace and join with single spaces
    return " ".join(clean_text.split())

def _build_pk_skill_reverse_lookup(taxonomy: dict) -> dict:
   
    lookup = {}
    for entry in taxonomy.values():
        canonical = entry.get("canonical_name")
        if not canonical:
            continue

        clean_canonical_key = _light_normalise_skill_text(canonical)
        lookup[clean_canonical_key] = canonical
        
        # 5. Get all alternative names (aliases) for this skill
        aliases_list = entry.get("aliases", [])
        
        # 6. Map each clean alias to the official canonical name
        for alias in aliases_list:
            clean_alias_key = _light_normalise_skill_text(alias)
            lookup[clean_alias_key] = canonical
    return lookup


def _build_pk_distinct_variant_lookup(taxonomy: dict) -> dict:
    
    lookup = {}
    for entry in taxonomy.values():
        canonical = entry.get("canonical_name")
        if not canonical:
            continue
        # 4. Get the list of distinct/conflicting variants
        variants_list = entry.get("distinct_variants", [])
        
        # 5. Clean each variant and add it to a set
        cleaned_variants_set = set()
        for variant in variants_list:
            clean_variant_text = _light_normalise_skill_text(variant)
            cleaned_variants_set.add(clean_variant_text)
            
        # 6. Save the set to our lookup dictionary under the canonical key
        lookup[canonical] = cleaned_variants_set
    return lookup


_PK_SKILL_REVERSE_LOOKUP = _build_pk_skill_reverse_lookup(_PK_SKILL_TAXONOMY_RAW)
_PK_SKILL_DISTINCT_VARIANTS = _build_pk_distinct_variant_lookup(_PK_SKILL_TAXONOMY_RAW)

# 2. Safety check function to see if two skills are flagged as different in DB
def _is_db_distinct_override(job_norm: str, cand_norm: str) -> bool:
    # Step A: Sort the two skill names so order doesn't matter ("A", "B") vs ("B", "A")
    ordered_skill_pair = _ordered_pair(job_norm, cand_norm)
    
    # Step B: Get the list/set of manual database overrides
    db_overrides_set = _get_skill_distinct_overrides()
    
    # Step C: Check if this pair exists in the overrides list
    if ordered_skill_pair in db_overrides_set:
        return True
    else:
        return False




def _is_pk_distinct_variant(job_skill_norm: str, candidate_skill_norm: str) -> bool:
    
    job_canonical = _PK_SKILL_REVERSE_LOOKUP.get(job_skill_norm)
    cand_canonical = _PK_SKILL_REVERSE_LOOKUP.get(candidate_skill_norm)

    # Resolve each side's distinct_variants list to canonical names too,
    # so comparing against the OTHER side's canonical always lines up
    # regardless of which alias/spelling was actually typed.
    def _variant_canonicals(canonical_name):
        raw_variants = _PK_SKILL_DISTINCT_VARIANTS.get(canonical_name, set())
        resolved = set()
        for v in raw_variants:
            resolved.add(_PK_SKILL_REVERSE_LOOKUP.get(v, v))  # fall back to raw text if variant itself isn't a known canonical/alias
        return resolved

    if job_canonical and cand_canonical:
        if cand_canonical in _variant_canonicals(job_canonical):
            return True
        if job_canonical in _variant_canonicals(cand_canonical):
            return True

    return False




def _resolve_skill_alias(normalised_text: str) -> str:
    overrides = _get_skill_alias_overrides()
    for a, b in overrides:
        if normalised_text == a or normalised_text == b:
            return a   # always canonicalize to the same side of the pair

    if normalised_text in _PK_SKILL_REVERSE_LOOKUP:
        return _light_normalise_skill_text(_PK_SKILL_REVERSE_LOOKUP[normalised_text])

    if normalised_text in _ESCO_SKILL_ALIASES:
        return _ESCO_SKILL_ALIASES[normalised_text]

    return normalised_text


# -------------------------------------------------------
# ACRONYM / INITIALISM MATCHER
# -------------------------------------------------------

def _to_initials_candidates(phrase: str) -> set:
  
    words = re.findall(r"[a-zA-Z0-9]+", phrase.lower())
    if not words:
        return set()

    initials = "".join(w[0] for w in words).upper()

    candidates = {initials}
    if len(words) == 1:
        candidates.add(words[0].upper())
    return candidates

def _acronym_match_score(skill_a: str, skill_b: str) -> float:

    def _is_short_form(s: str) -> bool:
        stripped = re.sub(r"[.\-]", "", s)
        no_space = stripped.replace(" ", "")
        no_space = no_space.replace("/", "")

        is_short_length = len(no_space) <= 6

        has_no_space = " " not in stripped
        has_slash = "/" in stripped

        if has_no_space or has_slash:
            passes_space_check = True
        else:
            passes_space_check = False

        if is_short_length and passes_space_check:
            return True
        else:
            return False

    def _clean(s: str) -> str:
        no_dots_slashes = re.sub(r"[./]", "", s)
        return no_dots_slashes.upper()

    a_is_short = _is_short_form(skill_a)
    b_is_short = _is_short_form(skill_b)

    if a_is_short and not b_is_short:
        short = skill_a
        long_ = skill_b
    elif b_is_short and not a_is_short:
        short = skill_b
        long_ = skill_a
    else:
        return 0.0

    short_clean = _clean(short)
    candidates = _to_initials_candidates(long_)

    if short_clean in candidates:
        return 1.0
    else:
        return 0.0


# -------------------------------------------------------
# FUZZY TYPO MATCHER
# -------------------------------------------------------
FUZZY_MATCH_MIN_LEN = 3
TYPO_MAX_EDIT_DISTANCE = 1

def _is_typo_match(skill_a_norm, skill_b_norm):
    a_no_space = skill_a_norm.replace(" ", "")
    b_no_space = skill_b_norm.replace(" ", "")

    a_len = len(a_no_space)
    b_len = len(b_no_space)

    shorter_len = min(a_len, b_len)

    if shorter_len < FUZZY_MATCH_MIN_LEN:
        return False

    edit_distance = DamerauLevenshtein.distance(skill_a_norm, skill_b_norm)

    if edit_distance <= TYPO_MAX_EDIT_DISTANCE:
        return True
    else:
        return False


def _best_pairwise_score(job_skill_raw, user_skills_raw, emb_sims_row):
    job_norm = _light_normalise_skill_text(job_skill_raw)
    job_alias = _resolve_skill_alias(job_norm)

    best = 0.0
    best_user_skill = None   

    for j in range(len(user_skills_raw)):
        user_skill_raw = user_skills_raw[j]
        cand_norm = _light_normalise_skill_text(user_skill_raw)

        is_exact_match = (job_norm == cand_norm)
        if is_exact_match:
            return 1.0, user_skill_raw   

        cand_alias = _resolve_skill_alias(cand_norm)
        if job_alias == cand_alias:
            return 1.0, user_skill_raw   

        is_pk_distinct = _is_pk_distinct_variant(job_norm, cand_norm)
        is_db_distinct = _is_db_distinct_override(job_norm, cand_norm)
        if is_pk_distinct or is_db_distinct:
            continue

        is_typo = _is_typo_match(job_norm, cand_norm)
        if is_typo:
            return 1.0, user_skill_raw   

        acronym_score = _acronym_match_score(job_norm, cand_norm)
        if acronym_score == 1.0:
            return 1.0, user_skill_raw   

        emb = float(emb_sims_row[j])
        if emb > best:
            best = emb
            best_user_skill = user_skill_raw   

    return best, best_user_skill   
# -------------------------------------------------------
# 2. SKILL SCORING (2-tier)
# -------------------------------------------------------
def calculate_skill_score(user_skills, user_skills_vecs, required_skills, optional_skills=None):

    if optional_skills is None:
        optional_skills = []

    all_job_skills = required_skills + optional_skills

    if len(all_job_skills) == 0:
        return 0.0, [], []   

    if len(user_skills) == 0 or user_skills_vecs is None:
        return 0.0, list(required_skills), []   

    job_skills_norm = []
    for s in all_job_skills:
        normalized = _light_normalise_skill_text(s)
        job_skills_norm.append(normalized)

    job_vecs = model.encode(job_skills_norm)
    sim_matrix = cosine_similarity(job_vecs, user_skills_vecs)

    weighted_score = 0.0
    max_possible = 0.0
    missing = []
    matched_user_skills = set()   
    required_count = len(required_skills)

    for i in range(len(all_job_skills)):
        skill = all_job_skills[i]

        if i < required_count:
            weight = REQUIRED_SKILL_WEIGHT
        else:
            weight = OPTIONAL_SKILL_WEIGHT

        max_possible = max_possible + weight

        best_sim, matched_skill = _best_pairwise_score(skill, user_skills, sim_matrix[i])   

        if best_sim >= SKILL_MATCH_THRESHOLD:
            weighted_score = weighted_score + (best_sim * weight)
            if matched_skill:
                matched_user_skills.add(matched_skill)   

        elif best_sim >= SKILL_PARTIAL_MATCH_THRESHOLD:
            threshold_range = SKILL_MATCH_THRESHOLD - SKILL_PARTIAL_MATCH_THRESHOLD
            distance_above_floor = best_sim - SKILL_PARTIAL_MATCH_THRESHOLD
            partial_ratio = distance_above_floor / threshold_range

            weighted_score = weighted_score + (best_sim * weight * partial_ratio)

            if matched_skill:
                matched_user_skills.add(matched_skill)   

            if i < required_count:
                missing.append(skill)

        else:
            if i < required_count:
                missing.append(skill)

    if max_possible == 0:
        return 0.0, list(required_skills), []   

    score = (weighted_score / max_possible) * 100.0
    score = np.clip(score, 0.0, 100.0)

    if required_count > 0:
        matched_required = required_count - len(missing)
        coverage = matched_required / required_count

        if coverage <= MIN_REQUIRED_SKILL_COVERAGE:
            score = score * (coverage / MIN_REQUIRED_SKILL_COVERAGE)

    final_score = round(score, 2)
    return final_score, missing, list(matched_user_skills)   
# -------------------------------------------------------
# 3. EDUCATION SCORING
# -------------------------------------------------------


def _normalise_field_text(text):
    text = text.lower()
    text = re.sub(r"[./]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text


def _build_field_reverse_lookup(taxonomy):
    lookup = {}

    for canonical, entry in taxonomy.items():
        canonical_key = _normalise_field_text(canonical)
        lookup[canonical_key] = canonical

        aliases_list = entry.get("aliases", [])
        for alias in aliases_list:
            alias_key = _normalise_field_text(alias)
            lookup[alias_key] = canonical

    return lookup


if _EDU_FIELD_TAXONOMY:
    _EDU_FIELD_REVERSE_LOOKUP = _build_field_reverse_lookup(_EDU_FIELD_TAXONOMY)
else:
    _EDU_FIELD_REVERSE_LOOKUP = {}


def _resolve_job_field_to_taxonomy(job_field_text):
    normalized = _normalise_field_text(job_field_text)
    return _EDU_FIELD_REVERSE_LOOKUP.get(normalized)


def _dataset_field_sim(candidate_degree_text, canonical_field, accept_related):
    entry = _EDU_FIELD_TAXONOMY.get(canonical_field)

    if entry is None:
        return None
    if not candidate_degree_text:
        return None

    haystack = _normalise_field_text(candidate_degree_text)

    own_names = [canonical_field]
    aliases = entry.get("aliases", [])
    for alias in aliases:
        own_names.append(alias)

    found_own_name = False
    for name in own_names:
        cleaned_name = _normalise_field_text(name)
        pattern = r"(?<!\w)" + re.escape(cleaned_name) + r"(?!\w)"
        if re.search(pattern, haystack):
            found_own_name = True
            break

    if found_own_name:
        return 1.0

    if accept_related:
        related = entry.get("related_fields", [])

        found_related = False
        for name in related:
            cleaned_name = _normalise_field_text(name)
            pattern = r"(?<!\w)" + re.escape(cleaned_name) + r"(?!\w)"
            if re.search(pattern, haystack):
                found_related = True
                break

        if found_related:
            return 0.80

    return None

def _education_level_penalty(job_level, user_level):
    if job_level is None:
        return 1.0
    if user_level is None:
        return 1.0
    if job_level == user_level:
        return 1.0

    tier_gap = job_level - user_level

    if tier_gap > 0:
        penalty_amount = tier_gap * LEVEL_MISMATCH_PENALTY_PER_TIER
        multiplier = 1.0 - penalty_amount

        if multiplier > LEVEL_MISMATCH_FLOOR:
            return multiplier
        else:
            return LEVEL_MISMATCH_FLOOR

    else:
        gap_size = abs(tier_gap)
        penalty_amount = gap_size * LEVEL_MISMATCH_PENALTY_PER_TIER * LEVEL_OVERQUALIFIED_DAMPENER
        multiplier = 1.0 - penalty_amount

        if multiplier > LEVEL_OVERQUALIFIED_FLOOR:
            return multiplier
        else:
            return LEVEL_OVERQUALIFIED_FLOOR


def _split_into_field_candidates(text):
    lowered = text.lower()
    parts = lowered.split(",")

    cleaned = []
    for p in parts:
        cleaned.append(p.strip())

    result = []
    for p in cleaned:
        if p and len(p) > 1:
            result.append(p)

    return result

def precompute_job_education_fields(job_edu_text):
    if not job_edu_text:
        return []
    if not job_edu_text.strip():
        return []

    fields = _split_into_field_candidates(job_edu_text)

    if not fields:
        return []

    normalized_fields = []
    for f in fields:
        normalized = _normalise_education_text(f)
        normalized_fields.append(normalized)

    vecs = model.encode(normalized_fields)

    result = []
    for i in range(len(fields)):
        field_name = fields[i]
        field_vec = vecs[i].reshape(1, -1)
        result.append({"field": field_name, "vec": field_vec})

    return result

def build_cached_job_edu_payload(job_edu_text):
    fields = precompute_job_education_fields(job_edu_text)
    return [
        {"field": f["field"], "vec": f["vec"].tolist()}
        for f in fields
    ]

def load_job_edu_fields_from_cache(cached_list):
    if not cached_list:
        return []

    result = []
    for f in cached_list:
        restored_vec = np.array(f["vec"])
        result.append({"field": f["field"], "vec": restored_vec})

    return result
def calculate_education_score(edu_records, job_edu_text, job_degree_tier=None,
                               job_edu_fields=None,
                               accept_related_education_fields=True):

    if not job_edu_text or not job_edu_text.strip():
        return 0.0, None

    if not edu_records:
        return 0.0, None

    if not job_edu_fields:
        job_edu_fields = precompute_job_education_fields(job_edu_text)

    if not job_edu_fields:
        return 0.0, None

    title_overrides = _get_title_overrides("education_field")

    best_sim = 0.0
    best_user_tier = None
    best_edu_id = None

    for jf in job_edu_fields:
        jf_norm = _normalise_field_text(jf["field"])
        canonical = _resolve_job_field_to_taxonomy(jf["field"])

        for ue in edu_records:
            ue_norm = _normalise_field_text(ue["degree"])
            pair = _ordered_pair(jf_norm, ue_norm)

            if pair in title_overrides:
                if title_overrides[pair]:
                    sim = 1.0
                else:
                    sim = 0.0
            else:
                sim = None

                if canonical:
                    sim = _dataset_field_sim(ue["degree"], canonical, accept_related_education_fields)

                if sim is None:
                    similarity_matrix = cosine_similarity(ue["vec"], jf["vec"])
                    sim = float(similarity_matrix[0][0])

            if sim > best_sim:
                best_sim = sim
                best_user_tier = ue["tier"]
                best_edu_id = ue.get("id")

    base_score = np.clip(best_sim * 100.0, 0.0, 100.0)
    penalty = _education_level_penalty(job_degree_tier, best_user_tier)
    final_score = round(float(base_score * penalty), 2)
    return final_score, best_edu_id

# -------------------------------------------------------
#  / ROLE OCCUPATION MATCHER
# -------------------------------------------------------
def check_occupation_match(
    job_title: str, 
    role_title: str, 
    threshold: float = 0.55
) -> bool:
    if not job_title or not role_title:
        return False

    t1 = job_title.strip().lower()
    t2 = role_title.strip().lower()

    if t1 == t2 or t1 in t2 or t2 in t1:
        return True

    try:
        vec1 = model.encode([t1])
        vec2 = model.encode([t2])
        sim = float(cosine_similarity(vec1, vec2)[0][0])
        return sim >= threshold
    except Exception:
        return False


# 4. EXPERIENCE SCORING

def calculate_experience_score(exp_records, required_skills, experience_required,
                                job_title="", job_title_vec=None,
                                overall_skill_score=0.0,
                                relevance_threshold=30.0,
                                title_sim_threshold=0.55):

    if experience_required <= 0:
        return 100.0, False, []

    if not exp_records:
        return 0.0, False, []

    title_overrides = _get_title_overrides("experience_role")

    if job_title:
        job_title_norm = _normalise_field_text(job_title)
    else:
        job_title_norm = ""

    total_relevant_years = 0.0
    relevant_exp_ids = []

    for exp in exp_records:
        try:
            raw_years = exp.get("years", 0.0) or 0.0
            role_years = float(raw_years)
        except (ValueError, TypeError):
            role_years = 0.0

        raw_role_title = exp.get("role", "") or ""
        role_title = str(raw_role_title).strip()

        role_skills = exp.get("skills_used", []) or []

        if role_years <= 0.0:
            continue

        is_relevant = False

        if role_title:
            role_norm = _normalise_field_text(role_title)
        else:
            role_norm = ""

        if job_title_norm and role_norm:
            pair = _ordered_pair(job_title_norm, role_norm)
        else:
            pair = None

        if pair and pair in title_overrides:
            is_relevant = title_overrides[pair]

        elif role_skills and required_skills:
            role_skills_norm = [_light_normalise_skill_text(s) for s in role_skills]
            role_skills_vecs = model.encode(role_skills_norm)
            role_skill_score, _, _ = calculate_skill_score(
                user_skills=role_skills,
                user_skills_vecs=role_skills_vecs,
                required_skills=required_skills
            )
            is_relevant = role_skill_score >= relevance_threshold

        elif role_title and job_title_vec is not None and exp.get("vec") is not None:
            sim = float(cosine_similarity(exp["vec"], job_title_vec.reshape(1, -1))[0][0])
            is_relevant = sim >= title_sim_threshold
        elif job_title and role_title:
            is_relevant = check_occupation_match(job_title, role_title, threshold=title_sim_threshold)

        if is_relevant:
            total_relevant_years += role_years
            exp_id = exp.get("id")
            if exp_id is not None:
                relevant_exp_ids.append(exp_id)

    if total_relevant_years <= 0.0:
        return 0.0, False, []

    ratio = total_relevant_years / experience_required

    if ratio <= 1.0:
        score = 90.0 * ratio
    elif ratio <= 1.5:
        score = 90.0 + (ratio - 1.0) / 0.5 * 10.0
    else:
        score = 100.0

    exceeds_experience = total_relevant_years > experience_required

    clipped_score = np.clip(score, 0.0, 100.0)
    final_score = round(float(clipped_score), 2)

    return final_score, exceeds_experience, relevant_exp_ids


########################################## existing data using admin feedback data
def jobs_using_skill_pair(skill_a_norm, skill_b_norm):
    # Step 1: find the IDs of skills whose normalized name matches either target
    matching_skill_ids = []
    all_skills = Skill.objects.all()
    for skill in all_skills:
        normalized_name = skill.name.strip().lower()
        if normalized_name == skill_a_norm or normalized_name == skill_b_norm:
            matching_skill_ids.append(skill.id)

    # Step 2: find active jobs that use any of those skills
    matching_job_ids = []
    active_jobs = Job.objects.filter(is_active=True)
    for job in active_jobs:
        job_skill_ids = job.job_skills.values_list("skill_id", flat=True)
        for skill_id in job_skill_ids:
            if skill_id in matching_skill_ids:
                if job.id not in matching_job_ids:
                    matching_job_ids.append(job.id)
                break

    return matching_job_ids


def jobs_using_title(title_norm):
    job_ids = []
    active_jobs = Job.objects.filter(is_active=True)
    for job in active_jobs:
        job_title_normalized = _normalise_field_text(job.title)
        if job_title_normalized == title_norm:
            job_ids.append(job.id)
    return job_ids


def jobs_using_edu_field(field_norm):
    job_ids = []
    jobs_with_edu_data = Job.objects.filter(is_active=True).exclude(cached_edu_fields=None)
    
    for job in jobs_with_edu_data:
        edu_field_list = job.cached_edu_fields or []
        normalized_fields = []
        for entry in edu_field_list:
            normalized_fields.append(_normalise_field_text(entry["field"]))
        
        if field_norm in normalized_fields:
            job_ids.append(job.id)
    
    return job_ids


def _approve_skill_feedback(fb, reviewed_by):
    # Step 1: normalize both skill names from the feedback
    skill_a = _light_normalise_skill_text(fb.job_skill_text)
    skill_b = _light_normalise_skill_text(fb.user_skill_text)
    skill_a, skill_b = _ordered_pair(skill_a, skill_b)  # put them in a consistent order

    # Step 2: record the reviewer's decision
    if fb.judged_same:
        # reviewer said: these two skill names mean the same thing
        existing = SkillAliasOverride.objects.filter(skill_a_norm=skill_a, skill_b_norm=skill_b).first()
        if not existing:
            SkillAliasOverride.objects.create(
                skill_a_norm=skill_a, skill_b_norm=skill_b, source_feedback=fb
            )
        cache.delete("skill_alias_overrides")
    else:
        # reviewer said: these are genuinely different skills
        existing = SkillDistinctOverride.objects.filter(skill_a_norm=skill_a, skill_b_norm=skill_b).first()
        if not existing:
            SkillDistinctOverride.objects.create(
                skill_a_norm=skill_a, skill_b_norm=skill_b, source_feedback=fb
            )
        cache.delete("skill_distinct_overrides")

    # Step 3: mark the feedback ticket as approved
    fb.status = "approved"
    fb.reviewed_by = reviewed_by
    fb.reviewed_at = timezone.now()
    fb.save()

    # Step 4: find every job that used either skill, and recompute their matches
    affected_job_ids = jobs_using_skill_pair(skill_a, skill_b)

    def queue_rematching():
        from jobs.tasks import generate_matches_for_job
        tasks = [generate_matches_for_job.si(job_id) for job_id in affected_job_ids]
        group(tasks).delay()

    transaction.on_commit(queue_rematching)


def _approve_title_feedback(fb, reviewed_by):
    # Step 1: normalize both text values
    text_a = _normalise_field_text(fb.job_text)
    text_b = _normalise_field_text(fb.user_text)
    text_a, text_b = _ordered_pair(text_a, text_b)

    # Step 2: save (or update) the reviewer's decision
    TitleMatchOverride.objects.update_or_create(
        kind=fb.kind,
        text_a_norm=text_a,
        text_b_norm=text_b,
        defaults={
            "judged_same": fb.judged_same,
            "source_feedback": fb,
        },
    )
    cache.delete(f"title_overrides_{fb.kind}")

    # Step 3: mark feedback as approved
    fb.status = "approved"
    fb.reviewed_by = reviewed_by
    fb.reviewed_at = timezone.now()
    fb.save()

    # Step 4: figure out which jobs are affected, depending on the "kind" of feedback
    job_text_normalized = _normalise_field_text(fb.job_text)

    if fb.kind == "experience_role":
        affected_job_ids = jobs_using_title(job_text_normalized)
    else:
        affected_job_ids = jobs_using_edu_field(job_text_normalized)

    def queue_rematching():
        from jobs.tasks import generate_matches_for_job
        tasks = [generate_matches_for_job.si(job_id) for job_id in affected_job_ids]
        group(tasks).delay()

    transaction.on_commit(queue_rematching)