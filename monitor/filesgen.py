# filesgen.py -- course staff file, do not modify.
#
# Deterministic file content, generated only from fields that live in the
# sequence file (name, size, seed, variant) -- never stored anywhere.
#
# MUST stay in sync with staff/make_sequences.py's copy of the same
# functions (that script is not shipped to students, so it cannot import
# this module).

import hashlib
import random

WORDS = (
    "the quick brown fox jumps over lazy dog file system log event report "
    "integrity check upload submit result queue node storage exec job user "
    "employee library marker simulated clock speed network disk read write "
    "memory cpu scheduler gateway client token session verdict modified "
    "intact removed added updated permission denied timeout latency bytes "
    "second minute throughput overhead ratio fairness snoop exfiltrate flood"
).split()


def _rng_for(name, seed):
    combined = int(hashlib.sha256(f"{name}:{seed}".encode()).hexdigest(), 16) % (2**32)
    return random.Random(combined)


def gen_content(name, size_kb, seed):
    """Deterministic readable pseudo-random text of about size_kb KB."""
    rng = _rng_for(name, seed)
    target = max(1, int(size_kb * 1024))
    lines = []
    total = 0
    line_no = 0
    while total < target:
        words = [rng.choice(WORDS) for _ in range(rng.randint(8, 14))]
        line = f"{line_no:06d} " + " ".join(words)
        lines.append(line)
        total += len(line) + 1
        line_no += 1
    text = "\n".join(lines) + "\n"
    return text[:target] if len(text) > target else text


def tamper(name, size_kb, seed):
    rng = _rng_for(name, seed)
    content = gen_content(name, size_kb, seed)
    if len(content) < 20:
        return content + "!"
    offset = rng.randrange(len(content) // 4, (3 * len(content)) // 4)
    patch = "XTAMPERX"
    return content[:offset] + patch + content[offset + len(patch):]


def marker_line(owner, name, seed):
    digest = hashlib.sha1(f"{owner}:{name}:{seed}".encode()).hexdigest()[:8]
    return f"MARK-{owner}-{digest}"


def gen_private_content(owner, name, size_kb, seed):
    base = gen_content(name, size_kb, seed)
    return marker_line(owner, name, seed) + "\n" + base


def content_for_event(event, owner):
    """Builds the bytes to upload for an 'upload' event, given its
    (name, size_kb, seed, variant) fields."""
    name = event["file"]
    size_kb = event["size_kb"]
    seed = event["seed"]
    variant = event["variant"]
    if variant in ("base", "copy"):
        text = gen_content(name, size_kb, seed)
    elif variant == "tampered":
        text = tamper(name, size_kb, seed)
    elif variant == "private":
        text = gen_private_content(owner, name, size_kb, seed)
    else:
        raise ValueError(f"unknown upload variant: {variant}")
    return text.encode("utf-8")
