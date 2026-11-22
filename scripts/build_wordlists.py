"""Build app/seed/lessons/L<n>.csv from the compact app/seed/lessons/_source.txt."""
import csv
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "app" / "seed" / "lessons"
COLS = ["lemma", "pos", "article", "plural", "aux", "partizip2", "gloss_es", "gloss_en"]


def parse(line: str) -> dict:
    head, es, en = (p.strip() for p in line.split("|"))
    kind, rest = head.split(" ", 1)
    row = dict.fromkeys(COLS, "")
    row.update(gloss_es=es, gloss_en=en)
    if kind == "N":
        art, lemma, plural = rest.split(" ")
        row.update(pos="NOUN", article=art, lemma=lemma, plural=plural)
    elif kind == "V":
        lemma, aux, p2 = rest.split(" ")
        row.update(pos="VERB", lemma=lemma, aux=aux, partizip2=p2)
    elif kind == "X":
        pos, lemma = rest.split(" ", 1)
        row.update(pos=pos, lemma=lemma)
    else:
        raise ValueError(line)
    return row


def main() -> None:
    lessons: dict[int, list[dict]] = {}
    seen: set[tuple] = set()
    current = None
    for raw in (SEED / "_source.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            current = int(line[1:])
            lessons[current] = []
            continue
        row = parse(line)
        key = (row["lemma"], row["pos"], row["article"])
        if key in seen:  # first lesson that introduces a word owns it
            continue
        seen.add(key)
        lessons[current].append(row)
    for n, rows in lessons.items():
        with open(SEED / f"L{n:02d}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)
        print(f"L{n:02d}: {len(rows)} words")


if __name__ == "__main__":
    main()
