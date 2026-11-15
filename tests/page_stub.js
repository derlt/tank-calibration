// A tiny DOM stub for the on-site page script (site/page.html).
// It runs the real page script under Node, so the tests can drive the page
// without a browser: set a field, click a button, read the result.
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const el = {
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    checked: false,
    open: false,
    dataset: {},
    style: {},
    _classes: new Set(),
    _listeners: {},
    classList: {
      add: (c) => el._classes.add(c),
      remove: (c) => el._classes.delete(c),
      contains: (c) => el._classes.has(c),
      toggle: (c, on) => {
        if (on === undefined) { if (el._classes.has(c)) el._classes.delete(c); else el._classes.add(c); }
        else if (on) el._classes.add(c);
        else el._classes.delete(c);
      },
    },
    addEventListener: (type, fn) => { (el._listeners[type] = el._listeners[type] || []).push(fn); },
    setAttribute: (k, v) => { el[k] = v; },
    getAttribute: (k) => el[k],
    focus: () => {},
    select: () => {},
    click: () => { for (const fn of el._listeners.click || []) fn({ target: el }); },
    querySelectorAll: () => [],
    appendChild: () => {},
    remove: () => {},
  };
  return el;
}

/** Load the page script with a stub DOM.  store is shared to simulate a reload. */
function boot(pagePath, corePath, store) {
  const core = require(corePath);
  const html = fs.readFileSync(pagePath, "utf8");
  const blocks = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  const pageScript = blocks[blocks.length - 1];

  const els = new Map();
  const el = (id) => { if (!els.has(id)) els.set(id, makeElement(id)); return els.get(id); };
  const tabs = ["live", "log", "shell", "settings", "files", "replay", "help"].map((t) => {
    const b = makeElement("tab-" + t); b.dataset.tab = t; return b;
  });
  el("tabs").querySelectorAll = (sel) => (sel === "button" ? tabs : []);

  const mem = store || new Map();
  const context = {
    window: { CalibSite: core, addEventListener: () => {} },
    document: { getElementById: el, createElement: () => makeElement("a"), body: { appendChild: () => {} } },
    localStorage: {
      getItem: (k) => (mem.has(k) ? mem.get(k) : null),
      setItem: (k, v) => mem.set(k, v),
      removeItem: (k) => mem.delete(k),
    },
    navigator: {},
    confirm: () => true,
    prompt: () => null,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    URL: { createObjectURL: () => "blob:", revokeObjectURL: () => {} },
    Blob: function () {},
    console,
    Date,
    Math,
    JSON,
    Number,
    String,
    Object,
    Array,
    isFinite,
    parseFloat,
    Error,
  };
  context.window.document = context.document;
  vm.createContext(context);
  vm.runInContext(pageScript, context);
  return { el, tabs, store: mem };
}

module.exports = { boot };
