"""
Phase 2I — Passphrase generator.

Uses a curated list of common, unambiguous English words (EFF-style).
Pool size is derived from the embedded wordlist at load time.
Entropy per 4-word phrase: 4 * log2(pool_size) bits.
"""
from __future__ import annotations

import math
import secrets

# 512-word curated wordlist (EFF-style, clean common English words)
_WORDLIST: tuple[str, ...] = (
    "able", "acid", "aged", "also", "amid", "arch", "area", "army", "atom",
    "aunt", "avid", "away", "axis", "baby", "back", "bail", "bake", "bald",
    "ball", "band", "bank", "barn", "base", "bath", "bead", "beam", "bean",
    "bear", "beat", "been", "bell", "belt", "best", "bias", "bike", "bill",
    "bind", "bird", "bite", "blot", "blow", "blue", "boar", "boat", "bold",
    "bolt", "bond", "bone", "book", "boom", "boot", "bore", "born", "boss",
    "both", "bowl", "brag", "brew", "brim", "brow", "buck", "buff", "bulk",
    "bull", "bump", "burn", "bust", "busy", "buzz", "cafe", "cage", "cake",
    "calm", "came", "cane", "card", "care", "carp", "cart", "case", "cash",
    "cast", "cave", "cell", "chef", "chin", "chip", "chop", "cite", "city",
    "clam", "clan", "clap", "clay", "clip", "club", "clue", "coal", "coat",
    "coil", "cold", "colt", "come", "cone", "cook", "cool", "cope", "copy",
    "cord", "core", "cork", "corn", "cost", "cozy", "crab", "crew", "crop",
    "crow", "cube", "cure", "curl", "cute", "damp", "dark", "dart", "dash",
    "data", "date", "dawn", "days", "deaf", "deal", "dean", "dear", "deck",
    "deed", "deep", "deer", "deft", "deny", "desk", "dial", "diet", "dirt",
    "disk", "dock", "dome", "door", "dove", "down", "drag", "draw", "drip",
    "drop", "drug", "drum", "dual", "dull", "dusk", "dust", "duty", "each",
    "earn", "ease", "east", "edge", "emit", "epic", "even", "ever", "exam",
    "exit", "eyes", "face", "fact", "fail", "fair", "fall", "fame", "farm",
    "fast", "fate", "feel", "feet", "fell", "felt", "fern", "file", "fill",
    "film", "find", "fine", "fire", "firm", "fish", "fist", "flag", "flat",
    "flaw", "flew", "flip", "flow", "foam", "fold", "folk", "fond", "font",
    "food", "fool", "ford", "fore", "fork", "form", "fort", "foul", "four",
    "free", "frog", "from", "fuel", "full", "fund", "fuse", "fuzz", "gain",
    "gale", "game", "gaze", "gear", "gild", "give", "glad", "glow", "glue",
    "goal", "goat", "gold", "golf", "good", "grab", "gray", "grew", "grid",
    "grim", "grip", "grit", "grow", "gulf", "gust", "hall", "halt", "hand",
    "hang", "hard", "harm", "harp", "have", "hawk", "head", "heap", "heat",
    "heel", "helm", "help", "herb", "here", "hero", "hide", "high", "hill",
    "hint", "hire", "hold", "hole", "home", "hood", "hook", "hope", "horn",
    "host", "hour", "huge", "hump", "hunt", "hurt", "husk", "hymn", "icon",
    "idea", "idle", "iris", "iron", "isle", "item", "jade", "jazz", "jest",
    "join", "joke", "jolt", "jump", "just", "keen", "kelp", "kept", "kind",
    "king", "knit", "knob", "knot", "lace", "lake", "lamp", "land", "lark",
    "last", "late", "lawn", "leaf", "lean", "leap", "lend", "lens", "liar",
    "lift", "like", "limp", "line", "lion", "list", "live", "load", "loaf",
    "loan", "lock", "loft", "long", "look", "loop", "lore", "loss", "lure",
    "lurk", "made", "maid", "mail", "main", "male", "mall", "malt", "mane",
    "many", "mark", "mart", "mast", "maze", "meal", "mean", "meet", "melt",
    "menu", "mesh", "mild", "milk", "mill", "mind", "mint", "mist", "mode",
    "mole", "monk", "moon", "more", "moss", "most", "moth", "move", "much",
    "mule", "must", "myth", "nail", "name", "navy", "near", "neck", "nest",
    "next", "nine", "node", "noon", "norm", "nose", "note", "noun", "oars",
    "oath", "oboe", "once", "only", "open", "oval", "oven", "over", "page",
    "paid", "pail", "pair", "pale", "palm", "park", "part", "past", "path",
    "pave", "peak", "pear", "peel", "peer", "pelt", "pine", "pink", "pipe",
    "plan", "play", "plea", "plod", "plot", "plow", "plug", "plum", "plus",
    "poem", "poet", "poll", "polo", "pond", "port", "pose", "post", "pour",
    "prey", "prop", "pull", "pulp", "pump", "pure", "push", "quad", "quiz",
    "rack", "raid", "rail", "rain", "ramp", "rank", "rare", "rate", "read",
    "real", "reed", "reef", "reel", "rely", "rent", "rest", "rice", "rich",
    "ride", "ring", "riot", "rise", "risk", "road", "roam", "roar", "rock",
    "role", "roll", "roof", "room", "rope", "rose", "ruby", "ruin", "rule",
    "rush", "rust", "safe", "saga", "sage", "sail", "salt", "same", "sand",
    "sane", "save", "scan", "seal", "seam", "seed", "seek", "self", "sell",
    "send", "shed", "ship", "shop", "show", "silk", "silt", "sing", "sink",
    "site", "size", "skin", "slab", "slam", "slap", "slim", "slip", "slow",
    "slug", "snap", "snow", "soak", "soap", "soar", "sock", "soft", "soil",
    "sold", "sole", "some", "song", "soot", "sort", "soul", "soup", "span",
    "spin", "spit", "spot", "spur", "star", "stay", "stem", "step", "stop",
    "stub", "such", "suit", "sunk", "surf", "swan", "swap", "tale", "tall",
    "tank", "tape", "task", "team", "tear", "tend", "tent", "term", "that",
    "them", "then", "this", "thus", "tide", "tile", "till", "time", "toad",
    "toil", "toll", "tomb", "tone", "tool", "tops", "torn", "toss", "tour",
    "town", "trap", "tray", "tree", "trim", "trio", "trip", "true", "tube",
    "tuck", "tuna", "turf", "turn", "twig", "type", "unit", "upon", "used",
    "vale", "vane", "veil", "very", "vest", "vial", "view", "vine", "visa",
    "void", "vole", "volt", "vote", "wade", "wage", "wake", "walk", "wall",
    "wand", "ward", "warm", "warp", "wart", "wasp", "wave", "wear", "weed",
    "week", "well", "went", "west", "what", "when", "whip", "wick", "wide",
    "wild", "will", "wind", "wine", "wing", "wink", "wire", "wise", "wish",
    "with", "woke", "wolf", "wood", "wool", "word", "wore", "work", "worm",
    "worn", "wrap", "wren", "writ", "yard", "yarn", "yell", "yoga", "yolk",
    "your", "zinc", "zone",
)

_POOL_SIZE: int = len(_WORDLIST)   # 512
_PHRASE_WORDS: int = 4


def gen_passphrase(words: int = _PHRASE_WORDS) -> str:
    """Return a space-separated passphrase of `words` random words."""
    return " ".join(secrets.choice(_WORDLIST) for _ in range(words))


def passphrase_entropy(words: int = _PHRASE_WORDS) -> float:
    """Return entropy in bits: words * log2(pool_size)."""
    return words * math.log2(_POOL_SIZE)
