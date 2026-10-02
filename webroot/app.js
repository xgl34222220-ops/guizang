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
  let state = initial(), timer;
  const titles = { overview: '总览', apps: '应用休眠', performance: '场景调度', recovery: '启动保护' };
  const icon = (symbol, cls = '') => `<span class="app-icon ${cls}" aria-hidden="true">${symbol}</span>`;
  const row = (symbol, cls, title, subtitle, status, pill = '') => `<div class="row">${icon(symbol, cls)}<div class="row-info"><strong>${title}</strong><small>${subtitle}</small></div><span class="pill ${pill}">${status}</span></div>`;
  function toast(text) { const el = document.getElementById('toast'); el.textContent = text; el.classList.add('show'); clearTimeout(timer); timer = setTimeout(() => el.classList.remove('show'), 3500); }
  function overview() {
    return `<section class="hero"><div><p class="eyebrow">QUIETLY IN BALANCE</p><h1>让后台安静。<br>让前台从容。</h1><p>在休眠、性能与安全之间，找到刚好的平衡。<br>从看得懂、可恢复的每一步开始。</p></div><div class="orb" aria-hidden="true"></div></section>
    <section class="metrics" aria-label="演示状态"><article class="metric"><div class="label">应用休眠 <span>↘</span></div><strong>${state.sleeping ? '01' : '00'}<small>示例应用</small></strong><p>仅处理你明确允许的应用</p></article><article class="metric"><div class="label">调度策略 <span>⌁</span></div><strong>观察<small>ONLY</small></strong><p>暂无设备参数写入</p></article><article class="metric"><div class="label">启动保护 <span>◇</span></div><strong>${state.disabled ? '已停用' : '待验证'}</strong><p>连续失败 ${state.failures} / 3 · 演示</p></article></section>
    <div class="section-title"><h2>保持活跃的，始终活跃</h2><a class="text-link" href="#apps">查看应用 <span>↗</span></a></div>
    <div class="split"><section class="card">${row('♫', 'music', '音乐播放', '音频会话优先，不参与休眠', '受保护')}${row('⌨', '', '当前输入法', '输入随时响应', '受保护')}${row('◇', 'vpn', 'VPN 连接', '保留网络连接服务', '受保护')}<div class="protection"><span class="shield">◇</span>前台、通话、录音与无障碍服务同样受到保护。<br>保护信号未知时，停止冻结。</div></section><section class="card"><p class="eyebrow">DEVICE READINESS</p><h3>你的设备，逐一适配</h3><p>不按机型猜参数。内核能力与系统行为均需实测。</p><div class="device-row">一加 15 <span>待实机核验</span></div><div class="device-row">Redmi K80 至尊版 <span>待实机核验</span></div><div class="note">当前未连接任何设备。虚拟机验证也不能替代两台实机的温控、功耗与后台测试。</div></section></div>`;
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
    document.querySelectorAll('[data-page]').forEach(el => { const selected = el.dataset.page === state.page; el.classList.toggle('active', selected); if (selected) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
    document.getElementById('breadcrumb').textContent = titles[state.page];
    document.getElementById('main').innerHTML = ({ overview, apps, performance, recovery })[state.page]();
    document.title = `归藏 · ${titles[state.page]}`;
  }
  function navigate() { const hash = location.hash.slice(1); state.page = Object.hasOwn(titles, hash) ? hash : 'overview'; render(); }
  document.addEventListener('click', event => { const button = event.target.closest('[data-action]'); if (!button || button.disabled) return; const action = button.dataset.action; state = reduce(state, action); render(); const messages = { allow:'示例名单已更新，未操作设备', sleep:'已模拟休眠，未冻结真实应用', wake:'已模拟唤醒，未操作设备', fail:state.disabled?'达到演示阈值，已停止模拟冻结':'已记录一次模拟失败', healthy:'模拟健康检查通过，失败计数清零', reset:'已重置演示，真实执行仍关闭', balanced:'演示策略：均衡', save:'演示策略：省电', observe:'演示策略：仅观察' }; toast(messages[action]); const replacement = document.querySelector(`[data-action="${action}"]`); if (replacement && !replacement.disabled) replacement.focus(); });
  addEventListener('hashchange', () => { navigate(); document.getElementById('main').focus(); scrollTo(0,0); });
  navigate();
})();
