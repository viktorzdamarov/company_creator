/* Shared helpers: JSON API calls, error messages, HTML escaping, autocomplete widget. */
window.Adrobot = (function ($) {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** Human readable message from an API error response. */
  function errorText(xhr) {
    var body = xhr.responseJSON;
    if (!body) {
      if (xhr.status === 0) return "Сервер недоступен. Запущен ли uvicorn?";
      return "Ошибка " + xhr.status + ": " + (xhr.statusText || "unknown");
    }
    if (Array.isArray(body.detail)) {  // FastAPI validation errors
      return body.detail.map(function (e) {
        var field = (e.loc || []).filter(function (p) { return p !== "body"; }).join(".");
        var msg = String(e.msg || "").replace(/^Value error, /, "");
        return (field ? field + ": " : "") + msg;
      }).join("; ");
    }
    return body.detail || ("Ошибка " + xhr.status);
  }

  function api(method, url, data) {
    return $.ajax({
      method: method,
      url: url,
      contentType: data ? "application/json" : undefined,
      data: data ? JSON.stringify(data) : undefined,
      dataType: "json",
    });
  }

  /**
   * Autocomplete on a `.ac` container: input.ac-input, input.ac-value (hidden), ul.ac-list.
   * Source: GET <data-source>?q=... returning [{id, label|name}].
   * opts.onSelect(item) is called on choice.
   */
  function autocomplete($root, opts) {
    opts = opts || {};
    var $input = $root.find(".ac-input");
    var $value = $root.find(".ac-value");
    var $list = $root.find(".ac-list");
    var source = $root.data("source");
    var timer = null, seq = 0, items = [], active = -1;

    function label(it) { return it.label || ("[" + it.id + "] " + it.name); }

    function close() { $list.prop("hidden", true).empty(); active = -1; }

    function render() {
      $list.empty();
      if (!items.length) {
        $list.append('<li class="ac-empty">Ничего не найдено</li>');
      }
      items.forEach(function (it, i) {
        $("<li>").addClass("ac-item").toggleClass("active", i === active)
          .attr("data-i", i).text(label(it)).appendTo($list);
      });
      $list.prop("hidden", false);
    }

    function choose(i) {
      var it = items[i];
      if (!it) return;
      $input.val(label(it));
      $value.val(it.id);
      close();
      if (opts.onSelect) opts.onSelect(it);
    }

    function search() {
      var q = $input.val().trim();
      var my = ++seq;
      $root.addClass("loading");
      $.getJSON(source, { q: q, limit: 15 }).done(function (data) {
        if (my !== seq) return;  // a newer request is in flight
        items = data.slice(0, 15);
        active = items.length ? 0 : -1;
        render();
      }).fail(function (xhr) {
        if (my !== seq) return;
        $list.html('<li class="ac-empty">' + esc(errorText(xhr)) + "</li>").prop("hidden", false);
      }).always(function () { if (my === seq) $root.removeClass("loading"); });
    }

    $input.on("input", function () {
      $value.val("");  // typed text no longer matches the chosen item
      clearTimeout(timer);
      timer = setTimeout(search, 250);
    });
    $input.on("focus", function () { if (!$value.val()) search(); });
    $input.on("keydown", function (e) {
      if ($list.prop("hidden")) return;
      if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length - 1); render(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
      else if (e.key === "Enter") { if (active >= 0) { choose(active); e.preventDefault(); } }
      else if (e.key === "Escape") { close(); }
    });
    $list.on("mousedown", ".ac-item", function (e) { e.preventDefault(); choose(+$(this).attr("data-i")); });
    $input.on("blur", function () { setTimeout(close, 150); });

    return {
      value: function () {
        // chosen item, or a bare numeric ID typed by hand
        var v = $value.val() || $input.val().trim();
        return /^\d+$/.test(v) ? parseInt(v, 10) : null;
      },
      reset: function () { $input.val(""); $value.val(""); close(); },
    };
  }

  function copy(text, $btn) {
    var done = function () { var t = $btn.text(); $btn.text("скопировано ✓"); setTimeout(function () { $btn.text(t); }, 1500); };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done);
  }

  return { esc: esc, api: api, errorText: errorText, autocomplete: autocomplete, copy: copy };
})(jQuery);
