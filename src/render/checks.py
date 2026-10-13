"""What a page actually does in a browser, measured rather than read.

The page builder's quality bar ("does not scroll sideways at 375 px", "every colour is a
token", form fields at 16 px) was checked by the model rereading its own markup, and some
of it cannot be seen that way: a declaration the browser does not understand is dropped
without an error, and the file still reads as correct. Each check here returns findings,
never a score -- a gate that only says green is decoration -- and each has a test that
plants its defect and proves it is caught (tests/unit/render/test_checks.py).

The measuring script is evaluated by Playwright, not by the page: the page's own scripts
stay off.
"""

from typing import Any

from .browser import Browser

MOBILE_WIDTH = 375
DESKTOP_WIDTH = 1440
# per check, so one systemic mistake does not bury the rest
MAX_EXAMPLES = 6

# Shared helpers, then one function per check. Each returns a list of
# {"message": str, "examples": [str]}.
_JS = r"""
() => {
  const MAX = __MAX__;
  const vw = document.documentElement.clientWidth;

  const describe = (el) => {
    let out = el.tagName.toLowerCase();
    if (el.id) out += '#' + el.id;
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (cls.length) out += '.' + cls.join('.');
    const text = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    return text ? `${out} ("${text}")` : out;
  };
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const ownText = (el) => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const all = [...document.body.querySelectorAll('*')].filter(el => !['SCRIPT','STYLE','HEAD','META','LINK','TITLE','BR'].includes(el.tagName));

  // colours as [r, g, b, a]
  const probe = document.createElement('i');
  document.body.appendChild(probe);
  const rgba = (value) => {
    probe.style.color = '';
    probe.style.color = value;
    const computed = getComputedStyle(probe).color;
    const m = computed.match(/[\d.]+/g);
    if (!m) return null;
    // color-mix() and friends compute to color(srgb r g b / a), with channels from 0 to 1
    const unit = computed.startsWith('color(srgb') ? 255 : 1;
    return [ +m[0] * unit, +m[1] * unit, +m[2] * unit, m[3] === undefined ? 1 : +m[3] ];
  };
  const key = (c) => c ? c.slice(0, 3).map(Math.round).join(',') + ',' + (Math.round(c[3] * 100) / 100) : '';

  // the page's own CSS text, comments out
  const sources = [...document.querySelectorAll('style')].map(s => s.textContent.replace(/\/\*[\s\S]*?\*\//g, ''));
  const inline = [...document.querySelectorAll('[style]')].map(el => el.getAttribute('style'));

  const splitDeclarations = (block) => {
    const out = []; let depth = 0, quote = null, cur = '';
    for (const ch of block) {
      if (quote) { if (ch === quote) quote = null; cur += ch; continue; }
      if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
      if (ch === '(') depth++;
      if (ch === ')') depth--;
      if (ch === ';' && depth === 0) { out.push(cur); cur = ''; continue; }
      cur += ch;
    }
    if (cur.trim()) out.push(cur);
    return out.map(d => d.trim()).filter(Boolean);
  };
  const blocks = [];  // [selector, declarations]
  for (const text of sources) {
    for (const m of text.matchAll(/([^{}]*)\{([^{}]*)\}/g)) blocks.push([m[1].trim(), m[2]]);
  }
  for (const text of inline) blocks.push(['[style]', text]);

  const checks = {};

  checks.overflow = () => {
    if (document.documentElement.scrollWidth <= vw + 1) return [];
    const clipped = (el) => {
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const o = getComputedStyle(p).overflowX;
        if (o !== 'visible') return true;
      }
      return false;
    };
    const wide = all.filter(el => visible(el) && el.getBoundingClientRect().right > vw + 1 && !clipped(el));
    // the outermost offenders: a child of one already listed adds nothing
    const roots = wide.filter(el => !wide.some(other => other !== el && other.contains(el)));
    return [{
      message: `The page scrolls sideways at ${vw}px: it is ${document.documentElement.scrollWidth}px wide. These run past the right edge`,
      examples: roots.slice(0, MAX).map(el => `${describe(el)} reaches ${Math.round(el.getBoundingClientRect().right)}px`),
    }];
  };

  checks.css = () => {
    const out = [];
    const dropped = [];
    const badSelectors = [];
    for (const [selector, body] of blocks) {
      if (selector.startsWith('@')) continue;  // @font-face, @page: descriptors, not properties
      const keyframe = /^(from|to|[\d.]+%)(\s*,\s*(from|to|[\d.]+%))*$/.test(selector);
      if (selector !== '[style]' && !keyframe && selector) {
        for (const part of selector.split(',')) {
          const s = part.trim();
          if (s && !CSS.supports(`selector(${s})`)) badSelectors.push(s);
        }
      }
      for (const decl of splitDeclarations(body)) {
        const i = decl.indexOf(':');
        if (i < 1) { dropped.push(decl.slice(0, 60)); continue; }
        const prop = decl.slice(0, i).trim();
        const value = decl.slice(i + 1).replace(/!\s*important\s*$/i, '').trim();
        if (prop.startsWith('--')) continue;
        if (!CSS.supports(prop, value)) dropped.push(`${prop}: ${value}`.slice(0, 80));
      }
    }
    if (dropped.length) out.push({
      message: `${dropped.length} declaration(s) the browser does not understand, so it drops them silently`,
      examples: [...new Set(dropped)].slice(0, MAX),
    });
    if (badSelectors.length) out.push({
      message: `${badSelectors.length} selector(s) the browser cannot parse; a bad selector drops its whole rule`,
      examples: [...new Set(badSelectors)].slice(0, MAX),
    });
    const defined = new Set();
    const used = new Set();
    for (const [, body] of blocks) {
      for (const m of body.matchAll(/(--[\w-]+)\s*:/g)) defined.add(m[1]);
      for (const m of body.matchAll(/var\(\s*(--[\w-]+)\s*(,)?/g)) if (!m[2]) used.add(m[1]);
    }
    const undefinedVars = [...used].filter(v => !defined.has(v));
    if (undefinedVars.length) out.push({
      message: 'custom properties used without a fallback but never defined, so those declarations do nothing',
      examples: undefinedVars.slice(0, MAX),
    });
    return out;
  };

  checks.tokens = () => {
    const rootTokens = [];
    for (const [selector, body] of blocks) {
      if (!/(^|,)\s*(:root|html)\s*(,|$)/.test(selector)) continue;
      for (const decl of splitDeclarations(body)) {
        const i = decl.indexOf(':');
        if (i > 0 && decl.slice(0, i).trim().startsWith('--')) rootTokens.push(decl.slice(0, i).trim());
      }
    }
    if (!rootTokens.length) return [{ message: 'the page defines no :root tokens, so no colour or spacing is a token', examples: [] }];
    const root = getComputedStyle(document.documentElement);
    const palette = new Set(['0,0,0,0']);  // transparent is not a choice
    // A token at partial opacity (white at 16 %, a tint of the accent) is still the token.
    const hues = new Set();
    const tokened = (c) => palette.has(key(c)) || (c[3] < 1 && hues.has(key(c).split(',').slice(0, 3).join(',')));
    const spacing = new Set(['0px', 'auto']);
    for (const name of rootTokens) {
      const value = root.getPropertyValue(name).trim();
      const colour = rgba(value);
      if (colour) { palette.add(key(colour)); hues.add(key(colour).split(',').slice(0, 3).join(',')); }
      if (/^-?[\d.]+(px|rem|em)$/.test(value)) {
        probe.style.marginTop = value;
        spacing.add(getComputedStyle(probe).marginTop);
      }
    }
    const hasSpacingScale = rootTokens.some(n => /^--(space|sp|gap)/.test(n));
    const colours = new Map(), spaces = new Map();
    const note = (map, value, el) => { if (!map.has(value)) map.set(value, []); map.get(value).push(el); };
    for (const el of all) {
      if (!visible(el)) continue;
      const s = getComputedStyle(el);
      if (ownText(el)) { const c = rgba(s.color); if (c && !tokened(c)) note(colours, s.color, el); }
      const bg = rgba(s.backgroundColor);
      if (bg && bg[3] > 0 && !tokened(bg)) note(colours, s.backgroundColor, el);
      if (hasSpacingScale) {
        for (const p of ['marginTop','marginBottom','paddingTop','paddingBottom','paddingLeft','paddingRight','rowGap','columnGap']) {
          const v = s[p];
          if (v && v !== 'normal' && !spacing.has(v) && parseFloat(v) > 0) note(spaces, `${p.replace(/[A-Z]/g, c => '-' + c.toLowerCase())} ${v}`, el);
        }
      }
    }
    const out = [];
    const top = (map) => [...map.entries()].sort((a, b) => b[1].length - a[1].length).slice(0, MAX)
      .map(([value, els]) => `${value} on ${els.length} element(s), e.g. ${describe(els[0])}`);
    if (colours.size) out.push({ message: `${colours.size} colour(s) on screen that match no :root token`, examples: top(colours) });
    if (spaces.size) out.push({ message: `${spaces.size} spacing value(s) that match no spacing token`, examples: top(spaces) });
    return out;
  };

  checks.small_text = () => {
    const out = [];
    const fields = all.filter(el => ['INPUT','SELECT','TEXTAREA'].includes(el.tagName) && visible(el)
      && !['checkbox','radio','hidden','range','color','submit','button','image','file'].includes(el.type));
    const smallFields = fields.filter(el => parseFloat(getComputedStyle(el).fontSize) < 16);
    if (smallFields.length) out.push({
      message: 'form fields under 16px: phones zoom the page in when one is tapped',
      examples: smallFields.slice(0, MAX).map(el => `${describe(el)} at ${getComputedStyle(el).fontSize}`),
    });
    const smallText = all.filter(el => ownText(el) && visible(el) && parseFloat(getComputedStyle(el).fontSize) < 12);
    if (smallText.length) out.push({
      message: `${smallText.length} text element(s) under 12px at ${vw}px wide`,
      examples: smallText.slice(0, MAX).map(el => `${describe(el)} at ${getComputedStyle(el).fontSize}`),
    });
    return out;
  };

  checks.images = () => {
    const out = [];
    const imgs = [...document.images];
    const unsized = imgs.filter(img => !img.hasAttribute('width') || !img.hasAttribute('height'));
    if (unsized.length) out.push({
      message: '<img> without width and height attributes: the page jumps as it loads',
      examples: unsized.slice(0, MAX).map(img => describe(img) + ' ' + (img.getAttribute('src') || '').slice(0, 60)),
    });
    const broken = imgs.filter(img => img.complete && img.naturalWidth === 0);
    if (broken.length) out.push({
      message: 'images that did not load (a missing file, or an address the page may not fetch)',
      examples: broken.slice(0, MAX).map(img => (img.getAttribute('src') || '(no src)').slice(0, 80)),
    });
    return out;
  };

  checks.contrast = () => {
    const luminance = (c) => {
      const [r, g, b] = c.slice(0, 3).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const blend = (top, bottom) => {
      const a = top[3];
      return [0, 1, 2].map(i => top[i] * a + bottom[i] * (1 - a)).concat(1);
    };
    // the colour behind an element; null when an image or gradient is in the way
    const ground = (el) => {
      const layers = [];
      for (let p = el; p; p = p.parentElement) {
        const s = getComputedStyle(p);
        if (s.backgroundImage !== 'none') return null;
        const c = rgba(s.backgroundColor);
        if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
      }
      let colour = [255, 255, 255, 1];
      for (const layer of layers.reverse()) colour = blend(layer, colour);
      return colour;
    };
    const low = [];
    for (const el of all) {
      if (!ownText(el) || !visible(el)) continue;
      const s = getComputedStyle(el);
      const bg = ground(el);
      const fgRaw = rgba(s.color);
      if (!bg || !fgRaw) continue;
      const fg = blend(fgRaw, bg);
      const [l1, l2] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
      const ratio = (l1 + 0.05) / (l2 + 0.05);
      const size = parseFloat(s.fontSize), bold = parseInt(s.fontWeight) >= 700;
      const needed = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
      if (ratio < needed) low.push(`${describe(el)}: ${ratio.toFixed(2)}:1, needs ${needed}:1 (${s.color} on ${key(bg).split(',').slice(0, 3).join(',')})`);
    }
    return low.length ? [{ message: `${low.length} text element(s) below WCAG AA contrast`, examples: low.slice(0, MAX) }] : [];
  };

  checks.fonts = () => {
    const generic = new Set(['serif','sans-serif','monospace','cursive','fantasy','system-ui','ui-serif','ui-sans-serif','ui-monospace','ui-rounded','emoji','math','fangsong','inherit','initial','-apple-system','blinkmacsystemfont']);
    const faces = [...document.fonts];
    const loaded = new Set(faces.filter(f => f.status === 'loaded').map(f => f.family.replace(/["']/g, '').toLowerCase()));
    const failed = faces.filter(f => f.status === 'error').map(f => f.family.replace(/["']/g, ''));
    const wanted = new Map();
    for (const el of all) {
      if (!ownText(el) || !visible(el)) continue;
      const first = getComputedStyle(el).fontFamily.split(',')[0].replace(/["']/g, '').trim();
      if (first && !generic.has(first.toLowerCase()) && !loaded.has(first.toLowerCase())) {
        if (!wanted.has(first)) wanted.set(first, el);
      }
    }
    const out = [];
    if (failed.length) out.push({ message: 'web fonts that failed to load', examples: [...new Set(failed)].slice(0, MAX) });
    if (wanted.size) out.push({
      message: 'typefaces asked for but never loaded, so the browser silently uses a fallback (load them from Google Fonts with a <link>)',
      examples: [...wanted.entries()].slice(0, MAX).map(([family, el]) => `${family}, e.g. ${describe(el)}`),
    });
    return out;
  };

  const wanted = __CHECKS__;
  const result = {};
  for (const name of wanted) {
    try { result[name] = checks[name](); }
    catch (e) { result[name] = [{ message: `the ${name} check could not run: ${e}`, examples: [] }]; }
  }
  probe.remove();
  return result;
}
"""

# Width-dependent checks run on the phone; the rest once, on the desktop layout.
MOBILE_CHECKS = ("overflow", "small_text")
DESKTOP_CHECKS = ("css", "tokens", "images", "contrast", "fonts")


def _script(checks: tuple[str, ...]) -> str:
    names = "[" + ",".join(f"'{name}'" for name in checks) + "]"
    return _JS.replace("__MAX__", str(MAX_EXAMPLES)).replace("__CHECKS__", names)


async def _measure(browser: Browser, html: str, width: int, checks: tuple[str, ...]) -> dict[str, Any]:
    async with browser.open(html, width) as session:
        found = await session.page.evaluate(_script(checks))
        return {"findings": found, "blocked": session.blocked}


async def run(browser: Browser, html: str) -> dict[str, Any]:
    """Every finding, grouped by check, with the width it was measured at."""
    mobile = await _measure(browser, html, MOBILE_WIDTH, MOBILE_CHECKS)
    desktop = await _measure(browser, html, DESKTOP_WIDTH, DESKTOP_CHECKS)
    findings = []
    for width, measured in ((MOBILE_WIDTH, mobile), (DESKTOP_WIDTH, desktop)):
        for check, items in measured["findings"].items():
            for item in items:
                findings.append({"check": check, "width": width, **item})
    blocked = sorted(set(mobile["blocked"]) | set(desktop["blocked"]))
    return {"findings": findings, "blocked": blocked}
