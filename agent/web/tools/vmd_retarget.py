"""Retarget a VMD made for a model with semi-standard bones to one without them
(あにまさ式 Miku.pmd).

Bones inserted into a chain (上半身2, 腕捩, 手捩, 親指０) are folded into the
bone above them: Q'(parent) = Q(parent) * Q(child), evaluated every frame
(VMD bezier interpolation) and written as dense keys. A lip VMD can be merged
in; its え is spread over あ and い like the stage's lip sync does.

usage: python3 vmd_retarget.py model.pmd motion.vmd out.vmd [--lip lip.vmd] [--end frame]
"""

import argparse
import bisect
import math
import struct
from collections import defaultdict


def dec(raw):
    return raw.split(b"\0", 1)[0].decode("cp932", errors="replace")


def enc(name, size):
    b = name.encode("cp932")
    assert len(b) <= size, name
    return b + b"\0" * (size - len(b))


# ---- files

def read_pmd_names(path):
    b = open(path, "rb").read()
    o = 3 + 4 + 20 + 256
    (n,) = struct.unpack_from("<I", b, o); o += 4 + n * 38
    (n,) = struct.unpack_from("<I", b, o); o += 4 + n * 2
    (n,) = struct.unpack_from("<I", b, o); o += 4 + n * 70
    (n,) = struct.unpack_from("<H", b, o); o += 2
    bones = []
    for _ in range(n):
        bones.append(dec(b[o : o + 20])); o += 39
    (n,) = struct.unpack_from("<H", b, o); o += 2
    for _ in range(n):
        o += 2 + 2 + 1 + 2 + 4 + b[o + 4] * 2
    (n,) = struct.unpack_from("<H", b, o); o += 2
    morphs = []
    for _ in range(n):
        morphs.append(dec(b[o : o + 20]))
        (vc,) = struct.unpack_from("<I", b, o + 20); o += 25 + vc * 16
    return set(bones), set(morphs)


def read_vmd(path):
    b = open(path, "rb").read()
    o = 50
    bones = defaultdict(list)  # name -> [(frame, pos, quat, interp)]
    (n,) = struct.unpack_from("<I", b, o); o += 4
    for _ in range(n):
        name = dec(b[o : o + 15])
        frame, *v = struct.unpack_from("<I7f", b, o + 15)
        bones[name].append((frame, tuple(v[:3]), tuple(v[3:]), b[o + 47 : o + 111]))
        o += 111
    morphs = defaultdict(list)  # name -> [(frame, weight)]
    (n,) = struct.unpack_from("<I", b, o); o += 4
    for _ in range(n):
        name = dec(b[o : o + 15])
        frame, w = struct.unpack_from("<If", b, o + 15)
        morphs[name].append((frame, w))
        o += 23
    for keys in list(bones.values()) + list(morphs.values()):
        keys.sort(key=lambda k: k[0])
    return bones, morphs, b[o:]  # the rest: camera, light, shadow, IK


def write_vmd(path, model, bones, morphs, rest):
    out = [enc("Vocaloid Motion Data 0002", 30), enc(model, 20)]
    nb = sum(len(k) for k in bones.values())
    out.append(struct.pack("<I", nb))
    for name, keys in bones.items():
        for frame, pos, quat, interp in keys:
            out.append(enc(name, 15) + struct.pack("<I7f", frame, *pos, *quat) + interp)
    nm = sum(len(k) for k in morphs.values())
    out.append(struct.pack("<I", nm))
    for name, keys in morphs.items():
        for frame, w in keys:
            out.append(enc(name, 15) + struct.pack("<If", frame, w))
    out.append(rest)
    open(path, "wb").write(b"".join(out))


# ---- math

def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def slerp(a, b, t):
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-x for x in b), -dot
    if dot > 0.9995:
        r = tuple(x + (y - x) * t for x, y in zip(a, b))
    else:
        th = math.acos(dot)
        s = math.sin(th)
        wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
        r = tuple(wa * x + wb * y for x, y in zip(a, b))
    n = math.sqrt(sum(x * x for x in r))
    return tuple(x / n for x in r)


def bezier(x1, y1, x2, y2, t):
    """y at x=t on the curve (0,0) (x1,y1) (x2,y2) (1,1); control values 0..127."""
    x1, y1, x2, y2 = x1 / 127, y1 / 127, x2 / 127, y2 / 127
    if x1 == y1 and x2 == y2:
        return t
    lo, hi = 0.0, 1.0
    for _ in range(30):
        s = (lo + hi) / 2
        x = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3
        lo, hi = (s, hi) if x < t else (lo, s)
    s = (lo + hi) / 2
    return 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3


IDENTITY = (0.0, 0.0, 0.0, 1.0)


def sample(keys, f):
    """(pos, quat) of a bone track at frame f."""
    if not keys:
        return (0.0, 0.0, 0.0), IDENTITY
    frames = [k[0] for k in keys]
    i = bisect.bisect_right(frames, f) - 1
    if i < 0:
        return keys[0][1], keys[0][2]
    if i >= len(keys) - 1:
        return keys[-1][1], keys[-1][2]
    (f0, p0, q0, _), (f1, p1, q1, ip) = keys[i], keys[i + 1]
    t = (f - f0) / (f1 - f0)
    pos = tuple(
        p0[c] + (p1[c] - p0[c]) * bezier(ip[c], ip[4 + c], ip[8 + c], ip[12 + c], t) for c in range(3)
    )
    return pos, slerp(q0, q1, bezier(ip[3], ip[7], ip[11], ip[15], t))


def is_still(keys):
    return all(
        all(abs(x) < 1e-6 for x in pos) and abs(abs(q[3]) - 1) < 1e-6 for _, pos, q, _ in keys
    )


# Linear in every channel: x1 == y1 and x2 == y2.
LINEAR = bytes([20] * 8 + [107] * 8) * 4


# child bone -> the bone of the plain model it folds into
FOLD = {
    "上半身2": "上半身",
    "左腕捩": "左腕", "右腕捩": "右腕",
    "左手捩": "左ひじ", "右手捩": "右ひじ",
    "左親指０": "左親指１", "右親指０": "右親指１",
}


def fold(bones):
    for child, parent in FOLD.items():
        ck = bones.pop(child, [])
        if not ck or is_still(ck):
            continue
        pk = bones.get(parent, [])
        last = max(k[0] for k in pk + ck)
        dense = []
        for f in range(last + 1):
            ppos, pq = sample(pk, f)
            _, cq = sample(ck, f)
            dense.append((f, ppos, qmul(pq, cq), LINEAR))
        bones[parent] = dense
        print(f"folded {child} ({len(ck)} keys) into {parent}: {len(pk)} -> {len(dense)} keys")


def morph_at(keys, f):
    if not keys:
        return 0.0
    frames = [k[0] for k in keys]
    i = bisect.bisect_right(frames, f) - 1
    if i < 0:
        return keys[0][1]
    if i >= len(keys) - 1:
        return keys[-1][1]
    (f0, w0), (f1, w1) = keys[i], keys[i + 1]
    return w0 + (w1 - w0) * (f - f0) / (f1 - f0)


def merge_lip(morphs, lip):
    """Morphs are linear between keys, so sampling at every key frame is exact."""
    for name in lip:
        morphs.pop(name, None)
    e = lip.pop("え", [])
    for name in ("あ", "い"):
        own = lip.get(name, [])
        frames = sorted({k[0] for k in own} | {k[0] for k in e})
        lip[name] = [(f, min(1.0, morph_at(own, f) + 0.5 * morph_at(e, f))) for f in frames]
    morphs.update(lip)


def cut(bones, morphs, end):
    """Drop keys after frame `end`, ending each moving track with its pose at `end`."""
    for name, keys in bones.items():
        kept = [k for k in keys if k[0] <= end]
        if len(kept) < len(keys) and (not kept or kept[-1][0] < end):
            pos, q = sample(keys, end)
            kept.append((end, pos, q, LINEAR))
        bones[name] = kept
    for name, keys in morphs.items():
        kept = [k for k in keys if k[0] <= end]
        if len(kept) < len(keys) and (not kept or kept[-1][0] < end):
            kept.append((end, morph_at(keys, end)))
        morphs[name] = kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pmd")
    ap.add_argument("vmd")
    ap.add_argument("out")
    ap.add_argument("--lip")
    ap.add_argument("--end", type=int, help="last frame to keep")
    a = ap.parse_args()
    pmd_bones, pmd_morphs = read_pmd_names(a.pmd)
    bones, morphs, rest = read_vmd(a.vmd)
    fold(bones)
    if a.lip:
        _, lip, _ = read_vmd(a.lip)
        merge_lip(morphs, lip)
    if a.end is not None:
        cut(bones, morphs, a.end)
    dropped_b = sorted(n for n in bones if n not in pmd_bones and not is_still(bones[n]))
    dropped_m = sorted(n for n in morphs if n not in pmd_morphs and len(morphs[n]) > 1)
    bones = {n: k for n, k in bones.items() if n in pmd_bones}
    morphs = {n: k for n, k in morphs.items() if n in pmd_morphs}
    print(f"dropped moving bones the model lacks: {dropped_b}")
    print(f"dropped moving morphs the model lacks: {dropped_m}")
    write_vmd(a.out, "初音ミク", bones, morphs, rest)
    last = max(k[-1][0] for k in list(bones.values()) + list(morphs.values()))
    print(f"wrote {a.out}: {sum(map(len, bones.values()))} bone keys, "
          f"{sum(map(len, morphs.values()))} morph keys, last frame {last}")


if __name__ == "__main__":
    main()
