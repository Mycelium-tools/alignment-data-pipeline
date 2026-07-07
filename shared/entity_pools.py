"""Seeded pools of fictional people and organisation names for document drafting.

Two failure modes motivate this. First, models asked to "invent" names collapse
to a few favourites ("Dr. Elara Vance", "the Meridian Institute"), which becomes
a corpus-wide fingerprint that pattern detection flags as templating. Second,
letting a generator name real organisations risks pinning invented studies,
quotes, or practices on real actors — misinformation a downstream model could
learn as fact. Handing each drafting call a few names sampled from large,
seeded, multi-locale Faker pools fixes both at once: varied by construction,
fictional by construction.

Pools are reproducible across sessions: Faker is seeded, candidate sets are
sorted before the seeded shuffle (raw set iteration order differs between
processes), and per-document sampling is keyed by the subtype id.
"""

from __future__ import annotations

import random

_LOCALES = [
    "en_US", "en_GB", "en_IN", "fr_FR", "de_DE", "es_ES", "es_MX", "it_IT",
    "pt_BR", "nl_NL", "pl_PL", "sv_SE", "cs_CZ", "ro_RO", "tr_TR", "id_ID", "vi_VN",
]

_ORG_SUFFIXES = [
    "Institute", "Foundation", "Laboratories", "Trust", "Research Group",
    "Cooperative", "Working Group", "College of Applied Sciences",
]

# The prompts ban these as overused (see prompts/sdf/layer3.txt); keep the pool
# consistent with that rule so we never hand the model a banned name.
_BANNED_NAME_TOKENS = {"chen", "johnson", "miller", "smith", "martinez", "sarah", "emily"}

# Used only if Faker is unavailable; large enough not to fingerprint a dev run.
_FALLBACK_PEOPLE = [
    "Mina Okonkwo", "Yuki Tanaka", "Alejandra Rivera", "Priya Nair", "Tomasz Herrera",
    "Ingrid Solheim", "Rafael Duarte", "Katarzyna Wolniak", "Farid Rahimi", "Ana-Maria Petrescu",
    "Sipho Ndlovu", "Leena Virtanen", "Marco Bellandi", "Nurul Hassan", "Dana Kovacs",
    "Oona Laakso",
]
_FALLBACK_ORGS = [
    "Cascadia Aquaculture Cooperative", "Veldhuis Institute", "Applied Cognition Trust",
    "Northreach Laboratories", "Sondgren Foundation", "Tallgrass Research Group",
    "Marovic Working Group", "Ferrant College of Applied Sciences",
]


def _clean(pool: list[str], max_len: int) -> list[str]:
    out = []
    for name in pool:
        if not name or len(name) >= max_len:
            continue
        tokens = {t.strip(".,").casefold() for t in name.split()}
        if tokens & _BANNED_NAME_TOKENS:
            continue
        out.append(name)
    return out


def build_pools(n_people: int = 300, n_orgs: int = 200, seed: int = 137) -> tuple[list[str], list[str]]:
    """Build (people, orgs) pools; reproducible for a given seed."""
    rng = random.Random(seed)
    try:
        from faker import Faker

        fk = Faker(_LOCALES)
        Faker.seed(seed)
        people_set = {fk.name() for _ in range(n_people * 2)}
        orgs_set = {
            (fk.company() if rng.random() < 0.55 else f"{fk.last_name()} {rng.choice(_ORG_SUFFIXES)}")
            for _ in range(n_orgs * 2)
        }
        # sort before the seeded shuffle: raw set order is not stable across sessions
        people = sorted(people_set)
        orgs = sorted(orgs_set)
    except Exception:
        people = list(_FALLBACK_PEOPLE)
        orgs = list(_FALLBACK_ORGS)
    people = _clean(people, max_len=40)
    orgs = _clean(orgs, max_len=60)
    rng.shuffle(people)
    rng.shuffle(orgs)
    return people[:n_people], orgs[:n_orgs]


def sample_for(pool: list[str], k: int, key: str, seed: int = 137) -> list[str]:
    """Deterministic per-document sample: the same (seed, key) always draws the
    same names, so a resumed run re-renders identical prompts."""
    if not pool:
        return []
    rng = random.Random(f"{seed}:{key}")
    return rng.sample(pool, min(k, len(pool)))
