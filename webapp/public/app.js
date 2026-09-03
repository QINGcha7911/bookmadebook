/* ============================================================
 * 私人听书工厂 · 前端逻辑（无框架，原生 JS）
 * 职责：成人/儿童下单、订单页状态轮询、模拟支付（开发）
 * API 基址：生产同源（''）；本地开发静态站(8788) → Worker(8787)
 * ============================================================ */
(function () {
  "use strict";

  /* ── 配置 ─────────────────────────────────────────────── */
  var DEV_WORKER = "http://127.0.0.1:8787";
  // 无 DOM 环境（node 单测 import 本文件）时按生产同源处理，不访问 location
  var HAS_DOM = typeof document !== "undefined" && typeof location !== "undefined";
  var IS_DEV = HAS_DOM &&
    (location.hostname === "127.0.0.1" || location.hostname === "localhost");
  // 本地静态页 8788 与 Worker 8787 不同源 → 显式指到 Worker；
  // 其余情况（Worker 直接访问 / 生产同源 Pages+Workers）用空串
  var API_BASE = IS_DEV && location.port !== "8787" ? DEV_WORKER : "";
  var POLL_MS = 8000;          // 订单状态轮询间隔

  var VOICE_LABEL = {
    husky_tender: "散文温柔沙哑",
    hist_deep_male: "历史深男",
    design_kid: "儿童音"
  };
  var STATUS_LABEL = {
    pending: "等待支付",
    paid: "已支付 · 排队生成中",
    generating: "正在生成",
    done: "已完成",
    failed: "生成失败",
    refunded: "已退款"
  };
  // 状态 → 进度条第几步（1下单 2支付 3生成 4下载）
  var STATUS_STEP = { pending: 1, paid: 2, generating: 3, done: 4, failed: 3, refunded: 2 };

  var state = {
    tab: "adult",
    adultDuration: 20,
    childAge: "7-12",
    childBooks: [],
    orderId: null,
    pollTimer: null
  };

  var $ = function (id) { return document.getElementById(id); };

  /* ── Toast 提示 ───────────────────────────────────────── */
  var toastTimer = null;
  function toast(msg, isErr) {
    var el = $("toast");
    el.textContent = msg;
    el.classList.toggle("err", !!isErr);
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.add("hidden"); }, 3500);
  }

  /* ── 通用请求 ─────────────────────────────────────────── */
  function api(path, opts) {
    return fetch(API_BASE + path, Object.assign(
      { headers: { "Content-Type": "application/json" } },
      opts
    )).then(function (res) {
      return res.json().catch(function () { return { ok: false, error: "响应解析失败" }; })
        .then(function (data) {
          data._status = res.status;
          return data;
        });
    });
  }

  /* ── Tab 切换 ─────────────────────────────────────────── */
  function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".tab").forEach(function (b) {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    document.querySelectorAll(".panel").forEach(function (p) {
      p.classList.toggle("active", p.id === "panel-" + tab);
    });
  }

  /* ── 分段选择器（时长/年龄） ──────────────────────────── */
  function bindSeg(segId, onPick) {
    $(segId).addEventListener("click", function (e) {
      var btn = e.target.closest(".seg-item");
      if (!btn) return;
      $(segId).querySelectorAll(".seg-item").forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      onPick(btn.dataset.value);
    });
  }

  /* ── 儿童书单加载（GET /api/books） ───────────────────── */
  function loadBooks() {
    api("/api/books").then(function (data) {
      var sel = $("child-book");
      if (!data.ok || !Array.isArray(data.list)) {
        sel.innerHTML = "<option value=\"\">书单加载失败，请刷新重试</option>";
        return;
      }
      state.childBooks = data.list;
      sel.innerHTML = "<option value=\"\">请选择一本</option>" + data.list.map(function (b) {
        return "<option value=\"" + b.id + "\" data-age=\"" + b.age.join(",") + "\">" +
          b.title + "（" + b.author + "）</option>";
      }).join("");
      sel.addEventListener("change", updateBookNote);
      updateBookNote();
    }).catch(function () {
      $("child-book").innerHTML = "<option value=\"\">无法连接服务，请稍后重试</option>";
    });
  }

  /* 选中书后：更新备注 + 按适龄档过滤年龄按钮 */
  function updateBookNote() {
    var sel = $("child-book");
    var opt = sel.options[sel.selectedIndex];
    var book = state.childBooks.find(function (b) { return b.id === sel.value; });
    $("child-book-note").textContent = book ? book.note + " · 适龄 " + book.age.join(" / ") : "";

    var allowed = opt && opt.dataset.age ? opt.dataset.age.split(",") : ["3-6", "7-12"];
    document.querySelectorAll("#child-age .seg-item").forEach(function (b) {
      var ok = allowed.indexOf(b.dataset.value) >= 0;
      b.style.display = ok ? "" : "none";
      if (!ok && b.classList.contains("active")) {
        var first = document.querySelector("#child-age .seg-item");
        while (first && first.style.display === "none") { first = first.nextElementSibling; }
        if (first) {
          first.classList.add("active");
          state.childAge = first.dataset.value;
        }
        b.classList.remove("active");
      }
    });
  }

  /* ── 提交订单 ─────────────────────────────────────────── */
  /* payload 构建抽成纯函数：handler 与 node 回归测试共用同一份真实逻辑 */
  function buildAdultPayload(title, durationMin, voice, email) {
    return {
      product_type: "adult",
      book_title: title,
      duration_min: durationMin,
      voice: voice,
      email: email
    };
  }

  /* declared 由 handler 在勾选校验通过后固定传 true（后端强制家长声明） */
  function buildChildPayload(bookId, ageBand, email, declared) {
    return {
      product_type: "child",
      book_id: bookId,
      age_band: ageBand,
      parent_declared: declared,
      email: email
    };
  }

  function submitOrder(payload) {
    var btn = document.activeElement;
    if (btn) { btn.disabled = true; btn.textContent = "提交中…"; }
    return api("/api/order", {
      method: "POST",
      body: JSON.stringify(payload)
    }).then(function (data) {
      if (btn) { btn.disabled = false; btn.textContent = "提交订单"; }
      if (!data.ok) { toast(data.error || "下单失败", true); return; }
      if (!data.order || !data.order.order_id) { toast("下单异常：缺少订单号", true); return; }
      showOrder(data.order);
    }).catch(function (err) {
      if (btn) { btn.disabled = false; btn.textContent = "提交订单"; }
      toast("网络错误：" + err.message, true);
    });
  }

  function onSubmitAdult(e) {
    e.preventDefault();
    var title = $("adult-title").value.trim();
    var email = $("adult-email").value.trim();
    if (title.length < 2) { toast("请输入书名（至少 2 个字）", true); return; }
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) {
      toast("请输入正确的邮箱", true); return;
    }
    submitOrder(buildAdultPayload(title, Number(state.adultDuration), $("adult-voice").value, email));
  }

  function onSubmitChild(e) {
    e.preventDefault();
    var email = $("child-email").value.trim();
    var bookId = $("child-book").value;
    if (!bookId) { toast("请从书单中选择一本", true); return; }
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) {
      toast("请输入家长邮箱", true); return;
    }
    if (!$("child-declare").checked) {
      toast("请勾选「本人为未成年子女点播」声明", true); return;
    }
    submitOrder(buildChildPayload(bookId, state.childAge, email, true));
  }

  /* ── 订单页渲染 ───────────────────────────────────────── */
  function fmtTime(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    var p = function (n) { return n < 10 ? "0" + n : "" + n; };
    return p(d.getHours()) + ":" + p(d.getMinutes());
  }

  function showOrder(order) {
    document.querySelectorAll(".panel").forEach(function (p) { p.classList.remove("active"); });
    $("order-view").classList.add("active");
    $("order-view").classList.remove("hidden");

    state.orderId = order.order_id;
    $("order-type-title").textContent =
      order.product_type === "child" ? "儿童点播已提交" : "订单已创建";
    $("order-id").textContent = order.order_id;
    $("order-book").textContent = order.book_title + (order.age_band ? "（" + order.age_band + " 岁档）" : "");
    $("order-voice").textContent = VOICE_LABEL[order.voice] || order.voice;
    $("order-amount").textContent = "¥" + order.amount_yuan;

    // 预计完成 ≈ 创建时间 + eta 分钟（本地时区展示）
    if (order.created_at && order.eta_min) {
      var d = new Date(order.created_at);
      d.setMinutes(d.getMinutes() + order.eta_min);
      $("order-eta").textContent = fmtTime(d.toISOString()) + "（约" + order.eta_min + "分钟后）";
    } else {
      $("order-eta").textContent = "—";
    }

    startPolling();
    renderOrder(order);
    if (IS_DEV) console.log("[bookmadebook] order:", order);
  }

  function renderOrder(order) {
    var statusEl = $("order-status");
    statusEl.textContent = STATUS_LABEL[order.status] || order.status;
    statusEl.className = "badge " + (order.status === "done" ? "done" :
      (order.status === "failed" || order.status === "refunded" ? "failed" : ""));

    // 进度条
    var step = STATUS_STEP[order.status] || 1;
    document.querySelectorAll(".step").forEach(function (s) {
      var n = Number(s.dataset.step);
      s.classList.toggle("done", n < step);
      s.classList.toggle("current", n === step);
    });

    // 支付区：pending 显示（真实爱发电下一轮接入，本地开发提供模拟按钮）
    $("pay-box").classList.toggle("hidden", order.status !== "pending");
    $("pay-link").setAttribute("href",
      "https://afdian.com/order/" + order.order_id + "?from=bookmadebook-mvp"); // 占位链接
    $("mock-pay").classList.toggle("hidden", !IS_DEV);

    // 下载按钮：R2 + daemon（下一轮）就绪前恒为占位
    var dl = $("download-btn");
    if (order.status === "done") {
      dl.disabled = false;
      dl.textContent = "下载音频";
      dl.onclick = function () {
        toast("下载通道（R2 存储）下一轮接入，敬请期待");
      };
    } else {
      dl.disabled = true;
      dl.textContent = "下载音频（生成完成后开放）";
      dl.onclick = null;
    }
  }

  /* ── 状态轮询（GET /api/order/:id） ───────────────────── */
  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(function () {
      if (!state.orderId) return;
      api("/api/order/" + state.orderId).then(function (data) {
        if (data.ok && data.order) {
          renderOrder(data.order);
          var s = data.order.status;
          if (s === "done" || s === "failed" || s === "refunded") stopPolling();
        }
      }).catch(function () { /* 网络抖动静默，下轮再试 */ });
    }, POLL_MS);
  }
  function stopPolling() {
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  /* ── 支付动作 ─────────────────────────────────────────── */
  function mockPay() {
    if (!state.orderId) return;
    api("/api/pay-callback", {
      method: "POST",
      body: JSON.stringify({ order_id: state.orderId, voucher: "mock-voucher-001" })
    }).then(function (data) {
      if (data.ok) { toast("模拟支付成功，订单已入队"); renderOrder(data.order); }
      else { toast(data.error || "模拟支付失败", true); }
    }).catch(function (err) { toast("网络错误：" + err.message, true); });
  }

  /* ── 回到首页 ─────────────────────────────────────────── */
  function backHome() {
    stopPolling();
    state.orderId = null;
    switchTab(state.tab); // 保留当前 tab 心智
    $("order-view").classList.add("hidden");
  }

  /* ── 初始化 ───────────────────────────────────────────── */
  function init() {
    document.querySelectorAll(".tab").forEach(function (b) {
      b.addEventListener("click", function () { switchTab(b.dataset.tab); });
    });
    bindSeg("adult-duration", function (v) { state.adultDuration = Number(v); });
    bindSeg("child-age", function (v) { state.childAge = v; });

    $("form-adult").addEventListener("submit", onSubmitAdult);
    $("form-child").addEventListener("submit", onSubmitChild);
    $("mock-pay").addEventListener("click", mockPay);
    $("refresh-status").addEventListener("click", function () {
      if (!state.orderId) return;
      api("/api/order/" + state.orderId).then(function (data) {
        if (data.ok && data.order) { renderOrder(data.order); toast("状态已刷新"); }
        else { toast(data.error || "查询失败", true); }
      }).catch(function (err) { toast("网络错误：" + err.message, true); });
    });
    $("back-home").addEventListener("click", backHome);

    // 家长声明勾选态联动样式
    $("child-declare").addEventListener("change", function (e) {
      e.target.closest(".check").classList.toggle("checked", e.target.checked);
    });

    loadBooks();
  }

  if (HAS_DOM) document.addEventListener("DOMContentLoaded", init);

  // 暴露 payload 构建器：浏览器挂 window，node 单测挂 globalThis
  var testable = {
    buildAdultPayload: buildAdultPayload,
    buildChildPayload: buildChildPayload
  };
  if (typeof window !== "undefined") {
    window.bookmadebook = testable;
  } else {
    globalThis.bookmadebook = testable;
  }
})();
