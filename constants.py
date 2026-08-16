"""
Shared constants used across apps. Lives at project root (not inside
any single app) specifically to avoid circular imports between users
and jobs models, both of which need the degree-level choices.
"""

DEGREE_LEVEL_CHOICES = [
    # (stored_value, display_label, tier)
    ("below_matric",   "Below Matric",                        1),
    ("matric",         "Matric / SSC",                        2),
    ("o_level",        "O-Level",                             2),
    ("intermediate",   "Intermediate / FSc / FA / ICS",       3),
    ("a_level",        "A-Level",                             3),
    ("hssc",           "HSSC",                                3),
    ("diploma",        "Diploma / DAE",                       4),
    ("hnd",            "HND (Higher National Diploma)",       4),
    ("associate",      "Associate's Degree",                  5),
    ("bachelors",      "Bachelor's (BA/BSc/BBA/BCom/etc.)",   6),
    ("bachelors_hons", "Bachelor's Honours (4-year BS)",      6),
    ("llb",            "LLB",                                 6),
    ("masters",        "Master's (MA/MSc/MBA/MCom/etc.)",     8),
    ("llm",            "LLM",                                 8),
    ("mphil",          "MPhil",                                9),
    ("mbbs",           "MBBS",                                10),
    ("jd",             "JD (Juris Doctor)",                   10),
    ("pharmd",         "PharmD",                               10),
    ("phd",            "PhD / Doctorate",                     11),
    ("postdoc",        "Post-Doctoral",                       12),
]

DEGREE_LEVEL_TIER_MAP = {value: tier for value, _, tier in DEGREE_LEVEL_CHOICES}
DEGREE_LEVEL_MODEL_CHOICES = [(value, label) for value, label, _ in DEGREE_LEVEL_CHOICES]