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
  const icon = (symbol, cls = '') => `<span class="app-icon ${cls}" aria-hidden="true">${glyph(({'▤':'book','♫':'music','⌨':'keyboard','◇':'vpn'})[symbol] || 'info',24)}</span>`;
  const row = (symbol, cls, title, subtitle, status, pill = '') => `<div class="row">${icon(symbol, cls)}<div class="row-info"><strong>${title}</strong><small>${subtitle}</small></div><span class="pill ${pill}">${status}</span></div>`;
  function toast(text) { const el = document.getElementById('toast'); el.textContent = text; el.classList.add('show'); clearTimeout(timer); timer = setTimeout(() => el.classList.remove('show'), 3500); }
  const glyph = (name, size = 24) => {
    const paths = {
      overview: '<rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1.8"/><rect x="14" y="3.5" width="6.5" height="6.5" rx="1.8"/><rect x="3.5" y="14" width="6.5" height="6.5" rx="1.8"/><rect x="14" y="14" width="6.5" height="6.5" rx="1.8"/>',
      apps: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9 5l3 2 3-2M9 19l3-2 3 2M4.5 11l3-1.5-.2-3.6M19.5 13l-3 1.5.2 3.6M7.3 18.1l.2-3.6-3-1.5M16.7 5.9l-.2 3.6 3 1.5"/>',
      performance: '<path d="M3 15h4l3-9 4 13 3-8h4"/>',
      recovery: '<path d="M12 3l8 3v5c0 5-3.4 8.5-8 10-4.6-1.5-8-5-8-10V6z"/><path d="M8.5 12l2.3 2.3 4.7-4.7"/>',
      book: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/>',
      music: '<path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2.5"/><ellipse cx="17" cy="16" rx="3" ry="2.5"/>',
      keyboard: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M7 15h10"/>',
      vpn: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
      balanced: '<circle cx="12" cy="12" r="8"/><path d="M12 4v16"/>',
      save: '<path d="M20.3 14.3A8.5 8.5 0 0 1 9.7 3.7 8.5 8.5 0 1 0 20.3 14.3z"/>',
      observe: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/>',
      guard: '<path d="M12 2.7l8 3.5v5.6c0 4.4-3.4 7.8-8 10-4.6-2.2-8-5.6-8-10V6.2z"/><path d="M12 10v4.5"/>',
      power: '<path d="M12 3v8M6.3 6.5a8 8 0 1 0 11.4 0"/>',
      arrow: '<path d="M9 5l7 7-7 7"/>',
      link: '<path d="M8 8l-2 2a4.3 4.3 0 0 0 6 6l2-2M16 16l2-2a4.3 4.3 0 0 0-6-6l-2 2M9 15l6-6"/>',
      info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v6M12 7v.1"/>'
    };
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.info}</svg>`;
  };
  function overview() {
    const connected = !!diagnostics;
    const dial = `<svg viewBox="0 0 128 128" aria-hidden="true">${Array.from({length:48},(_,i)=>`<line x1="64" y1="${i%12===0?4:6}" x2="64" y2="${i%12===0?13:11}" transform="rotate(${i*7.5} 64 64)" stroke="${i===0?'#0767fa':'#7e8a9c'}" stroke-width="${i===0?1.5:.65}"/>`).join('')}<g transform="translate(42.4 42.4) scale(1.8)" fill="none" stroke="#647084" stroke-width="1.8" stroke-linecap="round"><path d="M8 8l-2 2a4.3 4.3 0 0 0 6 6l2-2M16 16l2-2a4.3 4.3 0 0 0-6-6l-2 2M9 15l6-6"/></g></svg>`;
    const seal = '<svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><circle cx="20" cy="20" r="18"/><circle cx="20" cy="20" r="14.5"/><circle cx="20" cy="20" r="10.5"/><circle cx="20" cy="20" r="3"/><circle cx="20" cy="20" r="1.6" fill="#0767fa" stroke="none"/></svg>';
    const shield = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.7l8 3.5v5.6c0 4.4-3.4 7.8-8 10-4.6-2.2-8-5.6-8-10V6.2z"/><path d="M12 10v4.5"/></svg>';
    return `<div class="console-top"><div class="home-wordmark">${seal}<h1>归藏</h1></div><span class="offline-badge"><span></span>${connected ? '只读连接' : '离线预览'}</span></div>
    <section class="device-panel" aria-label="设备连接状态"><div class="device-panel-top"><div><span class="panel-eyebrow">设备状态</span><h2>${connected ? escape(diagnostics.model) : '未连接'}</h2><p>${connected ? '能力快照已读取，真实执行仍关闭' : '连接设备后读取实时状态'}</p></div><span class="connection-dial">${dial}</span></div><div class="device-facts"><span><strong>${connected ? (diagnostics.effective_uid === 0 ? '已确认' : '不可用') : '—'}</strong>ROOT</span><span><strong>${connected ? escape(diagnostics.kernel) : '—'}</strong>内核</span><span><strong>—</strong>守护进程</span></div><button class="connection-button" data-action="${bridge.available() ? 'probe' : 'connection-help'}" ${probeBusy ? 'disabled' : ''}>${probeBusy ? '正在检测' : connected ? '刷新只读诊断' : '检查连接'}${glyph('arrow',18)}</button></section>
    <div class="console-section-heading"><h2>控制</h2><span>安全模式 ${glyph('arrow',16)}</span></div>
    <section class="control-group" aria-label="功能入口"><a href="#apps" class="control-row"><span class="control-icon">${glyph('apps')}</span><span class="control-copy"><strong>应用休眠</strong><small>冻结与唤醒</small></span><span class="control-status">未启用</span>${glyph('arrow',15)}</a><a href="#performance" class="control-row"><span class="control-icon">${glyph('performance')}</span><span class="control-copy"><strong>性能调度</strong><small>按场景管理性能</small></span><span class="control-status">仅观察</span>${glyph('arrow',15)}</a><a href="#recovery" class="control-row"><span class="control-icon">${shield}</span><span class="control-copy"><strong>启动保护</strong><small>保留安全恢复路径</small></span><span class="control-status">待验证</span>${glyph('arrow',15)}</a></section><p class="console-footnote">${glyph('info',14)}预览模式 · 设备操作未开放</p>`;
  }
  function apps() {
    return `<p class="eyebrow">应用管理 · 演示</p><h1 class="page-title">应用休眠</h1><p class="lead">仅对允许名单演示冻结与唤醒。<br>当前不会冻结真实进程。</p><section class="card"><div class="section-title first"><h2>应用名单 · 示例</h2><span class="pill neutral">${state.allowed ? '1' : '0'} 个已允许</span></div><div class="app-list"><div class="row">${icon('▤')}<div class="row-info"><strong>阅读应用</strong><small>org.example.reader · 演示</small></div><span class="pill ${state.sleeping ? '' : 'neutral'}">${state.sleeping ? '模拟休眠' : '保持活跃'}</span><button class="toggle" role="switch" aria-label="允许示例阅读应用休眠" aria-checked="${state.allowed}" data-action="allow" ${state.disabled ? 'disabled' : ''}></button></div>${row('♫', 'music', '音乐播放', '音频保护 · 不能加入休眠名单', '受保护')}${row('⌨', '', '当前输入法', '输入服务保护', '受保护')}${row('◇', 'vpn', 'VPN 连接', '网络服务保护', '受保护')}</div><div class="actions"><button class="button primary" data-action="sleep" ${!state.allowed || state.disabled || state.sleeping ? 'disabled' : ''}>模拟后台休眠</button><button class="button" data-action="wake" ${!state.sleeping ? 'disabled' : ''}>模拟前台唤醒</button></div><div class="note">${state.disabled ? '启动保护已在演示中停用模块。请到启动保护页手动重置演示。' : '真实执行器尚未开放。未来仅在身份校验、Binder 协作和可靠唤醒全部通过后开放测试。'}</div></section><div class="architecture"><section><small>01 / 识别</small><h3>身份不能猜</h3><p>校验 UID、PID、启动时间，避免误操作复用的进程。</p></section><section><small>02 / 保护</small><h3>重要任务优先</h3><p>保护信号缺失或过期，就不尝试冻结。</p></section><section><small>03 / 唤醒</small><h3>出错即退让</h3><p>解冻失败保留记录，停止新增冻结。</p></section></div>`;
  }
  function performance() {
    return `<p class="eyebrow">场景管理 · 演示</p><h1 class="page-title">场景调度</h1><p class="lead">先观察场景，再决定策略。<br>尊重系统温控，不永久超频。</p><div class="scene-grid">${[['balanced','◐','均衡','日常交互，平稳响应'],['save','☾','省电','安静待机，保留重要任务'],['observe','⌁','仅观察','了解场景，不改变参数']].map(([id,symbol,title,desc])=>`<button class="scene-option" data-action="${id}" aria-pressed="${state.mode===id}"><span>${glyph(id,26)}</span><strong>${title}</strong><small>${desc}</small></button>`).join('')}</div><div class="note warn">选择仅改变演示策略。真实设备仍为观察模式，无任何 CPU / GPU / 温控写入。</div><div class="section-title"><h2>每一步，都能解释</h2><span class="pill neutral">演示轨迹</span></div><section class="card"><ol class="timeline"><li><span>场景输入</span>前台交互、音频会话、屏幕与热状态</li><li><span>策略判断</span>过热先退让，信号未知不增强性能</li><li><span>能力验证</span>逐设备确认节点、范围与独占写入条件</li><li><span>原值快照</span>先持久化恢复记录，再允许参数改变</li><li><span>失败恢复</span>倒序恢复自己的值，保留未解决的冲突</li></ol></section>`;
  }
  function recovery() {
    return `<p class="eyebrow">安全恢复 · 演示</p><h1 class="page-title">启动保护</h1><p class="lead">异常时停止本模块，保留恢复路径。<br>无法修复所有变砖、分区损坏或数据丢失。</p><div class="split"><section class="card"><h3>连续启动失败 · 演示</h3><p>模拟本模块启动未通过健康检查，达到阈值后停止执行。</p><div class="guard-count">${[1,2,3].map(i=>`<span class="${i<=state.failures ? (state.disabled ? 'stopped' : 'filled') : ''}"></span>`).join('')}</div><div class="stat-line"><strong>${state.failures}<small> / 3</small></strong><span class="pill ${state.disabled ? 'amber' : 'neutral'}">${state.disabled ? '已自动停用（演示）' : '保护待命（演示）'}</span></div><div class="actions"><button class="button primary" data-action="fail" ${state.disabled ? 'disabled' : ''}>模拟一次失败</button><button class="button" data-action="healthy" ${state.disabled || !state.failures ? 'disabled' : ''}>模拟健康启动</button><button class="button" data-action="reset">重置演示</button></div></section><section class="card"><p class="eyebrow">安全退出</p><h3>恢复，只做必要的事</h3><ol class="timeline"><li><span>第一步</span>停止新的冻结和参数写入</li><li><span>第二步</span>解冻本模块持有的应用</li><li><span>第三步</span>恢复已记录且未被他人改写的原值</li><li><span>最后</span>保留原因，不自行重启或重新启用</li></ol></section></div><div class="note warn">真实设备若无法进入系统，需要 Root 管理器的安全模式或手动卸载。本原型没有刷入包，不会修改启动分区、清空数据或移除其他模块。</div>`;
  }
  function render() {
    document.body.dataset.view = state.page;
    document.querySelectorAll('[data-page]').forEach(el => { el.querySelector('span').innerHTML = glyph(el.dataset.page === 'recovery' ? 'guard' : el.dataset.page,22); el.lastChild.textContent = ({overview:'总览',apps:'休眠',performance:'调度',recovery:'保护'})[el.dataset.page]; const selected = el.dataset.page === state.page; el.classList.toggle('active', selected); if (selected) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
    document.getElementById('breadcrumb').textContent = titles[state.page];
    document.getElementById('main').innerHTML = ({ overview, apps, performance, recovery })[state.page]();
    document.title = `归藏 · ${titles[state.page]}`;
  }
  function navigate() { const hash = location.hash.slice(1); state.page = Object.hasOwn(titles, hash) ? hash : 'overview'; render(); }
  document.addEventListener('click', async event => { const button = event.target.closest('[data-action]'); if (!button || button.disabled) return; const action = button.dataset.action; if (action === 'connection-help') { document.getElementById('connection-dialog').showModal(); return; } if (action === 'close-connection') { document.getElementById('connection-dialog').close(); return; } if (action === 'probe') { if (probeBusy || !bridge.available()) return; probeBusy = true; probeError = ''; render(); try { diagnostics = await bridge.readCapabilities(); toast('只读诊断完成，真实执行仍关闭'); } catch (_) { diagnostics = null; probeError = '诊断未完成。请检查测试构建和管理器连接；真实执行仍关闭。'; toast('诊断失败，未启用任何设备操作'); } finally { probeBusy = false; render(); } return; } state = reduce(state, action); render(); const messages = { allow:'示例名单已更新，未操作设备', sleep:'已模拟休眠，未冻结真实应用', wake:'已模拟唤醒，未操作设备', fail:state.disabled?'达到演示阈值，已停止模拟冻结':'已记录一次模拟失败', healthy:'模拟健康检查通过，失败计数清零', reset:'已重置演示，真实执行仍关闭', balanced:'演示策略：均衡', save:'演示策略：省电', observe:'演示策略：仅观察' }; toast(messages[action]); const replacement = document.querySelector(`[data-action="${action}"]`); if (replacement && !replacement.disabled) replacement.focus(); });
  addEventListener('hashchange', () => { const dialog = document.getElementById('connection-dialog'); if (dialog.open) dialog.close(); navigate(); document.getElementById('main').focus(); scrollTo(0,0); });
  navigate();
})();
