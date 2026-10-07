(function () {
  'use strict';

  var state = { catalog: null, endpoints: [], current: null, lastRequest: null, socket: null };
  var marketMode = false;
  var $ = function (id) { return document.getElementById(id); };
  var requestBase = 'http://127.0.0.1:8080';

  function esc(value) {
    if (typeof window.escHtml === 'function') return window.escHtml(value == null ? '' : String(value));
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function normalizeBaseUrl(value) {
    var text = String(value || '').trim().replace(/^wss?:/i, 'http:');
    if (!text) return '';
    try { return new URL(text, window.location.href).origin; }
    catch (_) { return text.replace(/\/+$/, ''); }
  }

  function baseUrl() {
    var candidates = marketMode ? ['marketRequestUrl', 'marketWsAddress', 'legacyRequestUrl'] : ['legacyRequestUrl', 'marketRequestUrl', 'marketWsAddress'];
    for (var i = 0; i < candidates.length; i++) {
      var input = $(candidates[i]);
      var value = input ? normalizeBaseUrl(input.value) : '';
      if (value) { requestBase = value; return value; }
    }
    return requestBase;
  }

  function setBaseUrl(value) {
    var normalized = normalizeBaseUrl(value);
    if (normalized) requestBase = normalized;
  }

  function requestAddressHtml(id, value, hint) {
    return '<div class="market-connection-row"><div class="market-connection-label"><code>地址</code><span>' + esc(hint || '包含协议、端口和接口路径') + '</span></div><input id="' + esc(id) + '" aria-label="请求地址" value="' + esc(value || '') + '"></div>';
  }

  function marketStatus(text, kind) {
    var status = $('marketPermissionStatus');
    if (status) {
      status.textContent = text;
      status.className = 'market-status' + (kind ? ' ' + kind : '');
    }
  }

  function updateMarketStatus() {
    var statusText = state.catalog ? '已加载 ' + state.endpoints.length + ' 个接口' : '目录待加载';
    marketStatus(statusText, '');
    var count = $('marketEndpointCount');
    if (count) count.textContent = String(state.endpoints.length);
  }

  function setMarketSelection(name, path) {
    var title = $('marketApiName');
    var route = $('marketApiPath');
    if (title) title.textContent = name || 'd6';
    if (route) route.textContent = path || '选择左侧行情接口';
  }

  function setProductActive(key) {
    document.querySelectorAll('.product-nav-button').forEach(function (button) {
      button.classList.remove('product-active', 'market-active');
    });
    var target = key === 'all' ? $('marketAllButton') : document.querySelector('.product-nav-button[data-product="' + key + '"]');
    if (target) {
      target.classList.add('product-active');
      if (key === 'd6') target.classList.add('market-active');
    }
  }

  function selectProductWorkspace(route) {
    leaveMarketWorkspace();
    setProductActive(route);
    var search = $('searchInput');
    if (search) { search.placeholder = '搜索接口...'; search.oninput = window.filterNav; search.value = ''; }
    if (typeof window.renderNav === 'function') window.renderNav(route);
    var section = document.querySelector('.market-category[data-route-prefix="' + route + '"]');
    if (!section) return;
    section.scrollIntoView({ block: 'start' });
    var first = section.querySelector('.api-item');
    if (first) first.click();
  }

  function leaveMarketWorkspace() {
    if (!marketMode) return;
    marketMode = false;
    if (state.socket) { try { state.socket.close(); } catch (_) {} state.socket = null; }
    var view = $('marketView');
    if (view) view.style.display = 'none';
    document.querySelectorAll('.main > .api-bar, .main > .market-layout').forEach(function (el) { el.style.display = ''; });
    var search = $('searchInput');
    if (search) { search.placeholder = '搜索接口...'; search.oninput = window.filterNav; search.value = ''; }
    var nav = $('nav');
    if (nav) nav.classList.remove('market-mode');
    var button = $('marketNavButton');
    if (button) button.classList.remove('market-active');
    setProductActive('all');
    if (typeof window.renderNav === 'function') window.renderNav();
  }

  function selectLegacyWorkspace() {
    leaveMarketWorkspace();
    setProductActive('all');
    if (typeof window.renderNav === 'function') window.renderNav();
  }

  function selectMarketWorkspace() {
    if (typeof window.wsCloseAll === 'function') window.wsCloseAll();
    marketMode = true;
    document.querySelectorAll('.main > .api-bar, .main > .market-layout').forEach(function (el) { el.style.display = 'none'; });
    var view = $('marketView');
    if (view) view.style.display = 'flex';
    var button = $('marketNavButton');
    if (button) button.classList.add('market-active');
    setProductActive('d6');
    var search = $('searchInput');
    if (search) { search.placeholder = '搜索行情接口、路径或描述...'; search.oninput = renderList; search.value = ''; }
    var nav = $('nav');
    if (nav) nav.classList.add('market-mode');
    if (!state.current) setMarketSelection('d6', '选择左侧行情接口');
    updateMarketStatus();
    renderList();
    if (!state.catalog) loadCatalog();
  }

  function catalogUrl() {
    var origin = window.location && window.location.origin;
    return origin && origin !== 'null' ? origin + '/api/catalog' : '/api/catalog';
  }

  function marketCatalogPayload(data) {
    return data && data.market && typeof data.market === 'object' ? data.market : (data || {});
  }

  function applyCatalog(data) {
    var market = marketCatalogPayload(data);
    state.catalog = market;
    state.endpoints = Array.isArray(market.endpoints) ? market.endpoints : [];
    if (typeof window.updateMethodGalleryMarketItems === 'function') window.updateMethodGalleryMarketItems(state.endpoints);
  }

  function renderLoadedMarketCatalog() {
    renderList();
    updateMarketStatus();
    if (state.endpoints.length) {
      var selected = state.current ? state.endpoints.findIndex(function (item) { return item.path === state.current.path && item.method === state.current.method; }) : 0;
      selectEndpoint(selected >= 0 ? selected : 0);
    }
  }

  function loadCatalog() {
    var base = baseUrl();
    if (!base) { marketStatus('代理地址为空', 'bad'); return; }
    setBaseUrl(base);
    marketStatus('加载目录中...', '');
    fetch(catalogUrl() + '?_' + Date.now(), { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) {
          var error = new Error('HTTP ' + response.status);
          error.status = response.status;
          throw error;
        }
        return response.json();
      })
      .then(function (data) {
        applyCatalog(data);
        renderLoadedMarketCatalog();
      })
      .catch(function (error) {
        var message = error.status === 403 ? '目录被旧版代理拦截，请重启客户端后重试' : error.status === 401 ? '请先登录并完成认证' : '无法连接行情代理，请确认服务已启动';
        marketStatus(error.status === 403 ? '代理在线 · 未开通' : '目录加载失败', error.status === 403 ? 'warn' : 'bad');
        var list = $('nav');
        if (list) list.innerHTML = '<button class="market-endpoint" onclick="marketRenderWs()"><div class="market-endpoint-line"><span class="market-method ws">WS</span><span class="market-endpoint-name">实时行情 WebSocket</span></div><span class="market-endpoint-path">/d6/market/ws/quote</span></button><div class="market-empty"><strong>' + esc(message) + '</strong><span>目录本身公开；请求数据仍会按 d6 授权校验。</span></div>';
        var editor = $('marketEditor');
        if (editor) editor.innerHTML = '<div class="market-empty"><strong>' + esc(message) + '</strong><span>请确认客户端已启动；目录公开，接口请求仍需 d6 授权。</span></div>';
      });
  }

  function endpointGroup(endpoint) { return endpoint.category || '行情数据'; }

  function methodBadge(method) {
    var cls = String(method || '').toLowerCase();
    return '<span class="market-method ' + esc(cls) + '">' + esc(method || 'GET') + '</span>';
  }

  // 所有 HTTP/WS 工作区共用这一套编辑器和响应区骨架；业务差异只通过字段、请求体和操作按钮注入。
  function renderUnifiedWorkspace(spec) {
    var editor = $(spec.editorId);
    var response = $(spec.responseId);
    if (!editor || !response) return;
    var fields = spec.params ? unifiedParamRows(spec.params, spec.paramKind) : (spec.fieldsHtml || '');
    if (!fields) fields = '<tr><td colspan="2" style="color:#8ea1bd">暂无固定参数，可直接编辑请求参数或请求体。</td></tr>';
    var description = spec.description ? '<div class="market-description">用途：' + esc(spec.description) + '</div>' : '';
    var connection = spec.connectionHtml || '';
    var actions = spec.actionsHtml ? '<div class="market-actions"' + (spec.actionsId ? ' id="' + esc(spec.actionsId) + '"' : '') + '>' + spec.actionsHtml + '</div>' : '';
    var sample = spec.sampleHtml || '';
    editor.innerHTML = '<div class="market-editor-head">' + methodBadge(spec.method) + '<span>' + esc(spec.name || '接口') + '</span><small>' + esc(spec.headNote || '入参') + '</small>' + (spec.headerExtraHtml || '') + '</div>' +
      connection +
      description +
      '<div class="market-editor-scroll"' + (spec.paramsId ? ' id="' + esc(spec.paramsId) + '"' : '') + '><table><tbody>' + fields + '</tbody></table></div>' +
      (spec.bodyHtml || '') + actions + (spec.infoHtml ? '<div class="market-info"' + (spec.infoId ? ' id="' + esc(spec.infoId) + '"' : '') + '>' + spec.infoHtml + '</div>' : '') + sample;
    response.innerHTML = '<div class="market-response-head"><span>' + esc(spec.responseTitle || '响应结果') + '</span><small' + (spec.responseMetaId ? ' id="' + esc(spec.responseMetaId) + '"' : '') + '>—</small></div><pre' + (spec.responseBodyId ? ' id="' + esc(spec.responseBodyId) + '"' : '') + ' class="market-response-body' + (spec.responseBodyClass ? ' ' + esc(spec.responseBodyClass) : '') + '">' + esc(spec.responseInitial || '点击“发送请求”查看结果') + '</pre><div class="market-response-tip">' + esc(spec.responseTip || '发送请求后显示结果。') + '</div>';
  }

  function unifiedParamRows(params, kind) {
    var today = new Date();
    var td = today.getFullYear() + ('0' + (today.getMonth() + 1)).slice(-2) + ('0' + today.getDate()).slice(-2);
    return (params || []).map(function (p, i) {
      if (p.section) return '<tr class="ws-section-row"><th colspan="2">' + esc(p.section) + '</th></tr>';
      var rowKind = p.kind || kind;
      var key = String(p.key == null ? (p.name == null ? '' : p.name) : p.key);
      var rawValue = p.value != null ? String(p.value) : (p.default == null ? '' : String(p.default));
      if (rowKind === 'legacy') {
        if (key.toLowerCase() === 'date' && !rawValue && p.autoToday !== false) rawValue = td;
        if (key.toLowerCase() === 'id' && !rawValue) rawValue = 'SZ002306';
      }
      var desc = p.desc || p.description || '';
      var note = (p.required ? '必填' : '可选') + (desc ? '；' + publicText(desc) : '');
      if (rowKind === 'market' && p.default != null && String(p.default) !== '') note += '；默认：' + publicText(p.default);
      var internal = rowKind === 'legacy' && p.internal === true;
      var isBodyField = rowKind === 'market-body';
      var inputValue = isBodyField ? (p.value == null ? '' : (typeof p.value === 'object' ? JSON.stringify(p.value) : String(p.value))) : (rowKind === 'legacy' ? (internal ? '当前接口自动注入' : publicText(rawValue)) : (p.displayValue != null ? publicText(p.displayValue) : publicText(rawValue)));
      var source = internal ? 'legacy-internal' : (isBodyField ? 'market-body' : (rowKind === 'legacy' ? 'legacy' : 'market'));
      var onInput = rowKind === 'legacy' && !internal ? ' oninput="this.dataset.changed=\'1\';buildBody()"' : (isBodyField ? ' oninput="marketBodyFieldChanged(this)"' : '');
      var inputAttrs = internal ? ' class="market-param-internal" readonly aria-readonly="true"' : (isBodyField ? ' class="market-param-body"' : ' placeholder="可选"');
      return '<tr><th><code>' + esc(publicText(key)) + '</code><span>' + esc(note) + '</span></th><td><input data-param-source="' + source + '" data-param-key="' + esc(key) + '" data-raw-value="' + esc(rawValue) + '" value="' + esc(inputValue) + '"' + inputAttrs + onInput + '></td></tr>';
    }).join('');
  }

  // 旧版实时通道仍由主页面动态生成参数；在进入工作区后统一转换为
  // 同一套“参数名—说明—值”结构，避免 d101/d201/d202 再创建旧四列表格。
  function normalizeLegacyWsParams() {
    var host = $('paramsTable');
    if (!host) return;
    var source = null;
    Array.prototype.some.call(host.children, function (child) {
      if (String(child.tagName).toLowerCase() === 'table') { source = child; return true; }
      return false;
    });
    if (!source) source = host.querySelector('table');
    if (!source) return;
    var html = '';
    Array.prototype.forEach.call(source.querySelectorAll('tr'), function (row, index) {
      var cells = row.cells;
      if (!cells.length) return;
      var firstText = String(cells[0].textContent || '').trim();
      if (index === 0 && firstText === '参数') return;
      if (cells.length === 1 || Number(cells[0].colSpan || 1) > 1) {
        html += '<tr class="ws-section-row"><th colspan="2">' + cells[0].innerHTML + '</th></tr>';
        return;
      }
      var key = firstText;
      var required = cells[1] ? String(cells[1].textContent || '').trim() : '';
      var description = cells[3] ? String(cells[3].textContent || '').trim() : '';
      var note = required + (description ? '；' + description : '');
      var attrs = row.id ? ' id="' + esc(row.id) + '"' : '';
      var style = row.getAttribute('style');
      if (style) attrs += ' style="' + esc(style) + '"';
      html += '<tr' + attrs + '><th><code>' + esc(key) + '</code><span>' + esc(note) + '</span></th><td>' + (cells[2] ? cells[2].innerHTML : '') + '</td></tr>';
    });
    host.innerHTML = '<table><tbody>' + html + '</tbody></table>';
  }

  function renderLegacyHttpEndpoint(spec) {
    var title = publicText((spec.groupName || '') + '_' + (spec.apiName || '接口'));
    var path = spec.prefix + '/' + String(spec.hostVar || '').replace(/^\/+/, '');
    var method = String(spec.method || 'POST').toUpperCase();
    var sample = spec.response && spec.response !== '(空)' ? String(spec.response) : (spec.response || '(空)');
    var params = spec.params || [];
    renderUnifiedWorkspace({
      editorId: 'legacyEditor', responseId: 'legacyResponse', paramsId: 'paramsTable', method: method, name: title,
      description: spec.groupName || '接口参数', params: params, paramKind: 'legacy', headNote: '入参',
      connectionHtml: requestAddressHtml('legacyRequestUrl', baseUrl() + path, 'HTTP 请求地址；可直接修改代理地址、端口或本地路径'),
      headerExtraHtml: '<span class="legacy-feedback" onclick="openFeedback()">反馈</span>',
      bodyHtml: '<div class="market-body"><label id="legacyBodyLabel">完整请求体 · application/x-www-form-urlencoded（可直接复制）</label><textarea id="rawBody" oninput="syncFromBody()"></textarea></div>',
      actionsId: 'legacyHttpActions', actionsHtml: '<button class="market-btn green" onclick="sendRequest()">发送请求</button><button class="market-btn" onclick="resetLegacyRequest()">重置</button><button class="market-btn" onclick="copyLegacyRequest()">复制 curl</button>',
      infoHtml: '路径：<code>' + esc(path) + '</code><br>请求方式：' + esc(method) + '；下面是完整真实请求参数，修改参数表或请求体后即可直接测试。',
      responseTitle: '响应结果', responseMetaId: 'respStats', responseBodyId: 'responseBody', responseInitial: sample, responseTip: '左侧为接口入参；发送请求后显示实际响应。'
    });
  }

  function renderLegacyWsShell(name, description, path) {
    var wsPath = path || '/d101';
    var address = baseUrl().replace(/^http:/, 'ws:').replace(/^https:/, 'wss:') + wsPath;
    renderUnifiedWorkspace({
      editorId: 'legacyEditor', responseId: 'legacyResponse', paramsId: 'paramsTable', method: 'WS', name: name || '实时推送', description: description || '连接后发送订阅命令。',
      connectionHtml: requestAddressHtml('legacyRequestUrl', address, 'WebSocket 地址；包含协议、端口和推送路径'),
      fieldsHtml: '<tr><td colspan="2" style="color:#8ea1bd">选择推送类型后显示对应参数。</td></tr>',
      bodyHtml: '<div class="market-body"><label>JSON 命令</label><textarea id="rawBody" oninput="syncFromBody()"></textarea><div id="wsBatchHint" style="display:none;font-size:9px;color:#e9c445;margin-top:2px">⚡ 支持批量订阅 — 用数组同时发送多个命令</div></div>',
      actionsId: 'legacyWsActions', actionsHtml: '<span id="wsBodyBtns" class="market-ws-command-actions"><button class="market-btn green" id="wsLocalConnect" onclick="wsConnectCurrent()">连接</button><button class="market-btn primary" onclick="wsSendCmd()">发送命令</button><button class="market-btn" id="wsLocalDisconnect" onclick="wsDisconnectCurrent()" style="display:none">断开</button><button class="market-btn" onclick="wsClearLog()">清空</button><span class="market-ws-action-status">状态：<b id="wsLocalStatus">未连接</b>　消息：<b id="wsLocalCount">0</b></span></span>',
      infoHtml: '连接状态和消息计数显示在当前接口底部；消息会实时显示在右侧。', responseTitle: '实时帧', responseBodyId: 'responseBody', responseInitial: '等待连接…', responseTip: '连接 WebSocket 后，右侧显示实时消息。',
      sampleHtml: '<div class="sample-section" id="sampleSection" style="display:none"><div class="sample-header" onclick="this.classList.toggle(\'collapsed\')"><span id="sampleTitle">响应参考</span><span class="arrow">▼</span></div><div class="sample-body" id="sampleBody"></div></div>'
    });
  }

  function renderList() {
    var list = $('nav');
    if (!list) return;
    if (!state.endpoints.length) {
      list.innerHTML = '<button class="market-endpoint" onclick="marketRenderWs()"><div class="market-endpoint-line"><span class="market-method ws">WS</span><span class="market-endpoint-name">实时行情 WebSocket</span></div><span class="market-endpoint-path">/d6/market/ws/quote</span></button><div class="market-empty" style="padding:32px 10px"><strong>d6</strong><span>HTTP 目录暂不可用；WebSocket 仍可进入测试。</span></div>';
      return;
    }
    var search = $('searchInput');
    var query = search ? search.value.trim().toLowerCase() : '';
    var groups = {};
    state.endpoints.forEach(function (endpoint, index) {
      var text = [endpoint.method, endpoint.name, endpoint.category, endpoint.description, endpoint.path].join(' ').toLowerCase();
      if (query && text.indexOf(query) < 0) return;
      var group = endpointGroup(endpoint);
      if (!groups[group]) groups[group] = [];
      groups[group].push({ endpoint: endpoint, index: index });
    });
    var html = '<button class="market-endpoint" onclick="marketRenderWs()"><div class="market-endpoint-line"><span class="market-method ws">WS</span><span class="market-endpoint-name">实时行情 WebSocket</span></div><span class="market-endpoint-path">/d6/market/ws/quote · 2001/201/801/501/504</span></button>';
    var shown = 0;
    Object.keys(groups).sort().forEach(function (groupName) {
      html += '<section class="market-category"><div class="market-category-title">' + esc(groupName) + '</div>';
      groups[groupName].forEach(function (item) {
        shown++;
        var e = item.endpoint;
        html += '<button class="market-endpoint' + (state.current === e ? ' active' : '') + '" onclick="marketSelectEndpoint(' + item.index + ')"><div class="market-endpoint-line">' + methodBadge(e.method) + '<span class="market-endpoint-name">' + esc(e.name || e.description || e.path) + '</span></div><span class="market-endpoint-path">' + esc(e.path) + '</span></button>';
      });
      html += '</section>';
    });
    if (!shown) html += '<div class="market-empty" style="padding:32px 10px">没有匹配的行情接口</div>';
    list.innerHTML = html;
    var count = $('marketEndpointCount');
    if (count) count.textContent = String(state.endpoints.length);
  }

  function selectEndpoint(index) {
    if (index < 0 || index >= state.endpoints.length) return;
    state.current = state.endpoints[index];
    renderList();
    renderEndpoint();
  }

  function renderEndpoint() {
    var current = state.current;
    if (!current || !$('marketEditor') || !$('marketResponse')) return;
    var queryParams = (current.query || []).map(function (field) {
      return { name: field.name, description: field.description, default: field.default, required: field.required };
    });
    var bodyParams = current.body && Array.isArray(current.body.fields) ? current.body.fields.map(function (field) {
      var example = current.body.example && Object.prototype.hasOwnProperty.call(current.body.example, field.name)
        ? current.body.example[field.name] : '';
      return { name: field.name, description: field.description, required: field.required, value: example, kind: 'market-body' };
    }) : [];
    var params = queryParams.slice();
    if (bodyParams.length) {
      params.push({ section: 'JSON 请求体字段（下方编辑器可直接修改）' });
      params = params.concat(bodyParams);
    }
    var body = current.body ? JSON.stringify(current.body.example || {}, null, 2) : '';
    var name = current.name || current.description || '行情接口';
    var responseMeta = current.response || {};
    var responseFields = Array.isArray(responseMeta.dataFields) ? responseMeta.dataFields.join('、') : '';
    setMarketSelection(name, current.path);
    updateMarketStatus();
    renderUnifiedWorkspace({
      editorId: 'marketEditor', responseId: 'marketResponse', method: current.method, name: name,
      description: current.description || '', params: params, paramKind: 'market',
      connectionHtml: requestAddressHtml('marketRequestUrl', baseUrl() + current.path, 'HTTP 请求地址；可直接修改代理地址、端口或本地路径'),
      bodyHtml: current.body ? '<div class="market-body"><label>JSON 请求体（可直接编辑；上方字段会同步更新）</label><textarea id="marketBodyEditor" oninput="syncMarketBodyFieldsFromEditor()" spellcheck="false">' + esc(body) + '</textarea></div>' : '',
      actionsHtml: '<button class="market-btn green" onclick="marketSendRequest()">发送请求</button><button class="market-btn" onclick="marketRenderEndpoint()">重置</button><button class="market-btn" onclick="marketCopyRequest()">复制 curl</button>',
      infoId: 'marketRequestInfo', infoHtml: '路径：<code>' + esc(current.path) + '</code>' + (responseMeta.hint ? '<br>响应：' + esc(responseMeta.hint) : '') + (responseFields ? '<br>字段：' + esc(responseFields) : '') + '<br>签名、时间戳和必要请求头由代理自动生成。',
      responseMetaId: 'marketResponseMeta', responseBodyId: 'marketResponseBody', responseInitial: '点击“发送请求”查看结果', responseTip: 'HTTP 响应保持 JSON 结构；未授权会返回 HTTP 403。常见数据字段以目录和实际响应为准。'
    });
  }

  function marketBodyFieldChanged(input) {
    var editor = $('marketBodyEditor');
    if (!editor || !input) return;
    var body = {};
    try {
      var text = editor.value.trim();
      body = text ? JSON.parse(text) : {};
      if (!body || typeof body !== 'object' || Array.isArray(body)) body = {};
    } catch (_) { body = {}; }
    var key = input.getAttribute('data-param-key');
    var value = input.value.trim();
    if (!value) delete body[key];
    else {
      try { body[key] = JSON.parse(value); }
      catch (_) { body[key] = value; }
    }
    editor.value = JSON.stringify(body, null, 2);
  }

  function syncMarketBodyFieldsFromEditor() {
    var editor = $('marketBodyEditor');
    if (!editor) return;
    var body;
    try {
      body = JSON.parse(editor.value || '{}');
      if (!body || typeof body !== 'object' || Array.isArray(body)) return;
    } catch (_) { return; }
    document.querySelectorAll('#marketEditor [data-param-source="market-body"]').forEach(function (input) {
      var key = input.getAttribute('data-param-key');
      var value = body[key];
      input.value = value == null ? '' : (typeof value === 'object' ? JSON.stringify(value) : String(value));
    });
  }

  function buildRequest() {
    if (!state.current) throw new Error('请先选择行情接口');
    var addressInput = $('marketRequestUrl');
    var url = addressInput && addressInput.value.trim() ? addressInput.value.trim() : baseUrl() + state.current.path;
    var params = new URLSearchParams();
    document.querySelectorAll('#marketEditor [data-param-source="market"]').forEach(function (input) {
      if (input.value.trim()) params.append(input.getAttribute('data-param-key'), input.value.trim());
    });
    if (state.current.method === 'GET' && params.toString()) url += (url.indexOf('?') >= 0 ? '&' : '?') + params.toString();
    var options = { method: state.current.method, headers: { Accept: 'application/json, text/plain, */*' } };
    if (state.current.method === 'POST') {
      var bodyEditor = $('marketBodyEditor');
      var body = bodyEditor ? bodyEditor.value.trim() : '';
      try { options.body = JSON.stringify(body ? JSON.parse(body) : {}); } catch (error) { throw new Error('JSON 请求体格式错误：' + error.message); }
      options.headers['Content-Type'] = 'application/json';
    }
    return { url: url, options: options };
  }

  function marketSendRequest() {
    var request;
    try { request = buildRequest(); } catch (error) { marketShowResponse(error.message, true, '参数错误'); return; }
    state.lastRequest = request;
    var pre = $('marketResponseBody');
    var meta = $('marketResponseMeta');
    var info = $('marketRequestInfo');
    if (!pre || !meta) return;
    pre.className = ''; pre.textContent = '请求中…'; meta.textContent = '请求中…';
    if (info) info.innerHTML = '请求地址：<code>' + esc(request.url) + '</code>' + (request.options.body ? '<br>请求体：<code>' + esc(request.options.body) + '</code>' : '');
    var started = performance.now();
    fetch(request.url, request.options).then(function (response) {
      return response.text().then(function (text) {
        var elapsed = Math.round(performance.now() - started);
        var output = text;
        try { output = JSON.stringify(JSON.parse(text), null, 2); } catch (_) {}
        meta.textContent = 'HTTP ' + response.status + ' · ' + elapsed + 'ms · ' + text.length + 'B';
        pre.className = response.ok ? '' : 'error'; pre.textContent = output || '(空响应)';
      });
    }).catch(function (error) { marketShowResponse(error.message, true, '请求失败'); });
  }

  function marketShowResponse(message, isError, meta) {
    var pre = $('marketResponseBody'); if (pre) { pre.className = isError ? 'error' : ''; pre.textContent = message; }
    var status = $('marketResponseMeta'); if (status) status.textContent = meta || '';
  }

  function curlDoubleQuote(value) {
    return '"' + String(value == null ? '' : value).replace(/(["\\])/g, '\\$1') + '"';
  }

  function curlSingleQuote(value) {
    // Single-quoted data works in PowerShell, bash and Git Bash.  Escape an
    // embedded apostrophe using the standard shell quote-break sequence.
    return "'" + String(value == null ? '' : value).replace(/'/g, "'\\''") + "'";
  }

  function marketCurlText(request) {
    var options = request.options || {};
    var text = 'curl.exe -i ' + curlDoubleQuote(request.url);
    var method = String(options.method || 'GET').toUpperCase();
    if (method !== 'GET') text += ' -X ' + method;
    Object.keys(options.headers || {}).forEach(function (key) {
      text += ' -H ' + curlDoubleQuote(key + ': ' + options.headers[key]);
    });
    if (options.body !== undefined && options.body !== null) {
      text += ' --data-raw ' + curlSingleQuote(options.body);
    }
    return text;
  }

  function marketCopyRequest() {
    var request;
    try { request = buildRequest(); }
    catch (error) { marketShowResponse(error.message, true, '参数错误'); return; }
    state.lastRequest = request;
    var text = marketCurlText(request);
    var done = function () { marketStatus('请求已复制', 'ok'); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done).catch(function () { window.prompt('复制下面的请求：', text); });
    else window.prompt('复制下面的请求：', text);
  }

  function wsExample(type) {
    if (type === '201') return { Header: { FrameId: 0, GroupId: 0, ModelId: 0, Length: 0, RawLength: 0, No: 0, MsgType: 201, Info: 0 }, Body: { key: { oldmarketcode: 'sz', code: '300052' }, level: 2 } };
    if (type === '801') return { Header: { FrameId: 0, GroupId: 0, ModelId: 0, Length: 0, RawLength: 0, No: 6, MsgType: 801, Info: 0 }, Body: { key: { oldmarketcode: 'sz', code: '300052' }, num: 50, timestamp: true } };
    if (type === '501') return { Header: { FrameId: 0, GroupId: 0, ModelId: 0, Length: 0, RawLength: 0, No: 9, MsgType: 501, Info: 0 }, Body: { key: { oldmarketcode: 'sz', code: '300052' }, pushflag: true, timestamp: true, nopushjh: true } };
    if (type === '504') return { Header: { FrameId: 0, GroupId: 0, ModelId: 0, Length: 0, RawLength: 0, No: 10, MsgType: 504, Info: 0 }, Body: { key: { oldmarketcode: 'sz', code: '300052' }, pushflag: true, timestamp: true } };
    return { Header: { FrameId: 0, GroupId: 0, ModelId: 0, Length: 0, RawLength: 0, No: 0, MsgType: 2001, Info: 0 }, Body: { info: { paramtype: 2, stockid: [{ marketid: 1, code: '000001' }, { marketid: 0, code: '399001' }, { marketid: 0, code: '399006' }] }, sortfield: 0, order: true, end: 3, respfield: [10, 11, 96, 97, 98] } };
  }

  function marketRenderWs() {
    if (state.socket) { try { state.socket.close(); } catch (_) {} state.socket = null; }
    if (!$('marketEditor') || !$('marketResponse')) return;
    setMarketSelection('实时行情 WebSocket', '/d6/market/ws/quote');
    updateMarketStatus();
    var address = baseUrl().replace(/^http:/, 'ws:').replace(/^https:/, 'wss:') + '/d6/market/ws/quote';
    renderUnifiedWorkspace({
      editorId: 'marketEditor', responseId: 'marketResponse', paramsId: 'marketWsParams', method: 'WS', name: '实时行情 WebSocket', headNote: '连接与订阅',
      fieldsHtml: '<tr><th><code>地址</code><span>代理自动完成行情鉴权</span></th><td><input id="marketWsAddress" value="' + esc(address) + '"></td></tr><tr><th><code>消息类型</code><span>2001 指数；201 快照；801 分时；501/504 推送</span></th><td><select id="marketWsType"><option value="2001">2001 指数/列表</option><option value="201">201 个股快照</option><option value="801">801 分时成交</option><option value="501">501 盘口推送</option><option value="504">504 扩展推送</option></td></tr>',
      bodyHtml: '<div class="market-body"><label>JSON 消息</label><textarea class="market-ws-message" id="marketWsMessage" spellcheck="false">' + esc(JSON.stringify(wsExample('2001'), null, 2)) + '</textarea></div>',
      actionsHtml: '<span class="market-ws-command-actions"><button class="market-btn green" id="marketWsConnect">连接</button><button class="market-btn primary" id="marketWsSend">发送订阅</button><button class="market-btn" id="marketWsClose" style="display:none">断开</button><button class="market-btn" id="marketWsClear">清空</button><span class="market-ws-action-status">状态：<b id="marketWsActionState">未连接</b></span></span>',
      infoHtml: '连接成功后发送 Header/Body JSON；不要填写 Token。连接状态和实时帧显示在右侧。',
      responseTitle: '实时帧', responseMetaId: 'marketWsState', responseBodyId: 'marketWsOutput', responseBodyClass: 'market-ws-output', responseInitial: '等待连接…', responseTip: '常见字段：Body.data[].base/newprice/yclose、Body.hq.newprice/mmp/zhangdief。'
    });
    $('marketWsType').onchange = function () { $('marketWsMessage').value = JSON.stringify(wsExample($('marketWsType').value), null, 2); };
    marketWsRenderFieldRows($('marketWsType').value);
    $('marketWsType').addEventListener('change', function () { marketWsRenderFieldRows($('marketWsType').value); });
    marketWsSetState('未连接');
    marketWsSetControls(false);
    $('marketWsConnect').onclick = marketWsConnect;
    $('marketWsSend').onclick = marketWsSend;
    $('marketWsClose').onclick = function () { if (state.socket) state.socket.close(); else marketWsSetState('已断开'); };
    $('marketWsClear').onclick = function () { $('marketWsOutput').textContent = ''; };
  }

  function wsLog(value, error) {
    var output = $('marketWsOutput'); if (!output) return;
    var line = document.createElement('div'); line.className = 'market-ws-line' + (error ? ' error' : '');
    var text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    line.innerHTML = '<span class="market-ws-time">[' + new Date().toLocaleTimeString() + ']</span> ' + esc(text);
    output.appendChild(line); output.scrollTop = output.scrollHeight;
  }

  function marketWsSetState(value) {
    if ($('marketWsState')) $('marketWsState').textContent = value;
    if ($('marketWsActionState')) $('marketWsActionState').textContent = value;
  }

  function marketWsSetControls(connected) {
    if ($('marketWsConnect')) $('marketWsConnect').style.display = connected ? 'none' : '';
    if ($('marketWsClose')) $('marketWsClose').style.display = connected ? '' : 'none';
  }

  function marketWsFieldDefinitions(type) {
    var common = [{ key: 'Header.MsgType', value: type, desc: '消息类型编号；与上方选择保持一致' }];
    if (type === '201') return common.concat([
      { key: 'Body.key.oldmarketcode', value: 'sz', desc: '市场简称；sz 深圳，sh 上海' },
      { key: 'Body.key.code', value: '300052', desc: '股票代码；不带市场前缀' },
      { key: 'Body.level', value: 2, desc: '行情档位；2 表示盘口档位' }
    ]);
    if (type === '801') return common.concat([
      { key: 'Body.key.oldmarketcode', value: 'sz', desc: '市场简称；sz 深圳，sh 上海' },
      { key: 'Body.key.code', value: '300052', desc: '股票代码；不带市场前缀' },
      { key: 'Body.num', value: 50, desc: '返回成交条数' },
      { key: 'Body.timestamp', value: true, desc: '是否返回时间戳' }
    ]);
    if (type === '501') return common.concat([
      { key: 'Body.key.oldmarketcode', value: 'sz', desc: '市场简称；sz 深圳，sh 上海' },
      { key: 'Body.key.code', value: '300052', desc: '股票代码；不带市场前缀' },
      { key: 'Body.pushflag', value: true, desc: '是否持续推送' },
      { key: 'Body.timestamp', value: true, desc: '是否返回时间戳' },
      { key: 'Body.nopushjh', value: true, desc: '是否关闭组合推送' }
    ]);
    if (type === '504') return common.concat([
      { key: 'Body.key.oldmarketcode', value: 'sz', desc: '市场简称；sz 深圳，sh 上海' },
      { key: 'Body.key.code', value: '300052', desc: '股票代码；不带市场前缀' },
      { key: 'Body.pushflag', value: true, desc: '是否持续推送' },
      { key: 'Body.timestamp', value: true, desc: '是否返回时间戳' }
    ]);
    return common.concat([
      { key: 'Body.info.paramtype', value: 2, desc: '列表参数类型；2 表示股票列表' },
      { key: 'Body.info.stockid', value: '[{"marketid":1,"code":"000001"}]', desc: '股票/指数列表；marketid 1 上海，0 深圳' },
      { key: 'Body.sortfield', value: 0, desc: '排序字段编号' },
      { key: 'Body.order', value: true, desc: '是否正序' },
      { key: 'Body.end', value: 3, desc: '返回数量或结束位置' },
      { key: 'Body.respfield', value: '[10,11,96,97,98]', desc: '需要返回的字段编号列表' }
    ]);
  }

  function marketWsRenderFieldRows(type) {
    var table = $('marketWsParams');
    if (!table) return;
    table.querySelectorAll('tr.market-ws-detail-row').forEach(function (row) { row.remove(); });
    var anchor = $('marketWsTypeRow') || ($('marketWsType') && $('marketWsType').closest('tr'));
    if (!anchor) return;
    var html = '<tr class="ws-section-row market-ws-detail-row"><th colspan="2">JSON 消息字段（下方 JSON 编辑器可直接修改）</th></tr>';
    marketWsFieldDefinitions(type).forEach(function (field) {
      html += '<tr class="market-ws-detail-row"><th><code>' + esc(field.key) + '</code><span>示例；' + esc(field.desc) + '</span></th><td><input class="market-param-body" value="' + esc(typeof field.value === 'string' ? field.value : JSON.stringify(field.value)) + '" readonly aria-readonly="true"></td></tr>';
    });
    anchor.insertAdjacentHTML('afterend', html);
  }

  function marketWsConnect() {
    var address = $('marketWsAddress').value.trim();
    if (!address) { wsLog('WebSocket 地址为空', true); return; }
    if (state.socket) { try { state.socket.close(); } catch (_) {} }
    try { state.socket = new WebSocket(address); } catch (error) { wsLog(error.message, true); return; }
    var socket = state.socket;
    marketWsSetState('连接中…');
    marketWsSetControls(false);
    socket.onopen = function () { marketWsSetState('已连接'); marketWsSetControls(true); wsLog('连接成功，代理已自动完成行情鉴权'); };
    socket.onmessage = function (event) { var value = event.data; try { value = JSON.parse(value); } catch (_) {} wsLog(value); };
    socket.onerror = function () { marketWsSetState('错误'); marketWsSetControls(false); wsLog('WebSocket 连接错误', true); };
    socket.onclose = function (event) { marketWsSetState('已断开'); marketWsSetControls(false); wsLog('连接关闭 code=' + event.code + ' reason=' + (event.reason || '')); state.socket = null; };
  }

  function marketWsSend() {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) { wsLog('请先连接 WebSocket', true); return; }
    try { var message = JSON.parse($('marketWsMessage').value); state.socket.send(JSON.stringify(message)); wsLog({ sent: message }); } catch (error) { wsLog('JSON 格式错误：' + error.message, true); }
  }

  function renderEndpointAgain() { renderEndpoint(); }

  window.selectMarketWorkspace = selectMarketWorkspace;
  window.selectLegacyWorkspace = selectLegacyWorkspace;
  window.leaveMarketWorkspace = leaveMarketWorkspace;
  window.selectProductWorkspace = selectProductWorkspace;
  window.productNavActive = setProductActive;
  window.marketRenderWs = marketRenderWs;
  window.marketSelectEndpoint = selectEndpoint;
  window.marketRenderEndpoint = renderEndpointAgain;
  window.marketSendRequest = marketSendRequest;
  window.marketCopyRequest = marketCopyRequest;
  window.marketBodyFieldChanged = marketBodyFieldChanged;
  window.syncMarketBodyFieldsFromEditor = syncMarketBodyFieldsFromEditor;
  window.marketFilterNav = renderList;
  window.marketUpdateStatus = updateMarketStatus;
  window.marketSetCatalog = applyCatalog;
  window.workspaceBaseUrl = baseUrl;
  window.renderLegacyHttpEndpoint = renderLegacyHttpEndpoint;
  window.renderLegacyWsShell = renderLegacyWsShell;
  window.renderUnifiedWorkspace = renderUnifiedWorkspace;
  window.normalizeLegacyWsParams = normalizeLegacyWsParams;
  if (window.__unifiedMarketCatalog) {
    applyCatalog(window.__unifiedMarketCatalog);
    window.__unifiedMarketCatalog = null;
  }
  updateMarketStatus();
}());
