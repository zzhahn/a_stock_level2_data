(function () {
  'use strict';

  var items = [
    { product: 'd1', view: '市场总览', file: 'd1_home.png', desc: '指数、市场宽度、异动与资讯摘要' },
    { product: 'd1', view: '行情概览', file: 'd1_quotes.png', desc: '实时行情与市场结构的组合视图' },
    { product: 'd1', view: '涨停复盘', file: 'd1_limits.png', desc: '涨停池、趋势与历史明细工作区' },
    { product: 'd1', view: '题材板块', file: 'd1_topics.png', desc: '热点主线、板块强弱与相关资讯' },
    { product: 'd1', view: '复盘工作台', file: 'd1_replay.png', desc: '交易日驱动的市场复盘组合页' },
    { product: 'd1', view: '个股分析', file: 'd1_stock.png', desc: '标的报价、走势、盘口与业务明细' },
    { product: 'd1', view: '资讯中心', file: 'd1_news.png', desc: '快讯、专栏、题材与个股资料' },
    { product: 'd1', view: '能力中心', file: 'd1_capabilities.png', desc: '按业务能力选择并查看结构化结果' },
    { product: 'd2', view: '市场总览', file: 'd2_overview.png', desc: '市场宽度、资金、情绪与指数图表' },
    { product: 'd2', view: '个股分析', file: 'd2_stock.png', desc: '走势、资金、K 线与综合诊断' },
    { product: 'd2', view: '专题雷达', file: 'd2_radar.png', desc: '情绪、题材、强势池与异常结构' },
    { product: 'd2', view: '期货分析', file: 'd2_futures.png', desc: '持仓、成交量与期货趋势图表' },
    { product: 'd2', view: '接口调试', file: 'd2_debug.png', desc: '图表看板背后的请求与响应观察台' },
    { product: 'd4', view: '市场列表', file: 'd4_list.png', desc: '品种列表、字段选择与分页读取' },
    { product: 'd4', view: 'K 线', file: 'd4_kline.png', desc: '历史 K 线、成交量与结构化表格' },
    { product: 'd4', view: '资金摘要', file: 'd4_money.png', desc: '单一标的的资金摘要与字段明细' },
    { product: 'd4', view: '分钟历史', file: 'd4_history.png', desc: '分钟级历史行情与时间序列数据' },
    { product: 'd4', view: '分时成交', file: 'd4_trade.png', desc: '分时成交分页、游标与加载状态' },
    { product: 'd6', view: '市场总览', file: 'd6_overview.png', desc: '市场强弱、资金流向、分布与排行' },
    { product: 'd6', view: '个股详情', file: 'd6_stock.png', desc: '实时标的详情、五档与盘中走势' },
    { product: 'd6', view: '行情排行', file: 'd6_rank.png', desc: '排行、板块与横向比较数据' },
    { product: 'd6', view: '资金专题', file: 'd6_capital.png', desc: '资金流向、连接数据与专题统计' },
    { product: 'd6', view: '异动监控', file: 'd6_activity.png', desc: '异动事件、涨跌结构与趋势变化' },
    { product: 'd6', view: '资讯数据', file: 'd6_news.png', desc: '资讯摘要、交易日与跨市场数据' },
    { product: 'd6', view: 'K 线分析', file: 'd6_kline.png', desc: '历史 K 线与指标数据分析' },
    { product: 'd6', view: '接口中心', file: 'd6_api.png', desc: '统一目录、字段字典与请求入口' },
    { product: 'd101', view: '行情全推', file: 'd101_snapshot.png', desc: '5,000+ 行实时行情与窗口化字段渲染' },
    { product: 'd101', view: '盘口异动', file: 'd101_market_event.png', desc: '实时事件流与历史事件拼接' },
    { product: 'd101', view: '字段枚举', file: 'd101gui2.JPG', desc: '字段枚举、语义字段与请求配置' },
    { product: 'd201', view: '实时盘口', file: 'd201_main.png', desc: '全息队列、委托、成交与盘口变化' },
    { product: 'd202', view: '千档盘口', file: 'd202_main.png', desc: '千档深度、队列、大单、委托与成交' }
  ];

  var filter = 'all';
  var query = '';

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (char) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char];
    });
  }

  function filteredItems() {
    return items.filter(function (item) {
      var byProduct = filter === 'all' || item.product === filter;
      var haystack = (item.product + ' ' + item.view + ' ' + item.desc).toLowerCase();
      return byProduct && (!query || haystack.indexOf(query) >= 0);
    });
  }

  function render() {
    var grid = document.getElementById('uiGalleryGrid');
    if (!grid) return;
    var visible = filteredItems();
    var count = document.getElementById('uiGalleryCount');
    if (count) count.textContent = '显示 ' + visible.length + ' / ' + items.length + ' 张';
    if (!visible.length) {
      grid.innerHTML = '<div class="ui-gallery-empty">没有匹配的示例应用画面，换个关键词试试。</div>';
      return;
    }
    grid.innerHTML = visible.map(function (item) {
      var index = items.indexOf(item);
      return '<button type="button" class="ui-gallery-card" data-ui-index="' + index + '" aria-label="查看 ' + esc(item.product + ' ' + item.view) + '">' +
        '<span class="ui-gallery-thumb"><img src="assets/images/ui/' + esc(item.file) + '" alt="' + esc(item.product + ' ' + item.view + ' 基于 data_interface 的示例应用画面') + '" loading="lazy"></span>' +
        '<span class="ui-gallery-card-meta"><span class="ui-gallery-product">' + esc(item.product.toUpperCase()) + '</span><span class="ui-gallery-view">' + esc(item.view) + '</span><span class="ui-gallery-mask">已掩码</span></span>' +
        '<div class="ui-gallery-card-title"><h3>' + esc(item.view) + '</h3><p>' + esc(item.desc) + '</p></div>' +
        '</button>';
    }).join('');
    grid.querySelectorAll('.ui-gallery-card').forEach(function (card) {
      card.addEventListener('click', function () {
        openImage(parseInt(card.getAttribute('data-ui-index'), 10));
      });
    });
  }

  function setFilter(value, element) {
    filter = value || 'all';
    document.querySelectorAll('.ui-gallery-filter').forEach(function (button) {
      button.classList.toggle('active', button === element || button.getAttribute('data-ui-filter') === filter);
    });
    render();
  }

  function openImage(index) {
    var item = items[index];
    var lightbox = document.getElementById('uiGalleryLightbox');
    var image = document.getElementById('uiGalleryLightboxImage');
    var title = document.getElementById('uiGalleryLightboxTitle');
    var code = document.getElementById('uiGalleryLightboxCode');
    var note = document.getElementById('uiGalleryLightboxNote');
    if (!item || !lightbox || !image) return;
    image.src = 'assets/images/ui/' + item.file;
    image.alt = item.product + ' ' + item.view + ' 基于 data_interface 的示例应用画面';
    if (title) title.textContent = item.view;
    if (code) code.textContent = item.product.toUpperCase();
    if (note) note.textContent = item.desc + ' · 基于 data_interface 构建 · 中文名称已掩码';
    lightbox.hidden = false;
    lightbox.setAttribute('aria-hidden', 'false');
    var close = document.getElementById('uiGalleryLightboxClose');
    if (close) close.focus();
  }

  function closeImage() {
    var lightbox = document.getElementById('uiGalleryLightbox');
    if (!lightbox) return;
    lightbox.hidden = true;
    lightbox.setAttribute('aria-hidden', 'true');
  }

  window.toggleUiGallery = function (force) {
    var panel = document.getElementById('uiGallery');
    var trigger = document.getElementById('uiGalleryToggle');
    if (!panel) return;
    var open = force === undefined ? !panel.classList.contains('open') : !!force;
    if (open) {
      if (typeof window.toggleMethodGallery === 'function') window.toggleMethodGallery(false);
      render();
      panel.classList.add('open');
      panel.setAttribute('aria-hidden', 'false');
      if (trigger) {
        trigger.classList.add('active');
        trigger.setAttribute('aria-expanded', 'true');
      }
    } else {
      panel.classList.remove('open');
      panel.setAttribute('aria-hidden', 'true');
      if (trigger) {
        trigger.classList.remove('active');
        trigger.setAttribute('aria-expanded', 'false');
      }
    }
  };

  window.setUiGalleryFilter = setFilter;
  window.openUiGalleryImage = openImage;
  window.closeUiGalleryImage = closeImage;

  function init() {
    var grid = document.getElementById('uiGalleryGrid');
    if (!grid) return;
    var search = document.getElementById('uiGallerySearch');
    if (search) {
      search.addEventListener('input', function () {
        query = String(search.value || '').trim().toLowerCase();
        render();
      });
    }
    document.querySelectorAll('.ui-gallery-filter').forEach(function (button) {
      button.addEventListener('click', function () {
        setFilter(button.getAttribute('data-ui-filter') || 'all', button);
      });
    });
    var lightbox = document.getElementById('uiGalleryLightbox');
    if (lightbox) {
      lightbox.addEventListener('click', function (event) {
        if (event.target === lightbox) closeImage();
      });
    }
    var close = document.getElementById('uiGalleryLightboxClose');
    if (close) close.addEventListener('click', closeImage);
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      var lightboxOpen = lightbox && !lightbox.hidden;
      if (lightboxOpen) closeImage();
      else if (document.getElementById('uiGallery').classList.contains('open')) window.toggleUiGallery(false);
    });
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
