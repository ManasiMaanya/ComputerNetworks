// Minimal mock of Packet Tracer's Script Engine IPC API, for running the
// generated PTBuilder scripts under Node in tests.
//
// Only the calls PTBuilder / MCP-Packet-Tracer document as working in PT
// 9.0.1 are implemented; calling anything else throws a TypeError, as the
// real engine does. PT rules that would make a real build fail are
// enforced: unknown models, unknown or already-used ports, and the wrong
// copper cable type (switch-switch needs cross-over, switch-PC straight).
//
// Usage: node pt_mock.js script1.js [script2.js ...]   -> JSON state on stdout
// Env PT_MOCK_FAIL_LINKS=1 makes createLink return false (failure path).
"use strict";
const fs = require("fs");

const MODELS = {
  "3560-24PS": { type: 16, prefix: "Multilayer Switch", ports: [
    ...Array.from({ length: 24 }, (_, i) => `FastEthernet0/${i + 1}`),
    "GigabitEthernet0/1", "GigabitEthernet0/2"] },
  "PC-PT": { type: 8, prefix: "PC", ports: ["FastEthernet0"] },
};
const CABLES = { 8100: "straight", 8101: "cross" };

const devices = {};
const links = [];
const messages = [];
const counters = {};

function makePort(name) {
  return {
    _name: name, _ip: null, _mask: null, _gateway: null, _link: null,
    setIpSubnetMask(ip, mask) { this._ip = ip; this._mask = mask; },
    setDefaultGateway(gw) { this._gateway = gw; },
    getLink() { return this._link; },
  };
}

function makeDevice(model, autoName, x, y) {
  const spec = MODELS[model];
  const ports = {};
  for (const p of spec.ports) ports[p] = makePort(p);
  const dev = {
    _name: autoName, _model: model, _type: spec.type, _x: x, _y: y, _ports: ports,
    _commands: [], _booted: false, _gateway: null,
    setName(n) { delete devices[this._name]; this._name = n; devices[n] = this; },
    getName() { return this._name; },
    getType() { return this._type; },
    skipBoot() { this._booted = true; },
    getPort(n) { return this._ports[n] || null; },
    getPorts() { return Object.keys(this._ports); },
    enterCommand(cmd, mode) {
      if (typeof cmd !== "string" || typeof mode !== "string") throw new TypeError("enterCommand(string, string)");
      this._commands.push([cmd, mode]);
    },
  };
  if (spec.type === 8) dev.setDefaultGateway = function (gw) { this._gateway = gw; };
  return dev;
}

const lw = {
  addDevice(type, model, x, y) {
    const spec = MODELS[model];
    if (!spec || spec.type !== type) return "";
    const n = counters[model] || 0;
    counters[model] = n + 1;
    const autoName = `${spec.prefix}${n}`;
    devices[autoName] = makeDevice(model, autoName, x, y);
    return autoName;
  },
  createLink(d1, p1, d2, p2, type) {
    if (process.env.PT_MOCK_FAIL_LINKS) return false;
    const a = devices[d1], b = devices[d2];
    if (!a || !b) return false;
    const pa = a.getPort(p1), pb = b.getPort(p2);
    if (!pa || !pb || pa._link || pb._link) return false;
    const kind = CABLES[type];
    if (!kind) return false;
    const sameKind = (a._type === 8) === (b._type === 8);
    if ((sameKind && kind !== "cross") || (!sameKind && kind !== "straight")) return false;
    const link = { a: d1, aPort: p1, b: d2, bPort: p2, cable: kind };
    pa._link = link; pb._link = link;
    links.push(link);
    return true;
  },
};

global.ipc = {
  network() { return { getDevice(n) { return devices[n] || null; } }; },
  appWindow() {
    return {
      getActiveWorkspace() { return { getLogicalWorkspace() { return lw; } }; },
      showMessageBox(title, text, detail) { messages.push({ title, text, detail }); },
    };
  },
};

for (const file of process.argv.slice(2)) {
  const code = fs.readFileSync(file, "utf8");
  // The Builder Code Editor is an HTML textarea, whose value has LF line endings only; PTBuilder
  // then strips every "\n" (interface.js executeCode: code.replace(/\n/g, "")) and runCode()
  // wraps the result in new Function. Mimic all three, so a "//" comment that would swallow the
  // rest of the script fails here too.
  new Function(code.replace(/\r\n?/g, "\n").replace(/\n/g, ""))();
}

const out = { devices: {}, links, messages };
for (const [name, d] of Object.entries(devices)) {
  const ports = {};
  for (const [pn, p] of Object.entries(d._ports)) {
    if (p._ip || p._link || p._gateway) ports[pn] = { ip: p._ip, mask: p._mask, gateway: p._gateway, linked: !!p._link };
  }
  out.devices[name] = { model: d._model, type: d._type, x: d._x, y: d._y, booted: d._booted,
    gateway: d._gateway, commands: d._commands, ports };
}
process.stdout.write(JSON.stringify(out));
