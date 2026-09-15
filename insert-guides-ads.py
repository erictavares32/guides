#!/usr/bin/env python3
"""
insert-guides-ads.py — Bulletproof AdSense insertion for the static guides site.

What it does (per *.html, idempotent):
  1. ATF unit after the first <p class="intro"> (else after <h1>).
  2. Mid-article unit after the middle content block of the main container.
  3. Bottom unit before <footer> (else after the main container).
  4. Injects shared CSS (reserved heights -> zero CLS) + a consent-aware loader
     (respects the main site's localStorage consent; unknown -> non-personalized;
     opt-out -> no ads; lazy-push below the fold; collapse-if-unfilled only
     off-screen).

Guarantees:
  - Byte-for-byte preservation except the inserted blocks (string splicing at
    computed offsets; original encoding/newlines kept).
  - Idempotent: files already containing <!-- WTW-ADS --> are skipped.
  - Dry-run by default; --apply writes.
  - UTF-8 safe (no PowerShell/ANSI path).

Slot IDs: fill the three constants below with real AdSense unit IDs, then run
  python insert-guides-ads.py --apply
"""
import glob
import os
import re
import sys

SLOT_ATF = "7706521584"      # Reuses Movie-ATF (Display, horizontal). Same slot may appear on different pages, never twice on one page.
SLOT_MID = "5136198567"      # Reuses Movie-InContent (Display, rectangle).
SLOT_BOTTOM = "1141113238"   # Reuses Show-InContent (Display, rectangle).
PUB_ID = "ca-pub-2167344122409975"

MARKER = "<!-- WTW-ADS -->"
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

CSS_BLOCK = """<!-- WTW-ADS-CSS -->
<style>
.wtw-gad{display:flex;width:100%;align-items:center;justify-content:center;margin:1.5rem auto;min-height:100px}
.wtw-gad-rect{min-height:280px}
.wtw-gad-atf{height:100px;overflow:hidden}
.wtw-gad ins.adsbygoogle{display:block;width:100%}
</style>"""

LOADER_JS = """<!-- WTW-ADS-LOADER -->
<script>
(function(){
  var KEY='wheretowatch-cookie-consent',cons=null;
  try{cons=JSON.parse(localStorage.getItem(KEY)||'null');}catch(e){}
  var adv=cons?(typeof cons.advertising==='boolean'?cons.advertising:true):null;
  if(adv===false){
    try{document.querySelectorAll('.wtw-gad').forEach(function(w){w.remove();});}catch(e){}
    return;
  }
  var npa=(adv!==true);
  var q=(window.adsbygoogle=window.adsbygoogle||[]);
  if(npa){try{q.requestNonPersonalizedAds=1;}catch(e){}}
  function pushOne(ins){
    if(!ins||ins.getAttribute('data-pushed'))return;
    ins.setAttribute('data-pushed','1');
    try{q.push({});}catch(e){}
  }
  function sweep(){
    document.querySelectorAll('.wtw-gad').forEach(function(w){
      if(!w.querySelector('iframe')){
        var r=w.getBoundingClientRect();
        if(!(r.bottom>0&&r.top<window.innerHeight)){w.style.display='none';}
      }
    });
  }
  function lazy(){
    var units=Array.prototype.slice.call(document.querySelectorAll('ins.adsbygoogle[data-wtw]'));
    if(!('IntersectionObserver' in window)){units.forEach(pushOne);setTimeout(sweep,2500);return;}
    var io=new IntersectionObserver(function(es){
      es.forEach(function(en){
        if(en.isIntersecting){
          var box=en.target;
          pushOne(box.querySelector('ins.adsbygoogle'));
          try{io.unobserve(box);}catch(e){}
        }
      });
    },{rootMargin:'300px 0px'});
    units.forEach(function(u){io.observe(u.closest('.wtw-gad')||u);});
    setTimeout(sweep,4000);setTimeout(sweep,9000);
  }
  function boot(){
    var s=document.createElement('script');
    s.async=true;s.crossOrigin='anonymous';
    s.src='https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=PUBID';
    s.onload=lazy;s.onerror=function(){};
    document.head.appendChild(s);
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',boot);}else{boot();}
})();
</script>""".replace("PUBID", PUB_ID)


def find_open(html, tag, attr_sub=None, occurrence=0, start=0):
    """Return (open_start, open_end) of the Nth <tag ...> matching attr_sub."""
    pat = re.compile(r"<%s\b[^>]*>" % re.escape(tag), re.IGNORECASE)
    n = 0
    for m in pat.finditer(html, start):
        if attr_sub and attr_sub.lower() not in m.group(0).lower():
            continue
        if n == occurrence:
            return (m.start(), m.end())
        n += 1
    return None


def element_span(html, tag, attr_sub=None, occurrence=0, start=0):
    """Return (start, end) covering the element incl. its close tag."""
    o = find_open(html, tag, attr_sub, occurrence, start)
    if not o:
        return None
    if tag.lower() in VOID_TAGS:
        return (o[0], o[1])
    depth = 1
    i = o[1]
    n = len(html)
    low = tag.lower()
    while i < n and depth > 0:
        if html.startswith("<!--", i):
            j = html.find("-->", i + 4)
            i = n if j < 0 else j + 3
            continue
        if html[i] != "<":
            i += 1
            continue
        m = re.match(r"</?\s*([a-zA-Z0-9]+)", html[i:])
        if not m:
            i += 1
            continue
        t = m.group(1).lower()
        is_close = html[i + 1] == "/"
        # skip script/style content
        if not is_close and t in ("script", "style"):
            j = re.search(r"</\s*%s\s*>" % t, html[i:], re.IGNORECASE)
            i = n if not j else i + j.end()
            continue
        if t == low:
            # ignore self-closing <tag .../>
            gt = html.find(">", i)
            if gt < 0:
                return None
            selfclose = html[gt - 1] == "/"
            if not selfclose:
                depth += -1 if is_close else 1
            i = gt + 1
        else:
            j = html.find(">", i)
            i = n if j < 0 else j + 1
    return (o[0], i) if depth == 0 else None


def direct_children(html, pstart, pend):
    """Yield (tag, start, end) for depth-0 elements inside [pstart, pend)."""
    kids = []
    i = pstart
    depth = 0
    cur = None
    n = pend
    while i < n:
        if html.startswith("<!--", i):
            j = html.find("-->", i + 4)
            i = n if j < 0 else j + 3
            continue
        if html[i] != "<":
            i += 1
            continue
        m = re.match(r"</?\s*([a-zA-Z0-9]+)([^>]*)>", html[i:], re.IGNORECASE | re.DOTALL)
        if not m:
            i += 1
            continue
        t = m.group(1).lower()
        is_close = html[i + 1] == "/"
        full = m.group(0)
        # script/style raw text
        if not is_close and t in ("script", "style"):
            if depth == 0:
                j = re.search(r"</\s*%s\s*>" % t, html[i:], re.IGNORECASE)
                end = n if not j else i + j.end()
                kids.append((t, i, end))
            jj = re.search(r"</\s*%s\s*>" % t, html[i:], re.IGNORECASE)
            i = n if not jj else i + jj.end()
            continue
        if t in VOID_TAGS or full.rstrip().endswith("/>"):
            if depth == 0:
                kids.append((t, i, i + len(full)))
            i += len(full)
            continue
        if t.startswith("!") or t.startswith("?"):
            i += len(full)
            continue
        if not is_close:
            if depth == 0:
                cur = [t, i]
            depth += 1
        else:
            depth = max(0, depth - 1)
            if depth == 0 and cur:
                kids.append((cur[0], cur[1], i + len(full)))
                cur = None
        i += len(full)
    return kids


def inner_kids(html, sp):
    """Direct element children inside a parent span (excludes the parent tags)."""
    gt = html.find(">", sp[0])
    inner_start = gt + 1 if gt >= 0 else sp[0]
    close_start = html.rfind("</", sp[0], sp[1])
    inner_end = close_start if close_start >= 0 else sp[1]
    if inner_end <= inner_start:
        return []
    return direct_children(html, inner_start, inner_end)


def content_parent(html):
    """The div.container holding h1 with the most children (else body)."""
    h1 = element_span(html, "h1", None, 0)
    best = None
    occ = 0
    while occ <= 30:
        sp = element_span(html, "div", "container", occ)
        occ += 1
        if not sp:
            continue
        if h1 and sp[0] < h1[0] < sp[1]:
            kids = inner_kids(html, sp)
            if not best or len(kids) > len(best[1]):
                best = (sp, kids)
    if best:
        return best
    b = element_span(html, "body", None, 0)
    if b:
        return (b, inner_kids(html, b))
    return (None, [])


SKIP_CLASSES = ("breadcrumb", "last-updated")


def is_content(kid, html):
    tag, s, e = kid
    if tag in ("script", "style", "link", "meta", "noscript"):
        return False
    snippet = html[s:e][:600].lower()
    if any(c in snippet for c in SKIP_CLASSES):
        return False
    if tag in ("h1",):
        return False
    if tag == "p" and 'class="intro"' in html[s:s + 200].lower():
        return False
    if tag in ("header", "nav"):
        return False
    if tag == "footer":
        return False
    return True


def ad_block(slot, variant):
    if variant == "atf":
        return (
            "<!-- WTW-ADS:ATF -->\n"
            '<div class="wtw-gad wtw-gad-atf" style="height:100px;overflow:hidden">\n'
            '  <div style="display:flex;width:100%;align-items:center;justify-content:center">\n'
            '    <ins class="adsbygoogle" style="display:block;width:100%" '
            'data-wtw="atf" data-ad-client="' + PUB_ID + '" data-ad-slot="' + slot + '" '
            'data-ad-format="horizontal" data-full-width-responsive="false"></ins>\n'
            "  </div>\n</div>"
        )
    cls = "wtw-gad wtw-gad-rect"
    fmt = "rectangle"
    return (
        "<!-- WTW-ADS:" + variant.upper() + " -->\n"
        '<div class="' + cls + '" style="min-height:280px">\n'
        '  <ins class="adsbygoogle" style="display:block;width:100%" '
        'data-wtw="' + variant + '" data-ad-client="' + PUB_ID + '" data-ad-slot="' + slot + '" '
        'data-ad-format="' + fmt + '" data-full-width-responsive="true"></ins>\n'
        "</div>"
    )


def process(path, apply):
    with open(path, "rb") as f:
        raw = f.read()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    html = raw.decode("utf-8")
    if MARKER in html:
        return (os.path.basename(path), "skip-marked", [])
    edits = []  # (offset, text) insert BEFORE offset; applied back-to-front

    def ins_before(off, text):
        edits.append((off, text))

    def ins_at_line_start(off, text):
        # Insert at the start of the line so the target element keeps its indent.
        ls = html.rfind("\n", 0, off) + 1
        edits.append((ls, text))

    # CSS into <head>
    if "<!-- WTW-ADS-CSS -->" not in html:
        h = html.lower().find("</head>")
        if h > 0:
            ins_at_line_start(h, CSS_BLOCK.replace("\n", nl) + nl)

    # ATF
    intro = element_span(html, "p", 'class="intro"', 0)
    if intro:
        atf_at = intro[1]
    else:
        h1 = element_span(html, "h1", None, 0)
        atf_at = h1[1] if h1 else None
    if atf_at is not None:
        ins_before(atf_at, nl + ad_block(SLOT_ATF, "atf").replace("\n", nl) + nl)

    def line_of(off):
        return html.count("\n", 0, off)

    atf_line = line_of(atf_at) if atf_at is not None else -1

    # Content parent (shared by MID + BOTTOM fallback)
    (psp, kids) = content_parent(html)
    content = [k for k in kids if is_content(k, html)]

    # BOTTOM offset first (for separation check)
    ftr = element_span(html, "footer", None, 0)
    if ftr:
        bot_at, bot_kind, bot_line_start = ftr[0], "footer", True
    elif psp:
        bot_at, bot_kind, bot_line_start = psp[1], "parent-end", False
    else:
        b = html.lower().rfind("</body>")
        bot_at, bot_kind, bot_line_start = (b, "body", True) if b > 0 else (None, "none", False)
    bot_line = line_of(bot_at) if bot_at is not None else 10 ** 9

    # MID via content parent (skipped unless well separated from ATF and BOTTOM)
    mid_done = False
    if len(content) >= 3:
        mid = content[len(content) // 2]
        mid_end = mid[2] if len(mid) > 2 else mid[1]
        mid_line = line_of(mid_end)
        if (atf_at is None or (mid_line - atf_line) > 25) and (bot_line - mid_line) > 25:
            ins_before(mid_end, nl + ad_block(SLOT_MID, "rect").replace("\n", nl) + nl)
            mid_done = True

    # BOTTOM insert
    bot = bot_kind
    if bot_at is not None and bot_kind != "none":
        if bot_line_start:
            ins_at_line_start(bot_at, ad_block(SLOT_BOTTOM, "rect").replace("\n", nl) + nl)
        else:
            ins_before(bot_at, nl + ad_block(SLOT_BOTTOM, "rect").replace("\n", nl) + nl)

    # Loader before </body> (once)
    if "<!-- WTW-ADS-LOADER -->" not in html:
        b = html.lower().rfind("</body>")
        if b > 0:
            ins_at_line_start(b, LOADER_JS.replace("\n", nl) + nl)

    # apply back-to-front so offsets stay valid
    for off, text in sorted(edits, key=lambda x: -x[0]):
        html = html[:off] + text + html[off:]
    html = html.replace("<!-- WTW-ADS-LOADER -->", MARKER + "\n<!-- WTW-ADS-LOADER -->", 1) if MARKER not in html else html
    if apply:
        with open(path, "wb") as f:
            f.write(html.encode("utf-8"))
    units = ["atf" if atf_at is not None else "atf-NONE",
             "mid" if mid_done else "mid-SKIPPED",
             "bottom-" + bot]
    return (os.path.basename(path), "would-apply" if not apply else "applied", units)


def main():
    apply = "--apply" in sys.argv
    if "0000000000" in (SLOT_ATF, SLOT_MID, SLOT_BOTTOM) and apply:
        print("REFUSING: fill SLOT_ATF/SLOT_MID/SLOT_BOTTOM with real IDs first.")
        sys.exit(2)
    files = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "*.html")))
    for path in files:
        try:
            name, status, units = process(path, apply)
            print(f"{name}: {status} [{', '.join(units)}]")
        except Exception as e:
            print(f"{os.path.basename(path)}: ERROR {e}")


if __name__ == "__main__":
    main()
