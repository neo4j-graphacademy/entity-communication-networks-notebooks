"""Enron-specific email header extraction using data-driven templates.

Built from corpus analysis of the Enron email archive (5,000 PDFs).
Handles the specific OCR corruption, boilerplate patterns, and layout
variants found in this dataset.

Key differences from the Clinton template system:
- `Ce:` is a common OCR variant of `Cc:` in Enron PDFs
- `Subject :` (space before colon) is very common
- Exchange DN lines (</O=ENRON/...>) appear as continuation lines after From/To values
- Date values are often split across multiple lines by OCR
- `Sent:` field is sometimes absent (replaced by bare timestamps in forwarded sections)
- From line may be preceded by more than 20 lines of boilerplate
- Many OCR typos in field labels: Fro:, Froi:, Fiom:, Brom:, etc.
- Junk OCR lines (standalone '.', ':', numbers, truncated words) appear between
  structural elements and must be skipped

Usage:
    from helpers.enron_templates import extract_enron_headers

    result = extract_enron_headers(text)
    if result:
        template = result.pop('_template')
        body_idx = result.pop('_body_start_idx')
        # result now has from/sent/to/cc/subject keys
"""

import re
from enum import Enum, auto


# =====================================================================
# LINE ROLES
# =====================================================================

class Role(Enum):
    """Role that a line plays in a header template."""
    LABEL = auto()        # Header label only (e.g., "From:")
    VALUE = auto()        # Non-label value line
    LABEL_VALUE = auto()  # Label + value on same line
    BODY = auto()         # First body line (extraction stops)


# Shorthand aliases for template definitions
L = Role.LABEL
V = Role.VALUE
LV = Role.LABEL_VALUE
B = Role.BODY


# =====================================================================
# BOILERPLATE STRIPPING
# =====================================================================

# Enron-specific boilerplate patterns (more extensive than Clinton set)
_ENRON_BOILERPLATE = [
    # Standard case/doc header lines
    r"^Case\s*['\u2018\u2019]?\s*No[,\.]",
    r"^Case[,\s']+No",
    r"^Doc[,\s']*No[,\.]",
    r"^Doc\s*['\u2018\u2019]?\s*No",
    r"^Doe\s*No",
    r"^Dot\s*No",
    r"^Dac\s*No",
    r"^Bac\s*No",
    r"^bet\s*No",
    r"^Dog\s*No",
    r"^Dac\s*['\u2018\u2019]?\s*No",
    r"^[A-Za-z]?Doc\s*No",
    r"^[EéE]nron[-\s]*\d{10}",  # ENRON-1087718677110
    r"^EC-2002",
    # Confidentiality notices (including OCR typos)
    r"^'?CONFIDENTIAL",
    r"^GONFIDENTIAL",
    r"^GONEIDENTIAL",
    r"^CONFIDENTIAE",
    r"^CONFIDENFIAL",
    r"^CONE\s*IDENTIAL",
    r"^CONF[.\s]*IDENTIAL",
    r"^'?UNCLASSIFIED",
    # Enron corp header (many OCR variants)
    r"^Enron\s*Corp\.\s*$",
    r"^Enroh\s*Corp",
    r"^Eriron\s*Corp",
    r"^Enrén\s*Corp",
    r"^Enrop\s*Corp",
    r"^Bmron\s*Corp",
    r"^Enion\s*Corp",
    r"^ENRON\s*COR.\.",  # "ENRON CORP." / "ENRON CORE." but not "Enron Corp Business"
    r"^ENROW\s*CORP",
    # Protective order notices
    r"^SUBJECT\s*[',\-\*]+\s*TO\s*PROTECTIVE",
    r"^SUBJECT\s*TO\s*PROTECTIVE",
    r"^stIBJECT\s*TO",
    r"^SUBJECT['\s]+TO",
    r"^\s*TO\s*PROTECTIVE",
    # Release notices
    r"^RELEASE\s*[,\s]*IN\s*(FULL|PART)",
    r"^RELEASE\s*$",
    r"^IN\s+(FULL|PART)",
    r"^PRODUCED\s*PURSUANT",
    r"^[-~\s]*PRODUCED\s*PURSUANT",
    r"^PURSUANT\s*TO\s*FERC",
    r"^.*FERC\s*SUBPOENA",
    r"^FERC\s*SUBPOENA",
    r"^\s*-?\s*FERC\s*$",
    r"^\s*SUBPOENA[.\s]*$",
    r"^\s*-?TQ?\s*FERC\s*$",
    r"^\s*TO[\s.]*FERC\s*$",
    # Date header lines (boilerplate date stamp, NOT email Sent: date)
    r"^Pate[r]?\s*:",
    r"^bate[ri]?\s*:",
    r"^Date:?\s*[,.\s]*\d",
    r"^Date:?\s*[,.\s]*['\"]\d",
    r"^Dates[,\s]*\d",
    # Lone separators / OCR junk lines
    r"^[-=~*+°•\|]+\s*$",
    r"^[;:,.<>\|]+\s*$",
    r"^['\u2018\u2019\u201c\u201d\u00b0]\s*$",
    # Bare single letters or numbers (OCR fragmentation)
    r"^[a-zA-Z\d]\s*$",
    r"^[a-zA-Z\d][.,;]\s*$",
    # ~-PRODUCED or - PRODUCED lines
    r"^~\s*PRODUCED",
    r"^\s*=\s*PRODUCED",
    # Specific known boilerplate phrases
    r"^mo\s*,?\s*$",
    r"^[A-Z]{2,}-\d{4,}",  # EC-2002-01038 already covered but catch variants
]

_BOILERPLATE_RE = re.compile(
    '|'.join(f'(?:{p})' for p in _ENRON_BOILERPLATE),
    re.IGNORECASE,
)


def strip_enron_boilerplate(text):
    """Strip Enron-specific boilerplate lines from extracted PDF text.

    Removes case/doc headers, confidentiality notices, FERC subpoena
    notices, release markers, and OCR-fragmented junk lines.
    """
    lines = text.split('\n')
    cleaned = [
        line for line in lines
        if not _BOILERPLATE_RE.match(line.strip())
    ]
    return '\n'.join(cleaned).strip()


# =====================================================================
# REGEX CONSTANTS
# =====================================================================

# Date patterns — covers Enron archive date formats including OCR corruptions
# Day name OCR variants seen in corpus:
#   Priday/Eriday (Friday), Mohday/Moriday/Manday (Monday),
#   Tiiesday/Thesday/fuesday (Tuesday/Thursday), Tuésday (Tuesday),
#   Wédnesday (Wednesday)
_DATE_RE = re.compile(
    r'(?:'
    # Standard day names
    r'Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?'
    r'|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?'
    # OCR-corrupted full day names (1-2 char substitutions)
    r'|P[ri]{1,2}day|Er[i]?day'           # Priday, Eriday → Friday
    r'|Mo[hn]day|Mor[i]day|Man[d]?ay'     # Mohday, Moriday, Manday → Monday
    r'|T[ui][ui]?esday|T[h]esday'         # Tiiesday, Thesday → Tuesday/Thursday
    r'|[Tt]u[eé]sday'                     # Tuésday → Tuesday
    r'|W[eé]d[n]?esday'                   # Wédnesday → Wednesday
    # OCR-corrupted 3-letter abbreviations (RFC date format: "Tue, 7 Aug 2001")
    r'|Mo[enr]|Men'                        # Moen, Mor, Men → Mon
    r'|Tu[ce]'                             # Tuc → Tue
    r'|We[eda]'                            # Wee, Wea → Wed
    r'|T[hn]u'                             # Tnu → Thu
    r'|Fr[iy]'                             # Fry → Fri
    # Numeric date formats
    r'|\d{1,2}/\d{1,2}/\d{2,4}'
    r'|\d{1,2}-\d{1,2}-\d{2,4}'
    r')',
    re.IGNORECASE,
)

# Email address pattern
_EMAIL_RE = re.compile(r'[\w.+\-]+@[\w.\-]+\.[\w]+')

# Exchange DN pattern (common in Enron PDFs): </O=ENRON/OU=NA/...>
# These appear as continuation lines after a From/To value.
# Variants seen in corpus:
#   </O=ENRON/...>       (standard)
#   </0=ENRON/...>       (zero instead of O)
#   </OENRON/...>        (missing =)
#   <IMCEANOTES-...>     (Notes address encoding)
#   ADMINISTRATION>      (wrapped DN tail — no leading <, ends with >)
#   TENTS /CN=...>       (wrapped mid-DN fragment)
# The wrapped-tail pattern: line contains /CN= and ends with >
_EXCHANGE_DN_RE = re.compile(
    r'^[<\s]*/?\s*[O0]=(?:ENRON|BNRON|[A-Z]RON)'
    r'|^<IMCEANOTES'
    r'|^\[mailto:IMCEANOTES'   # [mailto:IMCEANOTES-...] variant (OCR bracket instead of <)
    r'|^\[mailto:'             # Any [mailto:...] reference line
    r'|^</\s*[O0]='
    r'|^</\s*ENRON'
    r'|^\s*<[^>]*/CN='
    r'|^\s*\$\/[O0]=ENRON'
    # Wrapped DN tail: no < prefix, contains /CN= or ends with >, looks like routing
    r'|^[A-Z/][A-Z\s/=\-+_.>]*\/CN=[A-Z0-9]'
    # Exchange routing continuation: starts with /OU= or /CN= without <
    r'|^\s*/[O0]U='
    r'|^\s*/CN='
    # Short all-caps or routing fragment ending with > (e.g. "ADMINISTRATION>", "TENTS /CN=X>")
    # Require: 5+ chars, no lowercase, ends with >. or >.
    # Must have multiple chars to avoid matching single names like "Mark>"
    r'|^[A-Z0-9 _/\-+=.]{5,}>[. ]*$'
    # Junk-prefix variants: '. </O=ENRON/...>' or "' </O=ENRON/...>" or '° </O=...'
    # Also: '"</O=', '*/O=', ', </O=', 'q </O=' — OCR inserts single chars before DN
    # Broadly: up to 3 junk chars (non-alpha or single alpha) before the DN start
    r"|^['\u2018\u2019\u201c\u201d\.\s°:|\\*\-,\"q~`]+\s*</?\s*[O0Q]="
    # '</OSENRON': missing '=' between '</' and 'O', so 'O' merges with 'S'
    # e.g. "'</OSENRON/..." — smart-quote + </OSENRON
    r"|^['\u2018\u2019\u201c\u201d\.\s°:|\\*\-,\"]*</?\s*(?:OSENRON|0SENRON)"
    # '*/' prefix before O=ENRON (asterisk-slash prefix)
    r"|^\*/?[O0]="
    # ADMINISTRATION> / PIRO> — DN tail fragments that appear on their own line
    # These routing domain tails appear with a closing > followed by optional OCR junk
    # e.g. "ADMINISTRATION> : °", "PIRO> "
    r"|^(?:ADMINISTRATION|RECIPIENTS|RECIP\s*IENTS|EXTERNAL|ECT|PIRO)\s*>.*$"
    # Also standalone ADMINISTRATION (without >) — common Exchange routing artifact
    r"|^ADMINISTRATION\s*$",
    re.IGNORECASE,
)

# OCR junk line — no letters or digits, or just a lone token
_JUNK_LINE_RE = re.compile(r'^[^a-zA-Z0-9]*$')

# Bare digit-only or short-token lines (OCR fragmentation artifacts)
_OCR_FRAG_RE = re.compile(r'^[\d\s.,;:!\'\u2018\u2019-]{1,4}$')

# Bare FOIA redaction code
_BARE_BCODE_RE = re.compile(r'^B[1-7](\([A-Z]\))?$')

# Full-date-start (subject validation — off-by-one detection)
_FULL_DATE_START = re.compile(
    r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,'
    r'|^\d{1,2}/\d{1,2}/\d{2,4}',
    re.IGNORECASE,
)

# OCR prefix junk (bullet, smart quotes, dots, etc.)
# Includes '.' and '°' which OCR sometimes prepends to field labels
_P = r'[\s\u2022\u2019\u2018\'\u00b7=\-\+\*\|\.\°]*'

# -----------------------------------------------------------------------
# LABEL PATTERNS
# Enron additions: Ce: (OCR for Cc:), Subject : (space before colon),
# Date: (alias for Sent:), Tao:/Tso: OCR variants of To:
# -----------------------------------------------------------------------
_LABEL_PATTERNS = {
    'from': re.compile(
        rf'^{_P}(?:From|Fro|Froi|Fiom|Brom|Frot|from)\s*[i!:;]?\s*[\t ]*$',
        re.IGNORECASE,
    ),
    'sent': re.compile(
        rf"^{_P}(?:Sent|Sant|S[eé]nt|\"Sent|Serit|Sen['\u2018\u2019]?t?)\s*[.:;]?\s*[\t ]*$",
        re.IGNORECASE,
    ),
    'to': re.compile(
        # To: and common OCR variants incl. bare '| To:' (pipe-prefixed)
        # Tv/Ta/Te/Ze/Te: OCR substitutions; To?: question-mark separator
        # _ To: — underscore prefix handled by _P
        rf'^{_P}(?:\|?\s*To|Tut|Tao|Tor|Tso|Too|fo|Tv|Ta|Te|Ze)\s*[.:;!?]?\s*[\t ]*$',
        re.IGNORECASE,
    ),
    'cc': re.compile(
        # Ce: is the most common OCR variant of Cc: in Enron PDFs
        # Also: Cea:, Co:, ccs:, cc;
        rf'^{_P}(?:C[ce]a?|ccs?|co)\s*[.:;]?\s*[\t ]*$',
        re.IGNORECASE,
    ),
    'subject': re.compile(
        # Subject: and OCR variants; also Stibject: (seen in corpus)
        rf'^{_P}(?:Subject|Subjoct|Subjact|Stibject|Subje)\s*[.:;*»]?\s*[\t ]*$',
        re.IGNORECASE,
    ),
    'attachments': re.compile(
        rf'^{_P}Attachments?\s*[.:;]?\s*[\t ]*$',
        re.IGNORECASE,
    ),
}

# Any recognized header label (for VALUE role rejection)
_ANY_LABEL_RE = re.compile(
    rf'^{_P}(?:From|Fro|Froi|Fiom|Brom|Frot'
    rf"|Sent|Sant|S[eé]nt|\"Sent|Serit|Sen['\u2018\u2019]?t?"
    rf'|\|?\s*To|Tut|Tao|Tor|Tso|Too|fo|Tv|Ta|Te|Ze'
    rf'|C[ce]a?|ccs?|co'
    rf'|Subject|Subjoct|Subjact|Stibject|Subje'
    rf'|Attachments?)'
    rf'\s*[.:;!*»]?\s*[\t ]*$',
    re.IGNORECASE,
)

# Same-line label+value extraction patterns
# Enron additions: Ce: variant, Subject : (space before colon),
# Date: as alias for Sent:
_LABEL_VALUE_PATTERNS = {
    'from': re.compile(
        # Standard: "From: Name" — colon (or OCR colon) separator
        # Extended: "From Name" — no colon, but space + name start (capital/quote)
        # "Fro Matthew :" — trailing stray colon after name is part of value
        rf'^{_P}(?:From|Fro|Froi|Fiom|Brom|Frot|from)'
        rf'\s*(?:[i!:;]\s*|\s+(?=[A-Z"\'\u201c\u2018]))(.+)',
        re.IGNORECASE,
    ),
    'sent': re.compile(
        # Also match 'Date:' as Sent: (document date = sent date)
        # 'Sent :' (space before colon), 'Sent.:' (period after label)
        # 'Sent::' (double colon), ', Sent:' (comma prefix)
        # 'Serit :' — OCR variant; 'Sent Tuesday' — no colon at all
        # 'Sen'' — truncated OCR (smart-quote replaces 't:')
        # '"Sent:' — double-quote prefix
        # Value may start with smart-quote: 'Sent: 'Tuesday...' (curly quote)
        # Pattern: optional leading junk, label, optional junk, optional colon(s), optional junk, value
        rf"^{_P}[,\"']*{_P}(?:Sent|Sant|S[eé]nt|Serit|Sen['\u2018\u2019]?t?|Date)"
        rf"\s*[.:;]?[.:;]?[\s.,|'\"\u2018\u2019\u201c\u201d\u00ab\u00bb*°|\\~\-]*"
        # Value char classes: uppercase start then non-uppercase (incl. accented chars like é),
        # OR digit start, OR quote start
        # Use re.UNICODE flag so \w matches accented chars
        rf"([A-Z\u2018\u2019\u201c\u201d][a-z\u00e0-\u00ff\u2018\u2019].+|\d.+|['\"\u2018\u2019\u201c\u201d].+)",
        re.IGNORECASE,
    ),
    'to': re.compile(
        # 'To:' and OCR variants: 'To!', 'To;', 'To?', 'Tao:', 'Tor:', 'Ta:', 'Te:', 'Ze:', etc.
        # 'Tv:' — v/o OCR substitution
        # 'To:"' — quote after colon
        # '_ To:' / '. To:' — underscore/dot prefix handled by _P
        # Also bare 'T value' — OCR drops the 'o' and ':' entirely.
        # To avoid false positives, the bare-T pattern anchors to a name/email start.
        rf'(?:'
        rf'^{_P}(?:\|?\s*To|Tut|Tao|Tor|Tso|Too|fo|TX|Tv|Ta|Te|Ze)\s*[.:;!?]?\s*[.:;"\u2018\u2019\u201c\u201d,]?\s+(.+)'
        rf'|^{_P}T\s+([A-Z"\'\u201c\u2018<].+|[a-z]{{3,}}.+[@].+)'
        rf')',
        re.IGNORECASE,
    ),
    'cc': re.compile(
        rf'^{_P}(?:C[ce]a?|ccs?|co)\s*[.:;]\s+(.+)',
        re.IGNORECASE,
    ),
    'subject': re.compile(
        # Subject : value — space between Subject and colon is allowed
        # Also: Subje :, Stibject:, Subject *, Subject »
        rf'^{_P}(?:Subject|Subjoct|Subjact|Stibject|Subje)\s*[.:;*»]\s+(.+)',
        re.IGNORECASE,
    ),
    'attachments': re.compile(
        rf'^{_P}Attachments?\s*[.:;]\s+(.+)',
        re.IGNORECASE,
    ),
}


# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

def _is_label_for(line, field):
    """Check if a line is a label-only line for a specific field."""
    return bool(_LABEL_PATTERNS[field].match(line.strip()))


def _is_any_label(line):
    """Check if a line is any header label."""
    return bool(_ANY_LABEL_RE.match(line.strip()))


def _extract_label_value(line, field):
    """Extract value from a same-line label+value. Returns str or None."""
    m = _LABEL_VALUE_PATTERNS[field].match(line.strip())
    if m is None:
        return None
    # Some patterns have multiple groups (alternation); return first non-None
    for g in m.groups():
        if g is not None:
            return g.strip()
    return None


def _looks_like_date(text):
    """Does this text look like a date/time value?"""
    return bool(_DATE_RE.search(text))


def _looks_like_name_or_email(text):
    """Does this text look like a person name or email address?"""
    text = text.strip()
    if not text:
        return False
    if _EMAIL_RE.search(text):
        return True
    if '@' in text or '\u00a9' in text:
        return True
    if re.search(r'<[^>]+>', text):
        return True
    if re.match(r'^[A-Z][a-z]+,\s+[A-Z]', text):
        return True
    if re.match(r'^[A-Z][\w\-]+ [A-Z][a-z]', text):
        return True
    if re.match(r'^[A-Z]$', text):
        return True
    # Exchange display name format: "Lastname, Firstname <dn>" — starts with capital
    if re.match(r'^[A-Z][a-z]+,\s+[A-Z]', text):
        return True
    return False


def _is_exchange_dn(line):
    """Is this line an Exchange DN continuation (</O=ENRON/...>)?"""
    return bool(_EXCHANGE_DN_RE.match(line.strip()))


def _is_junk_line(line):
    """Is this line pure OCR junk with no useful content?"""
    s = line.strip()
    if not s:
        return True
    if _JUNK_LINE_RE.match(s):
        return True
    if _OCR_FRAG_RE.match(s):
        return True
    if _BARE_BCODE_RE.match(s):
        return True
    return False


def _is_inline_header(line):
    """Does this line look like a label+value on the same line?

    Used to stop _collect_value from consuming the next header line when
    the value is split across multiple lines.

    Examples of inline headers that should stop collection:
      'Sent: Wednesday, ...'  →  yes (new field starts here)
      'To: John Smith'         →  yes
      'Subject: Re: ...'       →  yes

    We match: known label word + optional junk + colon + space + non-empty content.
    """
    # Use existing _LABEL_VALUE_PATTERNS — if any field matches, it's an inline header
    stripped = line.strip()
    for field in ('sent', 'to', 'cc', 'subject'):
        if _extract_label_value(stripped, field) is not None:
            return True
    return False


def _fill_missing(headers):
    """Ensure all standard fields exist (empty string if missing)."""
    for field in ('from', 'sent', 'to', 'cc', 'subject'):
        if field not in headers:
            headers[field] = ''
    return headers


# =====================================================================
# FROM-LINE LOCATOR
# =====================================================================

def _find_from_line(lines):
    """Find the first From label or same-line From: value.

    Searches within the first 30 lines (extended from Clinton's 25 to
    accommodate heavier Enron boilerplate). Returns line index or None.

    Also handles OCR-prefixed variants:
    - '- From:' (dash-space prefix)
    - '| From:' (pipe prefix)
    - 'Froi:' / 'Fiom:' etc. (letter substitutions)
    """
    _from_any = re.compile(
        # Standard: "From:", "Fro:", "Froi:", leading-junk variants, dot-From
        # Extended: "From Matthew" — no colon, space + capital letter (name start)
        r'^[\s\-\.\|\*=]*(?:From|Fro|Froi|Fiom|Brom|Frot)'
        r'\s*(?:[i!:;]|(?=\s+[A-Z"\']))',
        re.IGNORECASE,
    )
    for i, line in enumerate(lines[:30]):
        stripped = line.strip()
        if not stripped:
            continue
        if _from_any.match(stripped):
            return i
    return None


# =====================================================================
# POST-MATCH VALIDATION
# =====================================================================

def _validate_extracted(extracted):
    """Validate extracted fields after template matching."""
    from_val = extracted.get('from', '')
    sent_val = extracted.get('sent', '')
    subject_val = extracted.get('subject', '')
    to_val = extracted.get('to', '')

    # SENT must look like a date (if present)
    if sent_val and not _looks_like_date(sent_val):
        return False

    # SUBJECT must NOT start with a full date (off-by-one detection)
    if subject_val and _FULL_DATE_START.search(subject_val):
        if not re.match(r'(?:RE|FW|Fwd)\s*:', subject_val, re.IGNORECASE):
            return False

    # SUBJECT must NOT contain an email address (value misalignment)
    if subject_val and _EMAIL_RE.search(subject_val):
        return False

    # SUBJECT must NOT start with embedded chain headers (shifted value)
    if subject_val and re.match(
        r'^(?:From|Fro|Sent|To|Tao)\s*:', subject_val, re.IGNORECASE,
    ):
        return False

    # TO must not start with Re:/Fw: (subject leaked into TO)
    if to_val and re.match(r'^(?:RE|FW|Fwd)\s*:', to_val, re.IGNORECASE):
        return False

    # At least one of from/sent must have content
    if not from_val and not sent_val:
        return False

    return True


# =====================================================================
# TEMPLATE DEFINITIONS
# =====================================================================
# Naming convention: SL = same-line, ALT = alternating, - = no field
# Fields: F=from S=sent T=to C=cc (Cc/Ce) X=subject A=attachments

# --- Same-line templates (LV role for each field) ---

# Standard: From/Sent/To/Cc/Subject (most common Enron same-line layout)
TEMPLATE_SL_FSTCX = {
    'name': 'sl_FStCX',
    'structure': [
        (LV, 'from'), (LV, 'sent'), (LV, 'to'),
        (LV, 'cc'), (LV, 'subject'), (B, None),
    ],
}

# Without Cc:
TEMPLATE_SL_FSTX = {
    'name': 'sl_FStX',
    'structure': [
        (LV, 'from'), (LV, 'sent'), (LV, 'to'),
        (LV, 'subject'), (B, None),
    ],
}

# Without To: (rare but seen)
TEMPLATE_SL_FSCX = {
    'name': 'sl_FsCX',
    'structure': [
        (LV, 'from'), (LV, 'sent'),
        (LV, 'cc'), (LV, 'subject'), (B, None),
    ],
}

# No Cc, no To (minimal — From/Sent/Subject only)
TEMPLATE_SL_FSX = {
    'name': 'sl_FsX',
    'structure': [
        (LV, 'from'), (LV, 'sent'), (LV, 'subject'), (B, None),
    ],
}

# --- Alternating templates (L then V for each field) ---

# Full: From/Sent/To/Cc/Subject
TEMPLATE_ALT_FSTCX = {
    'name': 'alt_FStCX',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'), (V, 'to'),
        (L, 'cc'), (V, 'cc'),
        (L, 'subject'), (V, 'subject'),
        (B, None),
    ],
}

# No Cc:
TEMPLATE_ALT_FSTX = {
    'name': 'alt_FStX',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'), (V, 'to'),
        (L, 'subject'), (V, 'subject'),
        (B, None),
    ],
}

# Cc: empty (label present, no value)
TEMPLATE_ALT_FST_CX = {
    'name': 'alt_FSt_cX',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'), (V, 'to'),
        (L, 'cc'),               # Cc label, no value
        (L, 'subject'), (V, 'subject'),
        (B, None),
    ],
}

# To: empty (label present, no value), no Cc:
TEMPLATE_ALT_FS_X = {
    'name': 'alt_Fs_X',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'),               # To label, no value
        (L, 'subject'), (V, 'subject'),
        (B, None),
    ],
}

# To: empty, Cc: has value (To empty but Cc present)
TEMPLATE_ALT_FS_CX = {
    'name': 'alt_Fs_cX',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'),               # To label, no value
        (L, 'cc'), (V, 'cc'),
        (L, 'subject'), (V, 'subject'),
        (B, None),
    ],
}

# To: empty, Cc: empty
TEMPLATE_ALT_FS__X = {
    'name': 'alt_Fs__X',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'),
        (L, 'cc'),
        (L, 'subject'), (V, 'subject'),
        (B, None),
    ],
}

# No Subject:
TEMPLATE_ALT_FST_NSUBJ = {
    'name': 'alt_FStX_noSubj',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'), (V, 'to'),
        (B, None),
    ],
}

# From/Sent/To/Cc/Subject + Attachments (less common but present)
TEMPLATE_ALT_FSTCXA = {
    'name': 'alt_FStCXA',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'), (V, 'to'),
        (L, 'cc'), (V, 'cc'),
        (L, 'subject'), (V, 'subject'),
        (L, 'attachments'), (V, 'attachments'),
        (B, None),
    ],
}

# No Cc, with Attachments
TEMPLATE_ALT_FSTXA = {
    'name': 'alt_FStXA',
    'structure': [
        (L, 'from'), (V, 'from'),
        (L, 'sent'), (V, 'sent'),
        (L, 'to'), (V, 'to'),
        (L, 'subject'), (V, 'subject'),
        (L, 'attachments'), (V, 'attachments'),
        (B, None),
    ],
}

# --- Bunched format: all labels first, then all values ---
# Common in some Enron email clients where header block is separated.
# Pattern: From:/Sent:/To:/Subject: on consecutive lines, then values follow.

TEMPLATE_BUNCH_FSTCX = {
    'name': 'bunch_FStCX',
    'structure': [
        (L, 'from'), (L, 'sent'), (L, 'to'), (L, 'cc'), (L, 'subject'),
        (V, 'from'), (V, 'sent'), (V, 'to'), (V, 'cc'), (V, 'subject'),
        (B, None),
    ],
}

TEMPLATE_BUNCH_FSTX = {
    'name': 'bunch_FStX',
    'structure': [
        (L, 'from'), (L, 'sent'), (L, 'to'), (L, 'subject'),
        (V, 'from'), (V, 'sent'), (V, 'to'), (V, 'subject'),
        (B, None),
    ],
}

TEMPLATE_BUNCH_FSX = {
    'name': 'bunch_FsX',
    'structure': [
        (L, 'from'), (L, 'sent'), (L, 'to'), (L, 'cc'), (L, 'subject'),
        (V, 'from'), (V, 'sent'), (V, 'subject'),  # to/cc empty
        (B, None),
    ],
}

# --- No-Sent templates (Sent: line absent — rare but present) ---
# Some emails (especially those with OCR at certain scan angles) lose the Sent: line.

TEMPLATE_SL_FTX_NOSENT = {
    'name': 'sl_FTX_noSent',
    'structure': [
        (LV, 'from'),
        (LV, 'to'),
        (LV, 'subject'),
        (B, None),
    ],
}

TEMPLATE_SL_FTCX_NOSENT = {
    'name': 'sl_FTcX_noSent',
    'structure': [
        (LV, 'from'),
        (LV, 'to'),
        (LV, 'cc'),
        (LV, 'subject'),
        (B, None),
    ],
}

# --- No-Subject templates (Subject: label absent OR blank) ---
# A common OCR failure: Subject label is garbled or absent.
# These are very permissive — must be tried last.

TEMPLATE_SL_FSTC_NOSUBJ = {
    'name': 'sl_FStC_noSubj',
    'structure': [
        (LV, 'from'), (LV, 'sent'), (LV, 'to'), (LV, 'cc'), (B, None),
    ],
}

TEMPLATE_SL_FST_NOSUBJ = {
    'name': 'sl_FSt_noSubj',
    'structure': [
        (LV, 'from'), (LV, 'sent'), (LV, 'to'), (B, None),
    ],
}

# --- Ordered template list (most specific first) ---
# Starting set: the three most common patterns, covering ~98.5% of the corpus.
# Students extend this list in notebook 2.4 (lesson 7) by building templates
# for the edge cases these three miss.
TEMPLATES = [
    TEMPLATE_ALT_FSTCX,     # From/Sent/To/Cc/Subject  (~25%)
    TEMPLATE_ALT_FSTX,      # From/Sent/To/Subject     (~72%)
    TEMPLATE_ALT_FS_X,      # From/Sent/To(empty)/Subject (~2%)
]


# =====================================================================
# GENERIC TEMPLATE MATCHER
# =====================================================================

# How many junk/continuation lines to tolerate between structural elements
_MAX_SKIP = 8


def _collect_value(lines, start, max_line, next_role):
    """Collect a VALUE starting at `start`.

    Returns (value_string, new_index) or (None, start) on failure.

    Handles:
    - Exchange DN continuation lines (skipped transparently, not added to value)
    - Multi-line To/Cc recipient lists (continuation lines appended)
    - Junk OCR lines between value and next label (skipped)
    - Date split across multiple lines (re-joins weekday + rest of date)
    """
    i = start

    # Skip initial junk/blank lines (up to _MAX_SKIP)
    skipped = 0
    while i < max_line and (not lines[i].strip() or _is_junk_line(lines[i])):
        i += 1
        skipped += 1
        if skipped > _MAX_SKIP:
            return None, start

    if i >= max_line:
        return None, start

    stripped = lines[i].strip()

    # Reject if this line is actually a label
    if _is_any_label(lines[i]):
        return None, start

    parts = [stripped]
    i += 1

    # Always skip Exchange DN lines immediately after the first value line
    while i < max_line and _is_exchange_dn(lines[i]):
        i += 1

    # If next structural step is LABEL (not BODY), consume continuation lines.
    # This handles multi-line recipient lists and split dates.
    if next_role == Role.LABEL:
        while i < max_line:
            s = lines[i].strip()
            if not s:
                break
            if _is_any_label(lines[i]):
                break
            # Stop if this line starts a new field inline (e.g., "Sent: Wednesday, ...")
            # This prevents greedy consumption of the next header label+value
            if _is_inline_header(lines[i]):
                break
            if _is_exchange_dn(lines[i]):
                # DN line — skip, it's an internal routing artifact
                i += 1
                continue
            if _is_junk_line(lines[i]):
                # Pure junk line — skip
                i += 1
                continue
            # Check: is this a date fragment? (e.g., "Wednesday," then "November 5, 2001")
            # Re-join with previous part if the combined text looks like a date
            combined = parts[-1] + ' ' + s
            if _looks_like_date(combined) and not _looks_like_date(parts[-1]):
                parts[-1] = combined
            else:
                parts.append(s)
            i += 1

    value = '; '.join(parts) if len(parts) > 1 else parts[0]
    return value, i


def match_template(template, lines, start):
    """Walk a template structure against input lines.

    Returns a dict of extracted fields + metadata, or None on failure.

    Extended vs. the Clinton matcher:
    - Skips junk OCR lines between any structural elements
    - Skips Exchange DN continuation lines after From/To values
    - Tolerates date values split across multiple lines
    - Uses relaxed label patterns (Ce:, Subject :, etc.)
    """
    structure = template['structure']
    extracted = {}
    i = start
    max_line = min(start + 40, len(lines))  # Extended window for Enron boilerplate

    for step_idx, (role, field) in enumerate(structure):

        # Skip blank, junk, and Exchange DN lines between structural elements.
        # Exchange DN lines (</O=ENRON/...>) appear after From/To values and
        # must be transparent to the template matcher.
        skipped = 0
        while i < max_line and (
            not lines[i].strip()
            or _is_junk_line(lines[i])
            or _is_exchange_dn(lines[i])
        ):
            i += 1
            skipped += 1
            if skipped > _MAX_SKIP:
                break

        if i >= max_line:
            remaining = [r for r, _ in structure[step_idx:]]
            if all(r == Role.BODY for r in remaining):
                extracted['_body_start_idx'] = None
                break
            return None

        if role == Role.LABEL:
            if not _is_label_for(lines[i], field):
                return None
            i += 1

        elif role == Role.VALUE:
            next_role = structure[step_idx + 1][0] if step_idx + 1 < len(structure) else None
            val, i = _collect_value(lines, i, max_line, next_role)
            if val is None:
                return None
            extracted[field] = val

        elif role == Role.LABEL_VALUE:
            val = _extract_label_value(lines[i], field)
            if val is None:
                return None
            # Consume Exchange DN continuation lines after the value
            extracted[field] = val
            i += 1
            while i < max_line and _is_exchange_dn(lines[i]):
                i += 1

        elif role == Role.BODY:
            while i < len(lines) and not lines[i].strip():
                i += 1
            extracted['_body_start_idx'] = i if i < len(lines) else None
            break

    _fill_missing(extracted)

    if not _validate_extracted(extracted):
        return None

    extracted['_template'] = template['name']
    return extracted


# =====================================================================
# MAIN DISPATCHER
# =====================================================================

def extract_enron_headers(text):
    """Extract email headers from Enron PDF-extracted text.

    1. Strips Enron-specific boilerplate.
    2. Locates the From: line (within first 30 lines post-stripping).
    3. Tries templates most-specific-first.

    Returns a dict with from/sent/to/cc/subject keys plus:
      _template      : template name that matched
      _body_start_idx: line index of first body line (in stripped text lines)

    Returns None if no template matches.
    """
    cleaned = strip_enron_boilerplate(text)
    lines = cleaned.split('\n')

    start = _find_from_line(lines)
    if start is None:
        return None

    for template in TEMPLATES:
        result = match_template(template, lines, start)
        if result is not None:
            return result

    return None
