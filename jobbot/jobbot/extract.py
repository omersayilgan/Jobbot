"""Reads the documents in a folder and turns them into structured facts.

Deliberately offline and dependency-light: text comes out of PDFs with
`pdftotext` (poppler-utils) or `pypdf` if it happens to be installed, out of
.docx by unzipping the XML, and out of .txt/.md directly. Nothing is sent
anywhere.

The parsers are heuristic by design. They are wrong sometimes, which is why
`setup.py` writes everything it inferred into profiles/<you>/profile.yaml as
plain editable text and prints a confidence line for each field. Correct it
there and re-run with --from-facts; nothing has to be re-parsed.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field

TEXT_EXT = {".txt", ".md", ".markdown", ".text"}
DOC_EXT = {".pdf", ".docx"} | TEXT_EXT

# ---------------------------------------------------------------- text loading


def _pdf_text(path: str) -> str:
    if shutil.which("pdftotext"):
        try:
            out = subprocess.run(["pdftotext", "-layout", path, "-"],
                                 capture_output=True, timeout=90)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.decode("utf-8", "replace")
        except (subprocess.SubprocessError, OSError):
            pass
    try:                                   # optional, only if the user has it
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    except Exception:
        return ""


def _docx_text(path: str) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "    ", xml)
    return re.sub(r"<[^>]+>", "", xml)


def read_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _pdf_text(path)
    if ext == ".docx":
        return _docx_text(path)
    if ext in TEXT_EXT:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return ""


# ---------------------------------------------------------------- classification

CV_MARKERS = ("curriculum vitae", "resume", "résumé", "lebenslauf", "work experience",
              "professional experience", "berufserfahrung", "employment history",
              "career summary", "work history")
TRANSCRIPT_MARKERS = ("transcript", "leistungsnachweis", "notenspiegel", "grade report",
                      "academic record", "diploma supplement", "notenübersicht",
                      "studienverlauf", "cumgpa", "grade point average", "ects")
CERT_MARKERS = ("zertifikat", "certificate", "certification", "goethe", "telc", "ielts",
                "toefl", "urkunde", "bescheinigung", "attestation", "diploma")
LETTER_MARKERS = ("reference letter", "letter of recommendation", "empfehlungsschreiben",
                  "arbeitszeugnis", "to whom it may concern", "referenzschreiben")


def classify(path: str, text: str) -> str:
    """cv | transcript | certificate | reference | other."""
    name = os.path.basename(path).lower()
    head = text[:4000].lower()
    body = text.lower()

    def score(markers, weight_name=3):
        s = sum(weight_name for m in markers if m in name)
        s += sum(2 for m in markers if m in head)
        s += sum(1 for m in markers if m in body)
        return s

    scores = {
        "cv": score(CV_MARKERS) + (4 if re.search(r"\bcv\b|\blebenslauf\b", name) else 0),
        "transcript": score(TRANSCRIPT_MARKERS),
        "certificate": score(CERT_MARKERS),
        "reference": score(LETTER_MARKERS),
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 3 else "other"


@dataclass
class Document:
    path: str
    kind: str
    text: str

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


def find_documents(folders: list[str]) -> list[Document]:
    """Read every supported document in the given folders (non-recursive)."""
    docs: list[Document] = []
    seen: set[str] = set()
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for entry in sorted(os.listdir(folder)):
            path = os.path.join(folder, entry)
            real = os.path.realpath(path)
            if not os.path.isfile(path) or real in seen:
                continue
            if os.path.splitext(entry)[1].lower() not in DOC_EXT:
                continue
            text = read_text(path)
            if len(text.strip()) < 60:
                # A scanned certificate carries no text to analyse but is still
                # an attachment worth sending, so classify it by filename.
                kind = classify(path, "")
                docs.append(Document(path, kind if kind != "other" else "unreadable", text))
                seen.add(real)
                continue
            docs.append(Document(path, classify(path, text), text))
            seen.add(real)
    return docs


# ---------------------------------------------------------------- CV parsing

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(?<![\w])(\+\d{1,3}[\s\-./]?)?(\(?\d{1,5}\)?[\s\-./]?){1,5}\d{2,8}(?![\w])")
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
# 08/2025– 06/2026   |   2017–2023   |   Aug 2023 - May 2024   |   10/2023–Present
RANGE_RE = re.compile(
    r"(?P<s>(?:\d{1,2}[/.])?(?:19|20)\d{2})\s*[–—\-‒~]{1,2}\s*"
    r"(?P<e>(?:\d{1,2}[/.])?(?:19|20)\d{2}|present|current|heute|now|ongoing|laufend|today)",
    re.I)

SECTION_HEADS = {
    "experience": ("professional experience", "work experience", "experience", "employment",
                   "berufserfahrung", "berufliche erfahrung", "praktische erfahrung",
                   "work history", "career", "beschäftigung"),
    "education": ("education", "ausbildung", "akademischer werdegang", "studium",
                  "academic background", "qualifications", "bildung"),
    "skills": ("skills", "kenntnisse", "technical skills", "competencies", "fähigkeiten",
               "expertise", "kompetenzen", "it-kenntnisse", "tools"),
    "languages": ("languages", "sprachen", "sprachkenntnisse", "language skills"),
    "projects": ("projects", "projekte", "publications", "publikationen", "theses"),
    "interests": ("interests", "hobbies", "hobbys", "interessen", "freizeit", "sonstiges"),
}

BULLET_RE = re.compile(r"^\s*[•▪◦○●·*\-–—]\s*(.+)$")

# A very common CV layout puts dates in a narrow left column, which makes
# pdftotext split one range over two lines:
#     08/2025– Working Student — Phlair, Munich
#      06/2026 ○ Developed TwinCAT logic ...
# Rejoining them is what lets the date logic below see a range at all.
_OPEN_RANGE = re.compile(r"^\s*((?:\d{1,2}[/.])?(?:19|20)\d{2})\s*[–—\-‒]\s*(?=\S|$)")
_LEAD_DATE = re.compile(r"^\s*((?:\d{1,2}[/.])?(?:19|20)\d{2}|present|current|heute|laufend)\s+", re.I)


def _rejoin_date_columns(lines: list[str]) -> list[str]:
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        m = _OPEN_RANGE.match(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if m and not RANGE_RE.search(line):
            n = _LEAD_DATE.match(nxt)
            if n:
                rest = line[m.end():].strip()
                tail = nxt[n.end():].strip()
                out.append(f"{m.group(1)}–{n.group(1)} {rest}")
                if tail:
                    out.append("   " + tail)
                i += 2
                continue
        out.append(line)
        i += 1
    return out

LANG_NAMES = {
    "english": "English", "englisch": "English", "german": "German", "deutsch": "German",
    "french": "French", "französisch": "French", "spanish": "Spanish", "spanisch": "Spanish",
    "italian": "Italian", "italienisch": "Italian", "turkish": "Turkish", "türkisch": "Turkish",
    "russian": "Russian", "russisch": "Russian", "arabic": "Arabic", "arabisch": "Arabic",
    "chinese": "Chinese", "mandarin": "Chinese", "portuguese": "Portuguese", "dutch": "Dutch",
    "polish": "Polish", "hindi": "Hindi", "japanese": "Japanese", "korean": "Korean",
    "persian": "Persian", "farsi": "Persian", "ukrainian": "Ukrainian", "greek": "Greek",
    "czech": "Czech", "swedish": "Swedish", "danish": "Danish", "norwegian": "Norwegian",
    "romanian": "Romanian", "hungarian": "Hungarian", "urdu": "Urdu", "bengali": "Bengali",
}
CEFR_RE = re.compile(r"\b([abc][12])\b", re.I)
LEVEL_WORDS = [
    (("native", "muttersprache", "mother tongue", "first language", "bilingual"), "Native"),
    (("fluent", "fließend", "fliessend", "verhandlungssicher", "full professional",
      "proficient", "c2", "business fluent"), "C2"),
    (("advanced", "very good", "sehr gut", "professional working", "c1"), "C1"),
    (("intermediate", "good", "gut", "conversational", "b2"), "B2"),
    (("basic", "grundkenntnisse", "elementary", "b1"), "B1"),
    (("beginner", "anfänger", "a2", "a1"), "A2"),
]

DEGREE_RE = re.compile(
    r"\b(ph\.?d|doctorate|doktor|dr\.\s*-?ing|m\.?\s?sc|master|magister|mba|"
    r"b\.?\s?sc|b\.?\s?eng|b\.?\s?a\b|bachelor|diplom|staatsexamen|associate degree|"
    r"apprenticeship|ausbildung)\b", re.I)
DEGREE_RANK = {"phd": 4, "master": 3, "bachelor": 2, "vocational": 1}


@dataclass
class CVFacts:
    full_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    address: str = ""
    languages: dict = field(default_factory=dict)
    experience_bullets: list = field(default_factory=list)
    skill_lines: list = field(default_factory=list)
    education_lines: list = field(default_factory=list)
    education_bullets: list = field(default_factory=list)
    job_titles: list = field(default_factory=list)
    employers: list = field(default_factory=list)
    degrees: list = field(default_factory=list)
    highest_degree: str = ""
    years_experience: float = 0.0
    is_student: bool = False
    all_text: str = ""


def _sections(lines: list[str]) -> dict[str, list[str]]:
    """Split CV lines into named sections by their headings."""
    out: dict[str, list[str]] = {k: [] for k in SECTION_HEADS}
    out["header"] = []
    current = "header"
    for raw in lines:
        line = raw.strip()
        probe = re.sub(r"[^a-zäöüß ]", "", line.lower()).strip()
        if line and len(line) < 60:
            for sec, heads in SECTION_HEADS.items():
                if probe in heads or any(probe == h for h in heads):
                    current = sec
                    break
            else:
                # A heading may carry trailing decoration ("Skills ———").
                for sec, heads in SECTION_HEADS.items():
                    if any(probe.startswith(h) and len(probe) <= len(h) + 3 for h in heads):
                        current = sec
                        break
                else:
                    out[current].append(raw)
                    continue
            continue
        out[current].append(raw)
    return out


# CVs love to decorate the name line: "Marco Rossi — Curriculum Vitae".
_CV_WORDS = re.compile(
    r"\s*[-–—|:]?\s*\b(curriculum\s+vitae|curriculum|vitae|r[eé]sum[eé]|resume|"
    r"lebenslauf|cv)\b\s*[-–—|:]?\s*", re.I)


def _guess_name(lines: list[str], email: str, places: set[str] | None = None) -> str:
    bad = ("phone", "email", "address", "profile", "contact", "www", "http", "@",
           "linkedin", "github", "date of birth", "nationality")
    places = places or set()
    for raw in lines[:14]:
        line = re.sub(r"\s{2,}.*$", "", raw).strip()      # drop a right-hand column
        line = _CV_WORDS.sub(" ", line).strip(" ,|·-–—")
        low = line.lower()
        if not (3 < len(line) < 50) or any(b in low for b in bad):
            continue
        # A city or country on its own line is an address, not a person.
        if places and any(part.strip().lower() in places
                          for part in re.split(r"[,/|]", low) if part.strip()):
            continue
        if re.search(r"\d", line):
            continue
        words = line.replace(",", " ").split()
        if not (2 <= len(words) <= 4):
            continue
        if all(w[:1].isupper() or not w[:1].isalpha() for w in words):
            return line.strip(" ,|·-")
    if email:                                   # last resort: build it from the address
        stem = re.split(r"[._\-0-9]+", email.split("@")[0])
        parts = [p.capitalize() for p in stem if len(p) > 1]
        if parts:
            return " ".join(parts[:3])
    return ""


def _languages(text: str, lang_section: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    hay = "\n".join(lang_section) if lang_section else text
    for line in hay.split("\n"):
        low = line.lower()
        names = [LANG_NAMES[k] for k in LANG_NAMES if re.search(rf"\b{k}\b", low)]
        if not names:
            continue
        level = ""
        cefr = CEFR_RE.search(low)
        if cefr:
            level = cefr.group(1).upper()
        else:
            for words, lab in LEVEL_WORDS:
                if any(w in low for w in words):
                    level = lab
                    break
        for n in names:
            if n not in found or (not found[n] and level):
                found[n] = level or "unspecified"
    return found


def _years_experience(exp_lines: list[str]) -> tuple[float, bool]:
    """Total professional months from the date ranges in the experience section."""
    this_year = _dt.date.today().year
    this_month = _dt.date.today().month
    spans: list[tuple[float, float]] = []
    ongoing = False

    def as_point(tok: str) -> float:
        tok = tok.strip().lower()
        if tok in ("present", "current", "heute", "now", "ongoing", "laufend", "today"):
            nonlocal ongoing
            ongoing = True
            return this_year + this_month / 12.0
        m = re.match(r"(?:(\d{1,2})[/.])?((?:19|20)\d{2})", tok)
        if not m:
            return 0.0
        month = int(m.group(1) or 1)
        return int(m.group(2)) + min(max(month, 1), 12) / 12.0

    for line in exp_lines:
        for m in RANGE_RE.finditer(line):
            a, b = as_point(m.group("s")), as_point(m.group("e"))
            if a and b and b >= a and (b - a) < 25:
                spans.append((a, b))
    if not spans:
        return 0.0, False

    spans.sort()                        # merge overlaps: parallel jobs are not double time
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= merged[-1][1] + 0.1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return round(sum(b - a for a, b in merged), 1), ongoing


def _job_titles(exp_lines: list[str]) -> tuple[list[str], list[str]]:
    """Entry headings look like 'Control Systems Engineer, Roketsan Inc., Ankara'."""
    titles, employers = [], []
    for line in exp_lines:
        text = line.strip()
        if not text or BULLET_RE.match(line) or not RANGE_RE.search(text):
            continue
        text = RANGE_RE.sub("", text).strip(" ,–—-|")
        text = re.sub(r"^[\s•▪◦○●·*\-–—]+", "", text)
        text = re.sub(r"^\s*\d{1,2}[/.]\d{4}\s*", "", text)
        if not (6 < len(text) < 130):
            continue
        parts = [p.strip() for p in re.split(r"\s[–—|]\s|,\s|\sat\s|\sbei\s", text) if p.strip()]
        if not parts:
            continue
        head = parts[0]
        if len(head) < 4 or head.lower().startswith(("http", "www")):
            continue
        if re.search(r"\d{4}", head):
            continue
        titles.append(head)
        if len(parts) > 1:
            employers.append(parts[1])
    return titles[:12], employers[:12]


def _collect_bullets(lines: list[str], min_len: int) -> list[str]:
    """Bullets, rejoined across the line breaks pdftotext introduces.

    A wrapped bullet continues on the next line with no marker of its own, so
    without this every long bullet is truncated mid-sentence — and a cover
    letter built from truncated bullets reads like a bug, because it is one.
    """
    out: list[str] = []
    buf = ""

    def flush():
        nonlocal buf
        text = re.sub(r"\s{2,}", " ", buf).strip()
        if len(text) >= min_len:
            out.append(text)
        buf = ""

    for raw in lines:
        m = BULLET_RE.match(raw)
        if m:
            flush()
            buf = m.group(1).strip()
            continue
        line = raw.strip()
        if not buf:
            continue
        # A blank line, a new dated entry, or a heading ends the bullet.
        if not line or RANGE_RE.search(line) or (len(line) < 40 and line.endswith(":")):
            flush()
            continue
        # A trailing hyphen is kept: in a CV it is far more often a real
        # compound ("Hardware-in-the-Loop", "Model-Based") than a soft wrap.
        buf = buf + line if buf.endswith("-") else f"{buf} {line}"
    flush()
    return out


def parse_cv(text: str, places: set[str] | None = None) -> CVFacts:
    f = CVFacts(all_text=text)
    lines = _rejoin_date_columns(text.split("\n"))
    sec = _sections(lines)

    m = EMAIL_RE.search(text)
    f.email = m.group(0) if m else ""
    for cand in PHONE_RE.finditer(text[:2500]):
        digits = re.sub(r"\D", "", cand.group(0))
        if 8 <= len(digits) <= 15:
            f.phone = re.sub(r"\s{2,}", " ", cand.group(0).strip())
            break
    f.full_name = _guess_name(lines, f.email, places)

    f.languages = _languages(text, sec["languages"])
    exp = sec["experience"]
    f.years_experience, ongoing = _years_experience(exp)
    f.job_titles, f.employers = _job_titles(exp)

    f.experience_bullets = _collect_bullets(exp + sec["projects"], 25)
    if not f.experience_bullets:            # some CVs use plain indented prose
        for line in exp:
            s = re.sub(r"\s{2,}", " ", line.strip())
            if len(s) > 45 and not RANGE_RE.search(s):
                f.experience_bullets.append(s)

    for line in sec["skills"]:
        s = re.sub(r"\s{2,}", " ", line.strip())
        if len(s) > 3:
            f.skill_lines.append(s)

    f.education_lines = [re.sub(r"\s{2,}", " ", l.strip())
                         for l in sec["education"] if l.strip()]
    # Thesis titles and specialisation lists live here and are strong evidence.
    f.education_bullets = _collect_bullets(sec["education"], 20)
    edu_blob = "\n".join(f.education_lines) or text
    ranks = []
    for d in DEGREE_RE.finditer(edu_blob):
        tok = d.group(1).lower().replace(".", "").replace(" ", "")
        f.degrees.append(d.group(1))
        if tok in ("phd", "doctorate", "doktor", "dring"):
            ranks.append("phd")
        elif tok in ("msc", "master", "magister", "mba", "diplom", "staatsexamen"):
            ranks.append("master")
        elif tok in ("bsc", "beng", "ba", "bachelor", "associatedegree"):
            ranks.append("bachelor")
        else:
            ranks.append("vocational")
    f.highest_degree = max(ranks, key=lambda r: DEGREE_RANK[r]) if ranks else ""

    low = text.lower()
    f.is_student = bool(
        re.search(r"\b(student|studierend|thesis ongoing|ongoing thesis|in progress|"
                  r"expected graduation|voraussichtlicher abschluss|working student|werkstudent|"
                  r"currently (?:studying|completing|pursuing))\b", low)
        or (ongoing and re.search(r"present", "\n".join(sec["education"]), re.I)))

    # Address: the header block line that carries a street or postcode.
    for line in sec["header"][:20]:
        s = re.sub(r"\s{2,}", " ", line.strip())
        if re.search(r"(?:stra(?:ße|sse)|str\.|\bstreet\b|\broad\b|\bave\b|\bweg\b|"
                     r"\bplatz\b|\bgasse\b|\ballee\b)", s, re.I) \
                or re.search(r"\b\d{4,5}\s+[A-ZÄÖÜ]", s):
            f.address = s
            break
    return f


# ---------------------------------------------------------------- transcript parsing

@dataclass
class Course:
    name: str
    grade: str
    performance: float
    credits: float = 0.0


@dataclass
class TranscriptFacts:
    scale: str = ""
    scale_label: str = ""
    courses: list = field(default_factory=list)
    institution: str = ""
    program: str = ""
    overall: str = ""
    all_text: str = ""


def detect_scale(text: str, scales: dict) -> str:
    low = text.lower()
    best, best_hits = "", 0
    for key, spec in scales.items():
        hits = sum(1 for m in spec.get("markers", []) if m in low)
        if hits > best_hits:
            best, best_hits = key, hits
    return best


def _course_name(raw: str) -> str:
    """Strip module codes, credits and grades, leaving the subject name."""
    s = raw.strip()
    s = re.sub(r"^\s*[A-ZÄÖÜ]{2,6}\s?\d{2,5}[A-Z]?\b", "", s)      # METU MATH119, TUM MW1420
    s = re.sub(r"^\s*[A-Z]{2}\d{6,8}\b", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"[\d.,()*\[\]/%|\s]{2,}$", "", s)
    s = re.sub(r"\s*\((?:NI|W|EX|S)\)\s*", " ", s)
    return s.strip(" .,-–—\t")


def parse_transcript(text: str, scales: dict, non_courses: list[str]) -> TranscriptFacts:
    t = TranscriptFacts(all_text=text)
    t.scale = detect_scale(text, scales)
    if not t.scale:
        return t
    spec = scales[t.scale]
    t.scale_label = spec.get("label", t.scale)
    values = {str(k).upper(): v for k, v in (spec.get("values") or {}).items()}
    ignore = {str(x).upper() for x in (spec.get("ignore") or [])}
    rng = spec.get("numeric_range")
    grade_re = re.compile(spec["pattern"], 0 if rng else re.I)

    for m in re.finditer(r"(?:degree program|studiengang|department/?\s*program)\b[:\s]*(.*)",
                         text, re.I):
        for cand in [m.group(1)] + text[m.end():m.end() + 200].split("\n")[1:3]:
            cand = re.sub(r"\s{2,}.*$", "", cand).strip(" :/-")
            if len(cand) > 3 and re.search(r"[a-zäöü]{4}", cand, re.I) \
                    and not re.search(r"course code|degree|program|abschluss", cand, re.I):
                t.program = cand[:80]
                break
        if t.program:
            break
    m = re.search(r"(technische universität[^\n]*|university[^\n]*|universität[^\n]*|"
                  r"hochschule[^\n]*|institute of technology[^\n]*)", text, re.I)
    if m:
        t.institution = re.sub(r"\s{2,}.*$", "", m.group(1)).strip()[:80]

    seen: set[tuple[str, str]] = set()
    for raw in text.split("\n"):
        line = raw.rstrip()
        if len(line.strip()) < 8:
            continue
        low = line.lower()
        if any(nc in low for nc in non_courses):
            continue

        tokens = grade_re.findall(line)
        if not tokens:
            continue
        tokens = [tok if isinstance(tok, str) else next(x for x in tok if x) for tok in tokens]

        grade, perf, raw_tok = "", None, ""
        if rng:
            lo, hi = rng
            nums = [float(x.replace(",", ".")) for x in tokens]
            nums = [n for n in nums if lo <= n <= hi]
            if not nums:
                continue
            grade = f"{nums[-1]:g}"
            raw_tok = tokens[-1]
            perf = (nums[-1] - lo) / float(hi - lo)
        else:
            for tok in tokens:
                key = tok.upper().replace(",", ".")
                if key in ignore:
                    continue
                if key in values:
                    grade, perf, raw_tok = key, values[key], tok
                    break
        if perf is None or not grade:
            continue

        cut = line.find(raw_tok) if raw_tok and raw_tok in line else -1
        name = _course_name(line[:cut] if cut > 0 else line)
        if len(name) < 4 or not re.search(r"[a-zA-ZäöüÄÖÜ]{4}", name):
            continue
        if re.fullmatch(r"[\d\s.,/%-]+", name):
            continue

        credits = 0.0
        tail = line[line.rfind(raw_tok) + len(raw_tok):] if raw_tok else ""
        cm = re.findall(r"\b(\d{1,2}(?:[.,]\d{1,2})?)\b", tail)
        if cm:
            cand = float(cm[-1].replace(",", "."))
            if 0.5 <= cand <= 40:
                credits = cand

        key = (name.lower()[:48], grade)
        if key in seen:
            continue
        seen.add(key)
        t.courses.append(Course(name=name, grade=grade, performance=round(perf, 3),
                                credits=credits))

    m = re.search(r"(?:cumgpa|cumulative gpa|gpa|zwischennote|gesamtnote|final grade)"
                  r"[:\s]*([0-9][.,][0-9]{1,2})", text, re.I)
    if m:
        t.overall = m.group(1).replace(",", ".")
    return t
