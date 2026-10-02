/* Standalone interaction prototype. No network, root bridge or device writes. */
(function () {
  'use strict';
  const initial = () => ({ page: 'overview', allowed: false, sleeping: false, mode: 'balanced', failures: 0, disabled: false });
  function reduce(state, action) {
    const next = { ...state };
    if (action === 'allow' && !state.disabled) { next.allowed = !state.allowed; if (!next.allowed) next.sleeping = false; }
    if (action === 'sleep' && state.allowed && !state.disabled) next.sleeping = true;
    if (action === 'wake') next.sleeping = false;
    if (action === 'fail') { next.failures = Math.min(3, state.failures + 1); next.disabled = next.failures === 3; if (next.disabled) next.sleeping = false; }
    if (action === 'healthy' && !state.disabled) next.failures = 0;
    if (action === 'reset') return { ...initial(), page: state.page };
    if (['balanced', 'save', 'observe'].includes(action)) next.mode = action;
    return next;
  }
  if (typeof module !== 'undefined') module.exports = { initial, reduce };
  if (typeof document === 'undefined') return;
  let state = initial(), timer, diagnostics = null, probeBusy = false, probeError = '';
  const bridge = window.GuizangBridge.createReadOnlyBridge({ enabled: window.GUIZANG_BUILD.deviceReadOnlyBridge });
  const escape = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const titles = { overview: '总览', apps: '应用休眠', performance: '场景调度', recovery: '启动保护' };
  const icon = (symbol, cls = '') => `<span class="app-icon ${cls}" aria-hidden="true">${symbol}</span>`;
  const row = (symbol, cls, title, subtitle, status, pill = '') => `<div class="row">${icon(symbol, cls)}<div class="row-info"><strong>${title}</strong><small>${subtitle}</small></div><span class="pill ${pill}">${status}</span></div>`;
  function toast(text) { const el = document.getElementById('toast'); el.textContent = text; el.classList.add('show'); clearTimeout(timer); timer = setTimeout(() => el.classList.remove('show'), 3500); }
  const glyph = (name, size = 24) => {
    const paths = {
      overview: '<rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1.8"/><rect x="14" y="3.5" width="6.5" height="6.5" rx="1.8"/><rect x="3.5" y="14" width="6.5" height="6.5" rx="1.8"/><rect x="14" y="14" width="6.5" height="6.5" rx="1.8"/>',
      apps: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9 5l3 2 3-2M9 19l3-2 3 2M4.5 11l3-1.5-.2-3.6M19.5 13l-3 1.5.2 3.6M7.3 18.1l.2-3.6-3-1.5M16.7 5.9l-.2 3.6 3 1.5"/>',
      performance: '<path d="M3 15h4l3-9 4 13 3-8h4"/>',
      recovery: '<path d="M12 3l8 3v5c0 5-3.4 8.5-8 10-4.6-1.5-8-5-8-10V6z"/><path d="M8.5 12l2.3 2.3 4.7-4.7"/>',
      power: '<path d="M12 3v8M6.3 6.5a8 8 0 1 0 11.4 0"/>',
      arrow: '<path d="M9 5l7 7-7 7"/>',
      link: '<path d="M8 8l-2 2a4.3 4.3 0 0 0 6 6l2-2M16 16l2-2a4.3 4.3 0 0 0-6-6l-2 2M9 15l6-6"/>',
      info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v6M12 7v.1"/>'
    };
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.info}</svg>`;
  };
  function overview() {
    const connected = !!diagnostics;
    return `<div class="console-top"><div><p class="console-kicker">设备控制台</p><h1>归藏</h1></div><span class="offline-badge"><span></span>${connected ? '只读连接' : '离线预览'}</span></div>
    <section class="device-panel" aria-label="设备连接状态"><div class="device-panel-top"><div><span class="panel-eyebrow">运行状态</span><h2>${connected ? escape(diagnostics.model) : '未连接设备'}</h2><p>${connected ? '能力快照已读取，真实执行仍关闭' : '真实执行已关闭'}</p></div><span class="power-icon">${glyph('power',27)}</span></div><div class="device-facts"><span>Root <strong>${connected ? (diagnostics.effective_uid === 0 ? '已确认' : '不可用') : '—'}</strong></span><span>内核 <strong>${connected ? escape(diagnostics.kernel) : '—'}</strong></span><span>守护进程 <strong>—</strong></span></div><button class="connection-button" data-action="${bridge.available() ? 'probe' : 'connection-help'}" ${probeBusy ? 'disabled' : ''}>${glyph('link',18)}${probeBusy ? '正在检测' : connected ? '刷新只读诊断' : '检查连接'}</button></section>
    <div class="console-section-heading"><h2>功能</h2><span>默认安全策略</span></div>
    <section class="control-group" aria-label="功能入口"><a href="#apps" class="control-row"><span class="control-icon ice">${glyph('apps')}</span><span class="control-copy"><strong>应用休眠</strong><small>仅允许名单内的应用</small></span><span class="control-status">未启用</span>${glyph('arrow',15)}</a><a href="#performance" class="control-row"><span class="control-icon violet">${glyph('performance')}</span><span class="control-copy"><strong>性能调度</strong><small>先观察，再优化</small></span><span class="control-status">仅观察</span>${glyph('arrow',15)}</a><a href="#recovery" class="control-row"><span class="control-icon steel">${glyph('recovery')}</span><span class="control-copy"><strong>启动保护</strong><small>异常时停止本模块</small></span><span class="control-status">待验证</span>${glyph('arrow',15)}</a></section>
    <div class="console-section-heading"><h2>能力检查</h2><span>${connected ? '执行链路待验证' : '尚未连接设备'}</span></div><section class="capability-list" aria-label="待验证能力"><div><span>冻结 / 唤醒</span><span class="cap-state">未验证</span></div><div><span>进程保护</span><span class="cap-state">未验证</span></div><div><span>恢复链路</span><span class="cap-state">未验证</span></div></section><p class="console-footnote">${glyph('info',14)}开发预览 · 设备操作尚未开放</p>`;
  }
  function apps() {
    return `<p class="eyebrow">APPLICATION LIFECYCLE</p><h1 class="page-title">留在内存，安静等候。</h1><p class="lead">显式允许休眠，唤醒优先。这里展示操作逻辑，不冻结真实进程。</p><section class="card"><div class="section-title first"><h2>应用名单 · 示例</h2><span class="pill neutral">${state.allowed ? '1' : '0'} 个已允许</span></div><div class="app-list"><div class="row">${icon('▤')}<div class="row-info"><strong>阅读应用</strong><small>org.example.reader · 演示</small></div><span class="pill ${state.sleeping ? '' : 'neutral'}">${state.sleeping ? '模拟休眠' : '保持活跃'}</span><button class="toggle" role="switch" aria-label="允许示例阅读应用休眠" aria-checked="${state.allowed}" data-action="allow" ${state.disabled ? 'disabled' : ''}></button></div>${row('♫', 'music', '音乐播放', '音频保护 · 不能加入休眠名单', '受保护')}${row('⌨', '', '当前输入法', '输入服务保护', '受保护')}${row('◇', 'vpn', 'VPN 连接', '网络服务保护', '受保护')}</div><div class="actions"><button class="button primary" data-action="sleep" ${!state.allowed || state.disabled || state.sleeping ? 'disabled' : ''}>模拟后台休眠</button><button class="button" data-action="wake" ${!state.sleeping ? 'disabled' : ''}>模拟前台唤醒</button></div><div class="note">${state.disabled ? '启动保护已在演示中停用模块。请到启动保护页手动重置演示。' : '真实执行器尚未开放。未来仅在身份校验、Binder 协作和可靠唤醒全部通过后开放测试。'}</div></section><div class="architecture"><section><small>01 / 识别</small><h3>身份不能猜</h3><p>校验 UID、PID、启动时间，避免误操作复用的进程。</p></section><section><small>02 / 保护</small><h3>重要任务优先</h3><p>保护信号缺失或过期，就不尝试冻结。</p></section><section><small>03 / 唤醒</small><h3>出错即退让</h3><p>解冻失败保留记录，停止新增冻结。</p></section></div>`;
  }
  function performance() {
    return `<p class="eyebrow">CONTEXT-AWARE PERFORMANCE</p><h1 class="page-title">性能，恰到好处。</h1><p class="lead">先观察场景，再决定策略。尊重系统温控，不永久超频。</p><div class="scene-grid">${[['balanced','◐','均衡','日常交互，平稳响应'],['save','☾','省电','安静待机，保留重要任务'],['observe','⌁','仅观察','了解场景，不改变参数']].map(([id,symbol,title,desc])=>`<button class="scene-option" data-action="${id}" aria-pressed="${state.mode===id}"><span>${symbol}</span><strong>${title}</strong><small>${desc}</small></button>`).join('')}</div><div class="note warn">选择仅改变演示策略。真实设备仍为观察模式，无任何 CPU / GPU / 温控写入。</div><div class="section-title"><h2>每一步，都能解释</h2><span class="pill neutral">演示轨迹</span></div><section class="card"><ol class="timeline"><li><span>场景输入</span>前台交互、音频会话、屏幕与热状态</li><li><span>策略判断</span>过热先退让，信号未知不增强性能</li><li><span>能力验证</span>逐设备确认节点、范围与独占写入条件</li><li><span>原值快照</span>先持久化恢复记录，再允许参数改变</li><li><span>失败恢复</span>倒序恢复自己的值，保留未解决的冲突</li></ol></section>`;
  }
  function recovery() {
    return `<p class="eyebrow">RECOVERY BY DESIGN</p><h1 class="page-title">留一条，回来的路。</h1><p class="lead">启动保护只负责本模块，不能修复所有变砖、分区损坏或数据丢失。</p><div class="split"><section class="card"><h3>连续启动失败 · 演示</h3><p>模拟本模块启动未通过健康检查，达到阈值后停止执行。</p><div class="guard-count">${[1,2,3].map(i=>`<span class="${i<=state.failures ? (state.disabled ? 'stopped' : 'filled') : ''}"></span>`).join('')}</div><div class="stat-line"><strong>${state.failures}<small> / 3</small></strong><span class="pill ${state.disabled ? 'amber' : 'neutral'}">${state.disabled ? '已自动停用（演示）' : '保护待命（演示）'}</span></div><div class="actions"><button class="button primary" data-action="fail" ${state.disabled ? 'disabled' : ''}>模拟一次失败</button><button class="button" data-action="healthy" ${state.disabled || !state.failures ? 'disabled' : ''}>模拟健康启动</button><button class="button" data-action="reset">重置演示</button></div></section><section class="card"><p class="eyebrow">SAFE EXIT</p><h3>恢复，只做必要的事</h3><ol class="timeline"><li><span>第一步</span>停止新的冻结和参数写入</li><li><span>第二步</span>解冻本模块持有的应用</li><li><span>第三步</span>恢复已记录且未被他人改写的原值</li><li><span>最后</span>保留原因，不自行重启或重新启用</li></ol></section></div><div class="note warn">真实设备若无法进入系统，需要 Root 管理器的安全模式或手动卸载。本原型没有刷入包，不会修改启动分区、清空数据或移除其他模块。</div>`;
  }
  function render() {
    document.body.dataset.view = state.page;
    document.querySelectorAll('[data-page]').forEach(el => { el.querySelector('span').innerHTML = glyph(el.dataset.page,22); const selected = el.dataset.page === state.page; el.classList.toggle('active', selected); if (selected) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
    document.getElementById('breadcrumb').textContent = titles[state.page];
    document.getElementById('main').innerHTML = ({ overview, apps, performance, recovery })[state.page]();
    document.title = `归藏 · ${titles[state.page]}`;
  }
  function navigate() { const hash = location.hash.slice(1); state.page = Object.hasOwn(titles, hash) ? hash : 'overview'; render(); }
  document.addEventListener('click', async event => { const button = event.target.closest('[data-action]'); if (!button || button.disabled) return; const action = button.dataset.action; if (action === 'connection-help') { document.getElementById('connection-dialog').showModal(); return; } if (action === 'close-connection') { document.getElementById('connection-dialog').close(); return; } if (action === 'probe') { if (probeBusy || !bridge.available()) return; probeBusy = true; probeError = ''; render(); try { diagnostics = await bridge.readCapabilities(); toast('只读诊断完成，真实执行仍关闭'); } catch (_) { diagnostics = null; probeError = '诊断未完成。请检查测试构建和管理器连接；真实执行仍关闭。'; toast('诊断失败，未启用任何设备操作'); } finally { probeBusy = false; render(); } return; } state = reduce(state, action); render(); const messages = { allow:'示例名单已更新，未操作设备', sleep:'已模拟休眠，未冻结真实应用', wake:'已模拟唤醒，未操作设备', fail:state.disabled?'达到演示阈值，已停止模拟冻结':'已记录一次模拟失败', healthy:'模拟健康检查通过，失败计数清零', reset:'已重置演示，真实执行仍关闭', balanced:'演示策略：均衡', save:'演示策略：省电', observe:'演示策略：仅观察' }; toast(messages[action]); const replacement = document.querySelector(`[data-action="${action}"]`); if (replacement && !replacement.disabled) replacement.focus(); });
  addEventListener('hashchange', () => { const dialog = document.getElementById('connection-dialog'); if (dialog.open) dialog.close(); navigate(); document.getElementById('main').focus(); scrollTo(0,0); });
  navigate();
})();
