(() => {
  const sel = $SELECTOR;
  const limit = $LIMIT;
  const out = [];

  function snapshot(el, path) {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName ? el.tagName.toLowerCase() : null,
      id: el.id || null,
      classes: (el.className && el.className.toString)
        ? el.className.toString().split(" ").filter(Boolean)
        : [],
      text: (el.innerText || el.textContent || "").trim().slice(0, 200),
      attrs: (() => {
        const map = {};
        for (const a of el.attributes || []) map[a.name] = a.value;
        return map;
      })(),
      box: { x: r.x, y: r.y, w: r.width, h: r.height },
      shadow_path: path,
    };
  }

  function walk(root, path) {
    if (!root || out.length >= limit) return;
    let matches;
    try { matches = root.querySelectorAll(sel); }
    catch (e) { return; }
    for (const el of matches) {
      if (out.length >= limit) return;
      out.push(snapshot(el, path));
    }
    const candidates = root.querySelectorAll("*");
    for (const el of candidates) {
      if (out.length >= limit) return;
      if (el.shadowRoot) {
        walk(el.shadowRoot, path.concat([
          el.tagName ? el.tagName.toLowerCase() : "?",
        ]));
      }
    }
  }

  walk(document, []);
  return out;
})()
