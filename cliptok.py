"""The text tokenizer Stable Diffusion's text encoder expects (CLIP's byte-level BPE), in plain Python so the
drawer needs nothing big installed. Reads the model's own vocab.json and merges.txt."""

import functools
import html
import json
import re


@functools.lru_cache()
def _bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, map(chr, cs)))


def _pairs(word):
    return {(a, b) for a, b in zip(word, word[1:])}


def _clean(text):
    text = html.unescape(html.unescape(text))
    return re.sub(r"\s+", " ", text).strip().lower()


class ClipTokenizer:
    START, END = "<|startoftext|>", "<|endoftext|>"

    def __init__(self, vocab_path, merges_path):
        with open(vocab_path, encoding="utf-8") as f:
            self.encoder = json.load(f)
        with open(merges_path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        merges = [tuple(line.split()) for line in lines[1:] if line.strip() and not line.startswith("#version")]
        self.ranks = {m: i for i, m in enumerate(merges) if len(m) == 2}
        self.byte_encoder = _bytes_to_unicode()
        self.cache = {self.START: self.START, self.END: self.END}
        self.pat = re.compile(r"<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|[^\W\d_]+|\d|[^\s\w]+",
                              re.IGNORECASE)

    def _bpe(self, token):
        if token in self.cache:
            return self.cache[token]
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        pairs = _pairs(word)
        if not pairs:
            return token + "</w>"
        while True:
            bigram = min(pairs, key=lambda p: self.ranks.get(p, float("inf")))
            if bigram not in self.ranks:
                break
            first, second = bigram
            new, i = [], 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                except ValueError:
                    new.extend(word[i:])
                    break
                new.extend(word[i:j])
                i = j
                if word[i] == first and i < len(word) - 1 and word[i + 1] == second:
                    new.append(first + second)
                    i += 2
                else:
                    new.append(word[i])
                    i += 1
            word = tuple(new)
            if len(word) == 1:
                break
            pairs = _pairs(word)
        out = " ".join(word)
        self.cache[token] = out
        return out

    def encode(self, text, length=77):
        """Token ids padded (with the end token) or cut to length, start and end tokens included."""
        ids = []
        for token in self.pat.findall(_clean(text)):
            token = "".join(self.byte_encoder[b] for b in token.encode("utf-8"))
            ids += [self.encoder[t] for t in self._bpe(token).split(" ") if t in self.encoder]
        start, end = self.encoder[self.START], self.encoder[self.END]
        ids = [start] + ids[: length - 2] + [end]
        return ids + [end] * (length - len(ids))
