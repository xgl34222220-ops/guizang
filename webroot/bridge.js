/* Original read-only transport based on KernelSU's documented exec callback ABI.
 * No third-party implementation copied. Not a security boundary against hostile code
 * in a privileged WebView: the installer and all bundled resources must be trusted.
 */
(function (root) {
  'use strict';
  const COMMAND = '/data/adb/modules/guizang/bin/guizang-probe --json';
  const MAX_BYTES = 16384;
  function parseReport(text) {
    if (typeof text !== 'string' || text.length > MAX_BYTES) throw Error('invalid_report_size');
    const raw = JSON.parse(text);
    if (!raw || raw.schema !== 2 || raw.source !== 'guizang-native-probe' || raw.read_only !== true ||
        raw.android !== true || raw.execution !== 'disabled' || raw.freeze_ready !== false || raw.error) throw Error('invalid_report_contract');
    if (!Number.isSafeInteger(raw.effective_uid) || raw.effective_uid < 0) throw Error('invalid_uid');
    const data = { schema: 2, readOnly: true, root: raw.effective_uid === 0, freezeReady: false };
    for (const key of ['sdk', 'model', 'soc', 'kernel']) {
      if (typeof raw[key] !== 'string' || !raw[key] || raw[key].length > 160 || /[\u0000-\u001f\u007f]/.test(raw[key])) throw Error('invalid_' + key);
      data[key] = raw[key];
    }
    if (!raw.capabilities || typeof raw.capabilities !== 'object') throw Error('invalid_capabilities');
    const caps = {};
    for (const key of ['cgroup2_membership', 'self_freezer_node', 'binder_node', 'pidfd_open', 'framework_coordinator', 'protection_signals', 'verified_thaw']) {
      if (typeof raw.capabilities[key] !== 'boolean') throw Error('invalid_' + key);
      caps[key] = raw.capabilities[key];
    }
    // This release cannot certify coordination/protection/thaw even if an unexpected
    // or compromised producer claims otherwise.
    if (caps.framework_coordinator || caps.protection_signals || caps.verified_thaw) throw Error('unsupported_execution_claim');
    data.capabilities = Object.freeze(caps);
    return Object.freeze(data);
  }
  function createReadOnlyBridge({ host = root, enabled = false, timeoutMs = 4000 } = {}) {
    let inFlight = null, sequence = 0;
    const available = () => enabled === true && host && host.ksu && typeof host.ksu.exec === 'function';
    function readCapabilities() {
      if (!available()) return Promise.reject(Error(enabled === true ? 'manager_unavailable' : 'bridge_disabled'));
      if (inFlight) return inFlight;
      const job = new Promise((resolve, reject) => {
        const name = `guizang_probe_${Date.now()}_${sequence++}`;
        let finished = false;
        const done = (error, value) => {
          if (finished) return;
          finished = true; clearTimeout(timer); delete host[name];
          if (error) reject(error); else resolve(value);
        };
        const timer = setTimeout(() => done(Error('probe_timeout')), Math.max(10, Math.min(timeoutMs, 10000)));
        host[name] = (errno, stdout) => {
          if (errno !== 0) { done(Error('probe_failed')); return; }
          try { done(null, parseReport(stdout)); } catch (error) { done(error); }
        };
        try { host.ksu.exec(COMMAND, '{}', name); } catch (_) { done(Error('manager_error')); }
      });
      inFlight = job.finally(() => { inFlight = null; });
      return inFlight;
    }
    return Object.freeze({ available, readCapabilities });
  }
  const api = Object.freeze({ parseReport, createReadOnlyBridge });
  if (typeof module !== 'undefined') module.exports = api;
  else Object.defineProperty(root, 'GuizangBridge', { value: api, writable: false });
})(typeof window !== 'undefined' ? window : undefined);
